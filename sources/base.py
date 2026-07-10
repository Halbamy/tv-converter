from __future__ import annotations

from abc import ABC, abstractmethod
import threading

from models import Recording


class RecordingSource(ABC):
    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    @abstractmethod
    def get_recordings(self) -> list[Recording]:
        raise NotImplementedError

    @abstractmethod
    def wait_for_changes(self, control_event: threading.Event) -> bool:
        """Wait until a source scan is required.

        Return True when the source should be scanned and False when the app
        control event interrupted the wait.
        """
        raise NotImplementedError

    def changes_pending(self) -> bool:
        return False

    def mark_scanned(self) -> None:
        pass
