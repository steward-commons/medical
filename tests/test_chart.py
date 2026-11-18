#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chart
from tests.helpers import Isolate


class TestChartAppendOnly(unittest.TestCase):
    def _note(self, ident: str, note: str = "logged a symptom") -> dict:
        return {
            "id": ident,
            "trigger": "unit test",
            "note": note,
            "actor": "test",
        }

    def test_append_does_not_change_prior_lines(self):
        with tempfile.TemporaryDirectory() as raw:
            with Isolate(Path(raw)) as iso:
                path = iso.data / "logs" / "incident.jsonl"
                chart.append(self._note("one", "first note"), log_file=path)
                before = path.read_bytes()
                chart.append(self._note("two", "second note"), log_file=path)
                after = path.read_bytes()
                self.assertTrue(after.startswith(before))
                self.assertGreater(len(after), len(before))
                lines = after.splitlines()
                self.assertEqual(len(lines), 2)
                self.assertEqual(json.loads(lines[0])["id"], "one")

    def test_hash_chain_verifies(self):
        with tempfile.TemporaryDirectory() as raw:
            with Isolate(Path(raw)) as iso:
                path = iso.data / "logs" / "incident.jsonl"
                chart.append(self._note("one"), log_file=path)
                chart.append(self._note("two"), log_file=path)
                chart.verify_chain(path)
                events = chart.read_events(path)
                self.assertEqual(events[0]["prev_hash"], chart.GENESIS_HASH)
                first = path.read_text(encoding="utf-8").splitlines()[0]
                self.assertEqual(events[1]["prev_hash"], chart.line_hash(first))

    def test_tampered_line_breaks_the_chain(self):
        with tempfile.TemporaryDirectory() as raw:
            with Isolate(Path(raw)) as iso:
                path = iso.data / "logs" / "incident.jsonl"
                chart.append(self._note("one"), log_file=path)
                chart.append(self._note("two"), log_file=path)
                lines = path.read_text(encoding="utf-8").splitlines()
                first = json.loads(lines[0])
                first["note"] = "edited after the fact"
                path.write_text(
                    json.dumps(first, separators=(",", ":"), sort_keys=True)
                    + "\n"
                    + lines[1]
                    + "\n",
                    encoding="utf-8",
                )
                with self.assertRaises(chart.ChartTampered):
                    chart.verify_chain(path)

    def test_no_rewrite_or_delete_api(self):
        forbidden = {
            "rewrite",
            "overwrite",
            "delete_record",
            "truncate",
            "edit",
            "replace_log",
            "remove_event",
            "rewrite_log",
        }
        names = {name for name in dir(chart) if not name.startswith("_")}
        self.assertTrue(forbidden.isdisjoint(names))

    def test_secrets_are_rejected(self):
        with tempfile.TemporaryDirectory() as raw:
            with Isolate(Path(raw)) as iso:
                path = iso.data / "logs" / "incident.jsonl"
                with self.assertRaises(Exception):
                    chart.append(
                        self._note("secret", "vault password is hunter2"),
                        log_file=path,
                    )
                with self.assertRaises(Exception):
                    chart.append(
                        self._note("priv", "see ../private/medical/notes.txt"),
                        log_file=path,
                    )
                self.assertFalse(path.is_file() and path.read_text(encoding="utf-8").strip())

    def test_readable_view(self):
        with tempfile.TemporaryDirectory() as raw:
            with Isolate(Path(raw)) as iso:
                path = iso.data / "logs" / "incident.jsonl"
                chart.append(self._note("one", "Integrity mismatch on defense."), log_file=path)
                text = chart.format_chart(chart.read_events(path))
                self.assertIn("Append-only", text)
                self.assertIn("Integrity mismatch on defense.", text)
                self.assertIn("unit test", text)


if __name__ == "__main__":
    unittest.main()
