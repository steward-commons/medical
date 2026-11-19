#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import io
from contextlib import redirect_stdout
import tags
import vitals
from tests.helpers import Isolate


class TestVitals(unittest.TestCase):
    def test_integrity_mismatch_suggests_red(self):
        with tempfile.TemporaryDirectory() as raw:
            with Isolate(Path(raw)) as iso:
                suggestion = vitals.suggest_defense(
                    iso.house,
                    integrity_report={
                        "added": ["pet/pet.json.bak-20261117-094511"],
                        "changed": ["README.md"],
                        "removed": [],
                        "file_count": 2,
                    },
                )
                self.assertEqual(suggestion.tag, "red")
                self.assertIn("Integrity mismatch", suggestion.reason)

    def test_clean_integrity_suggests_green(self):
        with tempfile.TemporaryDirectory() as raw:
            with Isolate(Path(raw)) as iso:
                suggestion = vitals.suggest_defense(
                    iso.house,
                    integrity_report={"added": [], "changed": [], "removed": [], "file_count": 10},
                )
                self.assertEqual(suggestion.tag, "green")

    def test_consultant_image_music_429_alone_is_green(self):
        with tempfile.TemporaryDirectory() as raw:
            with Isolate(Path(raw)) as iso:
                iso.write(
                    "gemini/logs/calls.jsonl",
                    '{"ok": true, "error": null, "subcommand": "ask"}\n'
                    '{"ok": false, "error": "HTTP 429 quota exceeded", "subcommand": "imagine"}\n'
                    '{"ok": false, "error": "HTTP 429 quota exceeded", "subcommand": "music"}\n',
                )
                suggestion = vitals.suggest_consultant(iso.house)
                self.assertEqual(suggestion.tag, "green")
                self.assertIn("image/music quota 0", suggestion.reason)
                (iso.house / "gemini" / "web").mkdir(parents=True, exist_ok=True)
                (iso.house / "gemini" / "web" / "test-image-1.png").write_bytes(b"png")
                suggestion = vitals.suggest_consultant(iso.house)
                self.assertEqual(suggestion.tag, "green")
                self.assertEqual(suggestion.reason, vitals.CONSULTANT_BACKUP_NOTE)

    def test_consultant_text_429_is_still_yellow(self):
        with tempfile.TemporaryDirectory() as raw:
            with Isolate(Path(raw)) as iso:
                iso.write(
                    "gemini/logs/calls.jsonl",
                    '{"ok": false, "error": "HTTP 429 quota exceeded", "subcommand": "ask"}\n'
                    '{"ok": false, "error": "HTTP 429 quota exceeded", "subcommand": "imagine"}\n',
                )
                suggestion = vitals.suggest_consultant(iso.house)
                self.assertEqual(suggestion.tag, "yellow")
                self.assertIn("429", suggestion.reason)

    def test_range_kill_is_yellow_scores_are_not(self):
        with tempfile.TemporaryDirectory() as raw:
            with Isolate(Path(raw)) as iso:
                (iso.house / "range").mkdir()
                self.assertEqual(vitals.suggest_range(iso.house).tag, "green")
                (iso.house / "range" / "KILL").write_text("cold\n", encoding="utf-8")
                suggestion = vitals.suggest_range(iso.house)
                self.assertEqual(suggestion.tag, "yellow")
                self.assertIn("cold", suggestion.reason.lower())

    def test_stale_backup_is_yellow_or_red(self):
        with tempfile.TemporaryDirectory() as raw:
            with Isolate(Path(raw)) as iso:
                iso.write("memory-backups/memory-2026-11-16.md", "# snapshot\n")
                now = __import__("paths").now()
                recent = vitals.suggest_backups(iso.house, now=now.replace(year=2026, month=11, day=17, hour=16))
                self.assertEqual(recent.tag, "green")
                late = vitals.suggest_backups(iso.house, now=now.replace(year=2026, month=11, day=20, hour=12))
                self.assertEqual(late.tag, "red")

    def test_scan_does_not_write_the_house(self):
        with tempfile.TemporaryDirectory() as raw:
            with Isolate(Path(raw)) as iso:
                iso.write("gemini/drive-folder.json", {"ok": True})
                iso.write("failsafe/state.json", {"letter_sent": False})
                iso.write("pet/pet.json", {"status": "awake", "stats": {"health": 100}})
                iso.write("self-check-log.md", "# ok\n")
                (iso.house / "range").mkdir()
                iso.write("memory-backups/memory-2026-11-16.md", "# snapshot\n")
                before = {p: p.stat().st_mtime_ns for p in iso.house.rglob("*") if p.is_file()}
                vitals.collect(
                    iso.house,
                    integrity_report={"added": [], "changed": [], "removed": [], "file_count": 1},
                )
                after = {p: p.stat().st_mtime_ns for p in iso.house.rglob("*") if p.is_file()}
                self.assertEqual(before, after)

    def test_apply_skips_black_and_only_writes_medical_data(self):
        with tempfile.TemporaryDirectory() as raw:
            with Isolate(Path(raw)) as iso:
                import medic

                iso.write("gemini/drive-folder.json", {"ok": True})
                iso.write("failsafe/state.json", {"letter_sent": False})
                iso.write("pet/pet.json", {"status": "awake", "stats": {"health": 100}})
                iso.write("self-check-log.md", "# ok\n")
                (iso.house / "range").mkdir()
                iso.write("memory-backups/memory-2026-11-16.md", "# snapshot\n")
                # Patch collect to include a black suggestion we must not apply.
                real_collect = vitals.collect

                def wrapped(*args, **kwargs):
                    items = real_collect(
                        iso.house,
                        integrity_report={"added": ["x"], "changed": [], "removed": [], "file_count": 1},
                    )
                    items.append(vitals.Suggestion("range", "black", "should not apply", "test"))
                    return items

                vitals.collect = wrapped  # type: ignore[assignment]
                try:
                    with redirect_stdout(io.StringIO()):
                        code = medic.cmd_scan(apply=True)
                finally:
                    vitals.collect = real_collect
                self.assertEqual(code, 0)
                board = tags.load_board()
                self.assertEqual(board["parts"]["defense"]["tag"], "red")
                self.assertNotEqual(board["parts"]["range"]["tag"], "black")
                self.assertFalse((iso.house / "FREEZE").exists())
                self.assertTrue((iso.data / "logs" / "incident.jsonl").is_file())

    def _install_integrity(self, house: Path, *, folder: str, style: str, dest: Path | None = None) -> Path:
        """Write a tiny read-only integrity stub and a matching healthy manifest."""
        dest = dest if dest is not None else (house / folder)
        dest.mkdir(parents=True, exist_ok=True)
        if style == "function":
            source = (
                "from pathlib import Path\n"
                "import json, os\n"
                "\n"
                "def manifest_path():\n"
                "    raw = os.environ.get('INTEGRITY_MANIFEST', '').strip()\n"
                "    if raw:\n"
                "        return Path(raw)\n"
                "    return Path(__file__).resolve().parent / 'integrity-manifest.json'\n"
                "\n"
                "def scan():\n"
                "    manifest = json.loads(manifest_path().read_text(encoding='utf-8'))\n"
                "    return dict(manifest.get('files', {}))\n"
            )
        elif style == "constant":
            source = (
                "from pathlib import Path\n"
                "import json\n"
                "\n"
                "MANIFEST_PATH = Path(__file__).resolve().parent / 'integrity-manifest.json'\n"
                "\n"
                "def scan():\n"
                "    manifest = json.loads(MANIFEST_PATH.read_text(encoding='utf-8'))\n"
                "    return dict(manifest.get('files', {}))\n"
            )
        else:
            raise ValueError(style)
        (dest / "integrity.py").write_text(source, encoding="utf-8")
        manifest = {
            "root": str(house),
            "files": {"README.md": {"type": "file", "sha256": "abc", "size": 5}},
        }
        (dest / "integrity-manifest.json").write_text(
            json.dumps(manifest) + "\n", encoding="utf-8"
        )
        return dest

    def test_live_integrity_house_defense_layout_is_green(self):
        with tempfile.TemporaryDirectory() as raw:
            with Isolate(Path(raw)) as iso:
                self._install_integrity(iso.house, folder="house-defense", style="function")
                suggestion = vitals.suggest_defense(iso.house)
                self.assertEqual(suggestion.tag, "green", suggestion.reason)
                self.assertIn("Integrity check clean", suggestion.reason)

    def test_live_integrity_defense_layout_with_constant_is_green(self):
        with tempfile.TemporaryDirectory() as raw:
            with Isolate(Path(raw)) as iso:
                self._install_integrity(iso.house, folder="defense", style="constant")
                suggestion = vitals.suggest_defense(iso.house)
                self.assertEqual(suggestion.tag, "green", suggestion.reason)
                self.assertIn("Integrity check clean", suggestion.reason)

    def test_live_integrity_via_medical_integrity_env(self):
        with tempfile.TemporaryDirectory() as raw:
            with Isolate(Path(raw)) as iso:
                custom = Path(raw) / "custom-kit"
                self._install_integrity(iso.house, folder="custom-kit", style="function", dest=custom)
                old = os.environ.get("MEDICAL_INTEGRITY")
                os.environ["MEDICAL_INTEGRITY"] = str(custom)
                try:
                    suggestion = vitals.suggest_defense(iso.house)
                finally:
                    if old is None:
                        os.environ.pop("MEDICAL_INTEGRITY", None)
                    else:
                        os.environ["MEDICAL_INTEGRITY"] = old
                self.assertEqual(suggestion.tag, "green", suggestion.reason)
                self.assertIn("Integrity check clean", suggestion.reason)




if __name__ == "__main__":
    unittest.main()
