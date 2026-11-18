#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chart
import guard
import tags
from tests.helpers import Isolate
from tests.test_cli import run


class TestTourniquet(unittest.TestCase):
    def test_apply_and_release_one_part(self):
        with tempfile.TemporaryDirectory() as raw:
            with Isolate(Path(raw)):
                code, out, err = run(
                    ["tourniquet", "--on", "consultant", "--reason", "Looping image calls."]
                )
                self.assertEqual(code, 0, err)
                self.assertEqual(guard.isolated_parts(), ("consultant",))
                self.assertIsNotNone(guard.blocked("consultant"))
                self.assertIsNone(guard.blocked("pride"))
                self.assertIsNone(guard.blocked("medical"))
                self.assertFalse(guard.pen_is_on())
                self.assertEqual(tags.load_board()["parts"]["consultant"]["tag"], "yellow")
                code, out, err = run(["tourniquet", "--off", "consultant"])
                self.assertEqual(code, 0, err)
                self.assertEqual(guard.isolated_parts(), ())
                self.assertIsNone(guard.blocked("consultant"))
                self.assertEqual(tags.load_board()["parts"]["consultant"]["tag"], "yellow")
                self.assertIn("released", tags.load_board()["parts"]["consultant"]["reason"].lower())
                self.assertTrue(any(e["kind"] == "tourniquet" for e in chart.read_events()))

    def test_refuses_medical_and_critical_without_ok(self):
        with tempfile.TemporaryDirectory() as raw:
            with Isolate(Path(raw)):
                code, out, err = run(
                    ["tourniquet", "--on", "medical", "--reason", "Should fail."]
                )
                self.assertEqual(code, 2)
                self.assertIn("cannot be tourniqueted", err.lower())
                self.assertEqual(guard.isolated_parts(), ())
                code, out, err = run(
                    ["tourniquet", "--on", "defense", "--reason", "Should need an OK."]
                )
                self.assertEqual(code, 2)
                self.assertIn("critical", err.lower())
                self.assertEqual(guard.isolated_parts(), ())
                code, out, err = run(
                    [
                        "tourniquet",
                        "--on",
                        "defense",
                        "--reason",
                        "Owner confirmed a temporary isolate.",
                        "--i-have-owner-ok",
                    ]
                )
                self.assertEqual(code, 0, err)
                self.assertEqual(guard.isolated_parts(), ("defense",))

    def test_status_lists_cuffs(self):
        with tempfile.TemporaryDirectory() as raw:
            with Isolate(Path(raw)):
                run(["tourniquet", "--on", "range", "--reason", "Bay would not clean up."])
                code, out, err = run(["tourniquet", "--status"])
                self.assertEqual(code, 0, err)
                self.assertIn("range: ON", out)
                self.assertIn("Morphine pen: off", out)


if __name__ == "__main__":
    unittest.main()
