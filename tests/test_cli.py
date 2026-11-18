#!/usr/bin/env python3
from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import medic
import tags
from tests.helpers import Isolate


def run(argv: list[str]) -> tuple[int, str, str]:
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = medic.main(argv)
    return code, out.getvalue(), err.getvalue()


class TestCLI(unittest.TestCase):
    def test_chart_add_and_show(self):
        with tempfile.TemporaryDirectory() as raw:
            with Isolate(Path(raw)):
                code, out, err = run(
                    [
                        "chart",
                        "add",
                        "--trigger",
                        "The owner asked how is the house",
                        "--note",
                        "Opening the chart for step 1.",
                    ]
                )
                self.assertEqual(code, 0, err)
                self.assertIn("Chart note 1 appended", out)
                code, out, err = run(["chart", "show"])
                self.assertEqual(code, 0, err)
                self.assertIn("Append-only", out)
                self.assertIn("Opening the chart for step 1.", out)

    def test_tag_set_and_list(self):
        with tempfile.TemporaryDirectory() as raw:
            with Isolate(Path(raw)):
                code, out, err = run(
                    [
                        "tag",
                        "set",
                        "consultant",
                        "yellow",
                        "--reason",
                        "HTTP 429 on image calls, text still works.",
                    ]
                )
                self.assertEqual(code, 0, err)
                self.assertIn("consultant", out)
                self.assertIn("yellow", out)
                code, out, err = run(["tag", "list"])
                self.assertEqual(code, 0, err)
                self.assertIn("yellow", out)

    def test_secret_note_is_rejected(self):
        with tempfile.TemporaryDirectory() as raw:
            with Isolate(Path(raw)):
                code, out, err = run(
                    [
                        "chart",
                        "add",
                        "--trigger",
                        "bad",
                        "--note",
                        "here is the api key " + "AIza" + "Sy" + "A" * 26,
                    ]
                )
                self.assertEqual(code, 2)
                self.assertIn("secret", err.lower())

    def test_status_mentions_visibility_only(self):
        with tempfile.TemporaryDirectory() as raw:
            with Isolate(Path(raw)) as iso:
                iso.write("failsafe/state.json", {"letter_sent": False})
                iso.write("gemini/drive-folder.json", {})
                iso.write("pet/pet.json", {"status": "awake", "stats": {"health": 80}})
                iso.write("self-check-log.md", "# ok\n")
                (iso.house / "range").mkdir()
                iso.write("memory-backups/memory-2026-11-16.md", "# s\n")
                code, out, err = run(["status"])
                self.assertEqual(code, 0, err)
                self.assertIn("step 2", out.lower())
                self.assertIn("Morphine pen: off", out)
                self.assertIn("Tourniquets: none", out)
                self.assertIn("No mail", out)


if __name__ == "__main__":
    unittest.main()
