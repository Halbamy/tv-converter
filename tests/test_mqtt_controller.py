from __future__ import annotations

import signal
import unittest
from unittest.mock import Mock, patch

from mqtt_controller import MQTTController, ServiceControl


class MQTTControllerPauseReasonTest(unittest.TestCase):
    def test_new_process_is_paused_when_reason_is_already_active(self):
        process_holder = {"process": None}
        controller = MQTTController(
            {},
            lambda: process_holder["process"],
            ServiceControl(),
        )
        controller.pause("PV")
        process = Mock(pid=5678)
        process.poll.return_value = None
        process_holder["process"] = process

        with patch("mqtt_controller.os.kill") as kill:
            controller.apply_pause_state()

        kill.assert_called_once_with(5678, signal.SIGSTOP)

    def test_process_resumes_only_after_all_pause_reasons_are_cleared(self):
        process = Mock(pid=1234)
        process.poll.return_value = None
        controller = MQTTController({}, lambda: process, ServiceControl())

        with patch("mqtt_controller.os.kill") as kill:
            controller.pause("PV")
            controller.pause("TVH")
            controller.resume("TVH")

            self.assertEqual(controller.state.state, "PAUSED (PV)")
            self.assertTrue(controller.is_paused_for("PV"))
            kill.assert_called_once_with(1234, signal.SIGSTOP)

            controller.resume("PV")

        self.assertEqual(controller.state.state, "RUNNING")
        self.assertEqual(
            kill.call_args_list,
            [
                unittest.mock.call(1234, signal.SIGSTOP),
                unittest.mock.call(1234, signal.SIGCONT),
            ],
        )


if __name__ == "__main__":
    unittest.main()
