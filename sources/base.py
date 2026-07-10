from __future__ import annotations

from abc import ABC, abstractmethod

from models import Recording


class RecordingSource(ABC):
    @abstractmethod
    def get_recordings(self) -> list[Recording]:
        raise NotImplementedError
