from pathlib import Path
from types import SimpleNamespace
import unittest

from recording_queue import RecordingQueue


def recording(recording_id: str):
    return SimpleNamespace(
        source="test",
        recording_id=recording_id,
        filename=Path(f"/{recording_id}.ts"),
    )


def recording_at(recording_id: str, filename: str):
    return SimpleNamespace(
        source="tvheadend",
        recording_id=recording_id,
        filename=Path(filename),
    )


class RecordingQueueProgressTests(unittest.TestCase):
    def test_changed_path_does_not_enqueue_same_recording_again(self):
        queue = RecordingQueue()
        queue.add_new([recording_at("same-uuid", "/recordings/old.ts")])
        queue.pop()

        added = queue.add_new(
            [recording_at("same-uuid", "/recordings/converted.mkv")]
        )

        self.assertEqual(added, 0)
        self.assertEqual(len(queue), 0)

    def test_current_advances_for_each_recording(self):
        queue = RecordingQueue()
        first = recording("first")
        second = recording("second")

        queue.add_new([first, second])

        self.assertIs(queue.pop(), first)
        self.assertEqual((queue.current, queue.total), (1, 2))
        self.assertIs(queue.pop(), second)
        self.assertEqual((queue.current, queue.total), (2, 2))

    def test_new_recordings_extend_an_active_batch(self):
        queue = RecordingQueue()
        queue.add_new([recording("first"), recording("second")])
        queue.pop()

        queue.add_new([recording("third")])

        self.assertEqual((queue.current, queue.total), (1, 3))
        queue.pop()
        self.assertEqual((queue.current, queue.total), (2, 3))

    def test_new_batch_restarts_progress_after_queue_is_empty(self):
        queue = RecordingQueue()
        queue.add_new([recording("first")])
        queue.pop()

        queue.add_new([recording("second")])

        self.assertEqual((queue.current, queue.total), (0, 1))
        queue.pop()
        self.assertEqual((queue.current, queue.total), (1, 1))


if __name__ == "__main__":
    unittest.main()
