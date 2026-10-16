"""Tests for single-host generation selection. Uses no Cognee database."""

import tempfile
import unittest
from pathlib import Path

from cognee_community_connector_opensiro_vsm.activation import (
    AUDIT_SCHEMA,
    Candidate,
    publish,
    read_active,
)
from cognee_community_connector_opensiro_vsm.source import SourceError


def candidate(sha: str, dataset: str, tag: str, count: int) -> Candidate:
    return Candidate(
        commit=sha,
        dataset=dataset,
        tag=tag,
        expected_count=count,
        audit={
            "schema": AUDIT_SCHEMA,
            "status": "PASS",
            "index_commit": sha,
            "dataset": dataset,
            "source_tag": tag,
            "documents": count,
            "accepted_harnesses": count,
            "exact_grades": count * 6,
            "states_exact": True,
            "source_refs_exact": True,
        },
    )


class SwitchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.old = candidate("1" * 40, "old-dataset", "source-old", 2)
        self.new = candidate("2" * 40, "new-dataset", "source-new", 3)

    def test_initial_and_new_generation_publish(self):
        self.assertIsNone(read_active(self.root))
        first = publish(self.root, self.old, None)
        self.assertEqual(first["sequence"], 1)
        self.assertEqual(first["commit"], self.old.commit)
        second = publish(self.root, self.new, first["selection_id"])
        self.assertEqual(second["sequence"], 2)
        self.assertEqual(second["commit"], self.new.commit)
        self.assertEqual(read_active(self.root), second)

    def test_atomic_failpoint_preserves_active(self):
        first = publish(self.root, self.old, None)
        before = (self.root / "active.json").read_bytes()
        with self.assertRaisesRegex(SourceError, "interruption"):
            publish(self.root, self.new, first["selection_id"], inject_failure="before_swap")
        self.assertEqual((self.root / "active.json").read_bytes(), before)
        self.assertEqual(read_active(self.root), first)
        self.assertEqual(list(self.root.glob(".staged-pointer-*.json")), [])

    def test_recovery_after_aborted_publish(self):
        first = publish(self.root, self.old, None)
        with self.assertRaises(SourceError):
            publish(self.root, self.new, first["selection_id"], inject_failure="before_swap")
        new = publish(self.root, self.new, first["selection_id"])
        again = publish(self.root, self.new, new["selection_id"])
        self.assertEqual(new, again)
        self.assertEqual(again["sequence"], 2)

    def test_stale_writer_rejected(self):
        first = publish(self.root, self.old, None)
        publish(self.root, self.new, first["selection_id"])
        with self.assertRaisesRegex(SourceError, "Stale"):
            publish(self.root, self.old, first["selection_id"])

    def test_wrong_receipt_never_publishes(self):
        untrusted = candidate("2" * 40, "new-dataset", "source-new", 3)
        audit = dict(untrusted.audit)
        audit["source_refs_exact"] = False
        with self.assertRaisesRegex(SourceError, "exact grades"):
            publish(
                self.root,
                Candidate(untrusted.commit, untrusted.dataset, untrusted.tag, 3, audit),
                None,
            )
        self.assertIsNone(read_active(self.root))

    def test_different_dataset_same_source_commit_rejected(self):
        first = publish(self.root, self.old, None)
        other = candidate(self.old.commit, "alternative-dataset", "source-alt", 2)
        with self.assertRaisesRegex(SourceError, "Same source commit"):
            publish(self.root, other, first["selection_id"])

    def test_different_receipt_same_generation_rejected(self):
        first = publish(self.root, self.old, None)
        audit = dict(self.old.audit)
        audit["extra_marker"] = True
        modified = Candidate(self.old.commit, self.old.dataset, self.old.tag, 2, audit)
        with self.assertRaisesRegex(SourceError, "different independent audit"):
            publish(self.root, modified, first["selection_id"])

    def test_corrupt_pointer_fails_closed(self):
        (self.root / "active.json").write_text('{"schema":"wrong","commit":"abc"}')
        with self.assertRaisesRegex(SourceError, "schema"):
            read_active(self.root)
        with self.assertRaises(SourceError):
            publish(self.root, self.old, None)

    def test_refuses_invalid_sha_and_cardinality(self):
        bad = candidate("invalid", "old-dataset", "source-old", 2)
        with self.assertRaises(SourceError):
            publish(self.root, bad, None)
        bad = candidate("1" * 40, "old-dataset", "source-old", 0)
        with self.assertRaises(SourceError):
            publish(self.root, bad, None)


if __name__ == "__main__":
    unittest.main()
