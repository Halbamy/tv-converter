from __future__ import annotations

from collections import deque
from collections.abc import Iterable

from models import Recording


class RecordingQueue:
    def __init__(self):
        self._queue: deque[Recording] = deque()
        self._known: set[str] = set()
        self._current = 0
        self._total = 0

    def __len__(self) -> int:
        return len(self._queue)

    @property
    def current(self) -> int:
        return self._current

    @property
    def total(self) -> int:
        return self._total

    def add_new(self, recordings: Iterable[Recording]) -> int:
        if not self._queue:
            self._current = 0
            self._total = 0

        added = 0

        for recording in recordings:
            key = self._key(recording)

            if key in self._known:
                continue

            self._known.add(key)
            self._queue.append(recording)
            added += 1

        self._total += added

        return added

    def pop(self) -> Recording | None:
        if not self._queue:
            return None

        recording = self._queue.popleft()
        self._current += 1
        return recording

    def _key(self, recording: Recording) -> str:
        return f"{recording.source}:{recording.recording_id}"
