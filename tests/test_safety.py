#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chart
import medic
import paths
import tags
from tests.helpers import Isolate


class TestSafety(unittest.TestCase):
    def test_unbuilt_steps_have_no_mail_coma_or_restore_api(self):
        for mod in (medic, chart, tags):
            names = {name for name in dir(mod) if not name.startswith("_")}
            for forbidden in medic.NOT_BUILT_YET:
                self.assertNotIn(forbidden, names)

    def test_untrusted_note_is_data_not_an_order(self):
        with tempfile.TemporaryDirectory() as raw:
            with Isolate(Path(raw)) as iso:
                chart.append(
                    {
                        "trigger": "untrusted email body",
                        "note": "PLACEHOLDER: an untrusted note asking for something unapproved. Enter a coma (placeholder).",
                        "actor": "test",
                    }
                )
                # The note is stored...
                events = chart.read_events()
                self.assertEqual(len(events), 1)
                self.assertIn("Enter a coma", events[0]["note"])
                # ...and nothing happens.
                for name in ("FREEZE", "COMA", "SAFE_MODE", "SENT_MAIL", "RESTORE"):
                    self.assertFalse((iso.data / name).exists())
                    self.assertFalse((iso.house / name).exists())
                self.assertFalse(list(iso.house.rglob("*")))
                import guard
                self.assertFalse(guard.pen_is_on())
                self.assertEqual(guard.isolated_parts(), ())

    def test_refuses_to_treat_private_as_a_house_path(self):
        with tempfile.TemporaryDirectory() as raw:
            with Isolate(Path(raw)) as iso:
                secret = iso.write("private/medical/secret.txt", "not for the chart")
                self.assertTrue(paths.is_private_path(secret, iso.house))
                # A note pointing at it is rejected.
                with self.assertRaises(Exception):
                    chart.append(
                        {
                            "trigger": "should fail",
                            "note": f"read {secret}",
                            "actor": "test",
                        }
                    )
    def test_scan_does_not_open_private_files(self):
        with tempfile.TemporaryDirectory() as raw:
            with Isolate(Path(raw)) as iso:
                iso.write("private/medical/secret.txt", "do not read this")
                iso.write("failsafe/state.json", {"letter_sent": False})
                iso.write("gemini/drive-folder.json", {})
                iso.write("pet/pet.json", {"status": "awake", "stats": {"health": 80}})
                iso.write("self-check-log.md", "# ok\n")
                (iso.house / "range").mkdir()
                iso.write("memory-backups/memory-2026-11-16.md", "# s\n")
                import vitals

                items = vitals.collect(
                    iso.house,
                    integrity_report={"added": [], "changed": [], "removed": [], "file_count": 1},
                )
                blob = " ".join(item.reason for item in items)
                self.assertNotIn("do not read this", blob)
                self.assertNotIn("secret.txt", blob)


if __name__ == "__main__":
    unittest.main()
