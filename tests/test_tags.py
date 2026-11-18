#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chart
import tags
from tests.helpers import Isolate


class TestTags(unittest.TestCase):
    def test_set_writes_a_chart_note(self):
        with tempfile.TemporaryDirectory() as raw:
            with Isolate(Path(raw)):
                tags.set_tag("defense", "red", reason="Integrity mismatch for the test.", actor="test")
                board = tags.load_board()
                self.assertEqual(board["parts"]["defense"]["tag"], "red")
                events = chart.read_events()
                self.assertEqual(len(events), 1)
                self.assertEqual(events[0]["kind"], "tag")
                self.assertEqual(events[0]["tag"], "red")
                self.assertIn("Integrity mismatch", events[0]["note"])

    def test_clearing_red_stays_in_the_chart(self):
        with tempfile.TemporaryDirectory() as raw:
            with Isolate(Path(raw)):
                tags.set_tag("defense", "red", reason="Integrity mismatch for the test.", actor="test")
                tags.set_tag("defense", "green", reason="The owner accepted the baseline.", actor="test")
                events = chart.read_events()
                self.assertEqual(len(events), 2)
                self.assertEqual(events[0]["tag"], "red")
                self.assertEqual(events[1]["tag"], "green")
                self.assertIn("was red", events[1]["ended"])
                self.assertEqual(tags.load_board()["parts"]["defense"]["tag"], "green")

    def test_black_on_critical_needs_owner(self):
        with tempfile.TemporaryDirectory() as raw:
            with Isolate(Path(raw)):
                with self.assertRaises(tags.TagError) as ctx:
                    tags.set_tag(
                        "defense",
                        "black",
                        reason="Suspected compromise in a fixture.",
                        actor="test",
                        owner_ok=False,
                    )
                self.assertIn("owner", str(ctx.exception))
                self.assertIsNone(tags.load_board()["parts"]["defense"]["tag"])
                events = chart.read_events()
                self.assertEqual(events[0]["kind"], "refused")
                self.assertEqual(events[0]["ended"], "refused")

    def test_black_on_critical_with_ok_still_does_not_freeze(self):
        with tempfile.TemporaryDirectory() as raw:
            with Isolate(Path(raw)) as iso:
                tags.set_tag(
                    "defense",
                    "black",
                    reason="The owner approved a test black tag.",
                    actor="test",
                    owner_ok=True,
                )
                self.assertEqual(tags.load_board()["parts"]["defense"]["tag"], "black")
                # No freeze artifact is created in the house or the medical folder.
                for name in ("FREEZE", "COMA", "SAFE_MODE", "KILL"):
                    self.assertFalse((iso.data / name).exists())
                    self.assertFalse((iso.house / name).exists())

    def test_unknown_part_is_rejected(self):
        with tempfile.TemporaryDirectory() as raw:
            with Isolate(Path(raw)):
                with self.assertRaises(tags.TagError):
                    tags.set_tag("kitchen", "green", reason="not a real part")


if __name__ == "__main__":
    unittest.main()
