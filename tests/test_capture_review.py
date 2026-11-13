import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import capture_review as review
import capture_runtime as runtime


class CaptureReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(
            dir=Path(__file__).resolve().parents[1], prefix="synthetic-review-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state_path = self.root / "state.v2"
        self.session_path = self.root / "sessions.json"
        self.history = [
            {"role": "user", "content": "baseline", "timestamp": "2026-11-01T10:00:00+08:00"},
            {"role": "assistant", "content": "same reply", "timestamp": "2026-11-01T10:01:00+08:00"},
            {"role": "assistant", "content": "same reply", "timestamp": "2026-11-01T10:02:00+08:00"},
        ]
        self.data = {"sessions": {"s1": {"id": "s1", "history": self.history},
                                  "s2": {"id": "s2", "history": []}},
                     "user_sessions": {"owner1": ["s1"], "owner2": ["s2"]},
                     "active_session": {"owner1": "s1", "owner2": "s2"}}
        self.state = {"version": 2, "salt": "a" * 32, "review_flags": ["initial_boundary_unverified"],
                      "channels": {}}
        for channel, owner in (("s1", "owner1"), ("s2", "owner2")):
            history = self.data["sessions"][channel]["history"]
            self.state["channels"][channel] = {
                "active": channel, "owner": runtime.digest(self.state["salt"], owner, b"capture-owner\0"),
                "sessions": {channel: {"cursor": len(history), "prefix": runtime.prefix(self.state["salt"], history, len(history)),
                                       "synthetic_pending": False, "pending": None,
                                       "review": ([{"start": 0, "end": 1, "reason": "baseline_unverified"},
                                                   {"start": 1, "end": 3, "reason": "assistant_unverified"}]
                                                  if history else [])}}}
        self.appended = []
        self.common = SimpleNamespace(CAPTURE_STATE_FILE=str(self.root / "state"),
                                      SESSION_FILE=str(self.session_path), CFG={},
                                      append_raw=self.append)
        self.save_inputs()

    def save_inputs(self):
        self.session_path.write_text(json.dumps(self.data), encoding="utf-8")
        runtime.save_state(str(self.state_path), self.state)

    def read_state(self):
        return runtime.read_json(str(self.state_path))

    def append(self, *args):
        state = self.read_state()
        runtime.validate_state(state)
        entry = state["channels"]["s1"]["sessions"]["s1"]
        self.assertEqual(entry["pending"], {"index": 3})
        self.assertIn("review_append_index", entry)
        self.appended.append(args)

    def test_identical_replies_are_distinct_generated_records(self):
        self.assertEqual(review.review(self.common), 2)
        self.assertEqual(len(self.appended), 2)
        self.assertNotEqual(self.appended[0][-1], self.appended[1][-1])
        self.assertTrue(all(item[1].startswith(review.GENERATED) for item in self.appended))
        state = self.read_state()
        self.assertEqual(state["review_flags"], ["initial_boundary_unverified"])
        entry = state["channels"]["s1"]["sessions"]["s1"]
        self.assertEqual(entry["review"], [{"start": 0, "end": 1, "reason": "baseline_unverified"}])
        self.assertEqual(entry["cursor"], 3)
        self.assertIsNone(entry["pending"])
        self.assertEqual(review.review(self.common), 0)

    def test_dry_run_does_not_write_or_create_lock(self):
        before = self.state_path.read_bytes()
        self.assertEqual(review.review(self.common, dry_run=True), 2)
        self.assertEqual(self.state_path.read_bytes(), before)
        self.assertFalse(Path(str(self.state_path) + ".lock").exists())
        self.assertEqual(self.appended, [])

    def test_changed_prefix_blocks_without_append(self):
        self.history[1]["content"] = "changed"
        self.session_path.write_text(json.dumps(self.data), encoding="utf-8")
        with self.assertRaisesRegex(runtime.CaptureError, "history_continuity_unproven"):
            review.review(self.common)
        self.assertEqual(self.appended, [])

    def test_changed_owner_blocks_without_append(self):
        self.state["channels"]["s1"]["owner"] = "b" * 64
        self.save_inputs()
        with self.assertRaisesRegex(runtime.CaptureError, "channel_owner_changed"):
            review.review(self.common)
        self.assertEqual(self.appended, [])

    def test_invalid_timestamp_preflights_all_records(self):
        self.history[2]["timestamp"] = "bad-date"
        entry = self.state["channels"]["s1"]["sessions"]["s1"]
        entry["prefix"] = runtime.prefix(self.state["salt"], self.history, 3)
        self.save_inputs()
        with self.assertRaisesRegex(runtime.CaptureError, "invalid_history_timestamp"):
            review.review(self.common)
        self.assertEqual(self.appended, [])
        self.assertIsNone(self.read_state()["channels"]["s1"]["sessions"]["s1"]["pending"])

    def test_missing_historical_pointer_blocks_all_mode(self):
        self.state["channels"]["s1"]["sessions"]["old"] = copy.deepcopy(
            self.state["channels"]["s1"]["sessions"]["s1"])
        self.save_inputs()
        with self.assertRaisesRegex(runtime.CaptureError, "session_owner_changed"):
            review.review(self.common, all_sessions=True)
        self.assertEqual(self.appended, [])

    def test_append_failure_keeps_durable_pending_and_blocks_retry(self):
        def fail(*args):
            raise OSError("uncertain write")
        self.common.append_raw = fail
        with self.assertRaisesRegex(runtime.CaptureError, "append_outcome_uncertain"):
            review.review(self.common)
        self.assertIsNotNone(self.read_state()["channels"]["s1"]["sessions"]["s1"]["pending"])
        with self.assertRaisesRegex(runtime.CaptureError, "append_outcome_uncertain"):
            review.review(self.common)

    def test_post_append_checkpoint_failure_keeps_pending(self):
        save = runtime.save_state
        calls = 0
        def save_then_fail(path, state):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("checkpoint failed")
            return save(path, state)
        with patch.object(runtime, "save_state", side_effect=save_then_fail):
            with self.assertRaises(OSError):
                review.review(self.common)
        self.assertEqual(len(self.appended), 1)
        with self.assertRaisesRegex(runtime.CaptureError, "append_outcome_uncertain"):
            review.review(self.common)

    def test_shared_capture_lock_blocks_review(self):
        with runtime.locked(str(self.state_path)):
            with self.assertRaisesRegex(runtime.CaptureError, "capture_busy"):
                review.review(self.common)
        self.assertEqual(self.appended, [])


if __name__ == "__main__":
    unittest.main()
