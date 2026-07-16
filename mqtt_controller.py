from __future__ import annotations

import json
import os
import signal
import threading
import time
from collections.abc import Callable
from typing import Any

from models import PVState, VERSION

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None


class ServiceControl:
    def __init__(self):
        self.stop_requested = False
        self.reload_requested = False


class MQTTController:
    def __init__(self, config: dict, process_getter: Callable, control: ServiceControl):
        self.config = config or {}
        self.process_getter = process_getter
        self.control = control
        self.enabled = bool(self.config.get("enabled", False))
        self.state = PVState(power="----", state="RUNNING", last_message=time.time(), mqtt_alive=True)
        self.client = None
        self.stop_event = threading.Event()
        self._pause_lock = threading.Lock()
        self._pause_reasons: set[str] = set()
        self.last_payload: dict[str, Any] | None = None
        self.topic_prefix = self.config.get("topic_prefix", "tv-converter").rstrip("/")
        self.status_topic = f"{self.topic_prefix}/status"
        self.control_topic = f"{self.topic_prefix}/control"

    def start(self) -> None:
        self.stop_event.clear()

        if not self.enabled:
            return

        if mqtt is None:
            raise RuntimeError("paho-mqtt is not installed")

        self.client = mqtt.Client()
        self.client.will_set(self.status_topic, json.dumps({"state": "offline"}), retain=True)

        if self.config.get("username") or self.config.get("password"):
            self.client.username_pw_set(self.config.get("username"), self.config.get("password"))

        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.connect(self.config["broker"], int(self.config.get("port", 1883)), 60)
        self.client.loop_start()
        self.publish_status({"state": "online"})
        threading.Thread(target=self._watchdog, daemon=True).start()

    def stop(self) -> None:
        self.stop_event.set()
        self.publish_status({"state": "stopped"})

        if self.client is not None:
            self.client.loop_stop()
            self.client.disconnect()
            self.client = None

    def publish_status(self, payload: dict[str, Any]) -> None:
        if not self.enabled or self.client is None:
            return

        data = {"version": VERSION, **payload}

        if data == self.last_payload:
            return

        self.last_payload = data
        self.client.publish(self.status_topic, json.dumps(data, ensure_ascii=False), retain=True)

    def publish_runtime_status(self, **kwargs) -> None:
        payload = {key: value for key, value in kwargs.items() if value is not None}
        self.publish_status(payload)

    def _on_connect(self, client, userdata, flags, rc, properties=None) -> None:
        self.state.mqtt_alive = True
        self.state.last_message = time.time()
        client.subscribe(self.config["topic"])
        client.subscribe(self.control_topic)

    def _json_path(self, data: dict, path: str):
        current = data

        for part in path.split("."):
            current = current[part]

        return current

    def _on_message(self, client, userdata, msg) -> None:
        topic = msg.topic
        payload = msg.payload.decode("utf-8", errors="replace").strip()

        if topic == self.control_topic:
            self._handle_control(payload)
            return

        self.state.last_message = time.time()
        self.state.mqtt_alive = True
        self.resume("MQTT")

        try:
            data = json.loads(payload)
            power_curr = float(self._json_path(data, self.config.get("json_path", "ZPA.Power_curr")))
        except Exception:
            return

        surplus = int(-power_curr)
        self.state.power = str(surplus)

        if surplus >= int(self.config.get("resume_watt", 50)):
            self.resume("PV")
        elif surplus <= int(self.config.get("pause_watt", 0)):
            self.pause("PV")

    def _handle_control(self, command: str) -> None:
        command = command.lower().strip()

        if command == "pause":
            self.pause("MANUAL")
        elif command == "resume":
            self.resume("MANUAL")
        elif command == "stop":
            self.control.stop_requested = True
            self.terminate_process()

    def _watchdog(self) -> None:
        timeout = int(self.config.get("timeout_seconds", 30))

        while not self.stop_event.is_set():
            time.sleep(5)

            if time.time() - self.state.last_message > timeout:
                if self.state.mqtt_alive:
                    self.state.mqtt_alive = False
                    self.state.power = "----"
                    self.pause("MQTT")

    def pause(self, reason: str) -> None:
        reason = reason.upper()

        with self._pause_lock:
            already_paused = bool(self._pause_reasons)
            self._pause_reasons.add(reason)
            self._update_pause_state()

        if already_paused:
            return

        self._signal_process(signal.SIGSTOP)

    def resume(self, reason: str = "MANUAL") -> None:
        reason = reason.upper()

        with self._pause_lock:
            if reason not in self._pause_reasons:
                return

            self._pause_reasons.remove(reason)
            should_resume = not self._pause_reasons
            self._update_pause_state()

        if should_resume:
            self._signal_process(signal.SIGCONT)

    def is_paused_for(self, reason: str) -> bool:
        with self._pause_lock:
            return reason.upper() in self._pause_reasons

    def apply_pause_state(self) -> None:
        """Pause a newly started process when any pause reason is active."""
        with self._pause_lock:
            should_pause = bool(self._pause_reasons)

        if should_pause:
            self._signal_process(signal.SIGSTOP)

    def _update_pause_state(self) -> None:
        if not self._pause_reasons:
            self.state.state = "RUNNING"
            return

        reasons = ", ".join(sorted(self._pause_reasons))
        self.state.state = f"PAUSED ({reasons})"

    def _signal_process(self, sig: signal.Signals) -> None:
        process = self.process_getter()

        if process is not None and process.poll() is None:
            try:
                os.kill(process.pid, sig)
            except ProcessLookupError:
                pass

    def terminate_process(self) -> None:
        process = self.process_getter()

        if process is not None and process.poll() is None:
            try:
                os.kill(process.pid, signal.SIGCONT)
            except ProcessLookupError:
                return
            process.terminate()
