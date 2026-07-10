from __future__ import annotations

from collections import deque
from collections.abc import Iterable

from models import Recording


class RecordingQueue:
    def __init__(self):
        self._queue: deque[Recording] = deque()
        self._known: set[str] = set()

    def __len__(self) -> int:
        return len(self._queue)

    def add_new(self, recordings: Iterable[Recording]) -> int:
        added = 0

        for recording in recordings:
            key = self._key(recording)

            if key in self._known:
                continue

            self._known.add(key)
            self._queue.append(recording)
            added += 1

        return added

    def pop(self) -> Recording | None:
        if not self._queue:
            return None

        return self._queue.popleft()

    def _key(self, recording: Recording) -> str:
        return f"{recording.source}:{recording.recording_id}:{recording.filename}"
