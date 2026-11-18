#!/usr/bin/env python3
"""Read-only health signals for triage suggestions.

These functions only read existing logs and status files under the house
root. They never write to those trees, never enter private/, never send
mail, never freeze a routine, and never restore a backup. Suggestions
are just suggestions until tag set / scan --apply writes a tag (and a
chart note) in this folder.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import paths
import tags


@dataclass
class Suggestion:
    part: str
    tag: str
    reason: str
    source: str

    def as_dict(self) -> dict[str, str]:
        return {
            "part": self.part,
            "tag": self.tag,
            "reason": self.reason,
            "source": self.source,
        }


def _safe(path: Path, house: Path) -> Path | None:
    if paths.is_private_path(path, house):
        return None
    return path


def _read_text(path: Path, house: Path) -> str | None:
    target = _safe(path, house)
    if target is None or not target.is_file():
        return None
    try:
        return target.read_text(encoding="utf-8")
    except OSError:
        return None


def _parse_ts(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=paths.TZ)
    return stamp.astimezone(paths.TZ)


def suggest_defense(house: Path, *, integrity_report: dict[str, Any] | None = None) -> Suggestion:
    """Integrity mismatch is red. Empty injection logs are not an emergency."""
    report = integrity_report if integrity_report is not None else _live_integrity()
    if report.get("error"):
        return Suggestion(
            "defense",
            "yellow",
            report["error"],
            "integrity",
        )
    added = list(report.get("added") or [])
    removed = list(report.get("removed") or [])
    changed = list(report.get("changed") or [])
    if added or removed or changed:
        # Keep the reason short enough for the chart. Names only, no hashes.
        seen = []
        for rel in added + changed + removed:
            head = rel.split("/")[0]
            if head not in seen:
                seen.append(head)
        sample = ", ".join(seen[:5])
        return Suggestion(
            "defense",
            "red",
            (
                f"Integrity mismatch: {len(added)} added, {len(changed)} changed, "
                f"{len(removed)} removed (areas: {sample}). Not accepted. "
                "The owner should review, then integrity.py accept or a new baseline."
            ),
            "integrity",
        )
    return Suggestion(
        "defense",
        "green",
        f"Integrity check clean ({report.get('file_count', '?')} watched files).",
        "integrity",
    )


def _live_integrity() -> dict[str, Any]:
    """Read-only compare against the live manifest. Never saves or accepts."""
    defense_dir = paths.house_root() / "defense"
    if str(defense_dir) not in sys.path:
        sys.path.insert(0, str(defense_dir))
    try:
        import integrity as integrity_mod
    except Exception as exc:  # pragma: no cover - import environment
        return {"error": f"Could not import integrity.py: {exc}"}
    manifest_path = integrity_mod.MANIFEST_PATH
    if not manifest_path.is_file():
        return {"error": "No integrity manifest found."}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected = manifest.get("files", {})
        current = integrity_mod.scan()
    except Exception as exc:
        return {"error": f"Integrity scan failed to read: {exc}"}
    added = sorted(set(current) - set(expected))
    removed = sorted(set(expected) - set(current))
    changed = sorted(
        rel for rel in (set(current) & set(expected)) if current[rel] != expected[rel]
    )
    return {
        "added": added,
        "removed": removed,
        "changed": changed,
        "file_count": len(current),
    }


# Image and music API models have a known free-tier quota of 0. A 429
# on those alone is not a house health problem once a separate
# manual backup path is in play. Text / ask 429s still count as yellow.
IMAGE_MUSIC_SUBCOMMANDS = frozenset({"imagine", "music"})
IMAGE_MUSIC_HINTS = ("image", "lyria", "imagen", "nano-banana")
CONSULTANT_BACKUP_NOTE = (
    "API image/music quota 0 is a known limit, covered by a separate "
    "manual backup path"
)


def _is_image_or_music_row(row: dict) -> bool:
    sub = str(row.get("subcommand") or "").strip().lower()
    if sub in IMAGE_MUSIC_SUBCOMMANDS:
        return True
    blobs = [str(row.get("model") or "")]
    for key in ("models_tried", "models_requested"):
        values = row.get(key) or []
        if isinstance(values, (list, tuple)):
            blobs.extend(str(v) for v in values)
        else:
            blobs.append(str(values))
    hay = " ".join(blobs).lower()
    return any(hint in hay for hint in IMAGE_MUSIC_HINTS)


def _web_backup_proven(house: Path) -> bool:
    path = house / "gemini" / "web" / "test-image-1.png"
    return bool(_safe(path, house) and path.is_file())


def suggest_consultant(house: Path) -> Suggestion:
    log = house / "gemini" / "logs" / "calls.jsonl"
    text = _read_text(log, house)
    if text is None:
        if (house / "gemini").is_dir():
            return Suggestion("consultant", "yellow", "Consultant folder is present but the call log is missing.", "consultant-log")
        return Suggestion("consultant", "yellow", "Consultant folder was not found under the house root.", "consultant-log")
    saw_ok = False
    saw_429_media = 0
    saw_429_core = 0
    saw_fail = 0
    for raw in text.splitlines():
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        error = str(row.get("error") or "")
        if row.get("ok") is True:
            saw_ok = True
        elif "429" in error or "quota" in error.lower():
            if _is_image_or_music_row(row):
                saw_429_media += 1
            else:
                saw_429_core += 1
        else:
            saw_fail += 1
    if saw_429_core:
        return Suggestion(
            "consultant",
            "yellow",
            (
                f"Consultant had {saw_429_core} HTTP 429 / quota failure(s) on text "
                f"or other core models"
                f"{' (some calls have also succeeded)' if saw_ok else ''}. "
                "Quota issues are yellow, not a freeze."
            ),
            "consultant-log",
        )
    if saw_429_media:
        if _web_backup_proven(house):
            return Suggestion("consultant", "green", CONSULTANT_BACKUP_NOTE, "consultant-log")
        return Suggestion(
            "consultant",
            "green",
            (
                "API image/music quota 0 is a known limit"
                + (
                    "; text calls are otherwise healthy."
                    if saw_ok
                    else ". No text 429s in the current log."
                )
            ),
            "consultant-log",
        )
    if saw_fail and not saw_ok:
        return Suggestion(
            "consultant",
            "yellow",
            f"Consultant call log has {saw_fail} failure(s) and no successful calls.",
            "consultant-log",
        )
    return Suggestion(
        "consultant",
        "green",
        "Consultant call log looks healthy (no 429s in the current log)."
        if saw_ok or not saw_fail
        else f"Consultant has {saw_fail} non-quota failure(s) but also successful calls.",
        "consultant-log",
    )


def suggest_range(house: Path) -> Suggestion:
    kill = house / "range" / "KILL"
    if _safe(kill, house) and kill.is_file():
        return Suggestion(
            "range",
            "yellow",
            "Range kill switch is on (RANGE COLD). A training miss is not a medical event; this just notes the range is cold.",
            "range-kill",
        )
    if not (house / "range").is_dir():
        return Suggestion("range", "yellow", "Range folder was not found under the house root.", "range-kill")
    return Suggestion(
        "range",
        "green",
        "Range kill switch is off. Qual scores are training notes, not vitals.",
        "range-kill",
    )


def suggest_pride(house: Path) -> Suggestion:
    log = house / "pride" / "logs" / "pride.jsonl"
    if not log.is_file():
        return Suggestion("pride", "yellow", "Pride log was not found.", "pride-log")
    pride_dir = house / "pride"
    if str(pride_dir) not in sys.path:
        sys.path.insert(0, str(pride_dir))
    try:
        import journal as pride_journal
    except Exception as exc:
        return Suggestion("pride", "yellow", f"Could not import pride journal: {exc}", "pride-log")
    try:
        pride_journal.verify_chain(log)
    except Exception as exc:
        return Suggestion("pride", "red", f"Pride log chain does not verify: {exc}", "pride-log")
    return Suggestion("pride", "green", "Pride log chain verifies. Pride is not a vital sign.", "pride-log")


def suggest_backups(house: Path, *, now: datetime | None = None) -> Suggestion:
    folder = house / "memory-backups"
    if paths.is_private_path(folder, house):
        return Suggestion("backups", "yellow", "Backup path refused (private/).", "backups")
    if not folder.is_dir():
        return Suggestion("backups", "red", "memory-backups/ folder is missing.", "backups")
    dates: list[datetime] = []
    for path in folder.glob("memory-*.md"):
        stem = path.stem.replace("memory-", "")
        try:
            dates.append(datetime.strptime(stem, "%Y-%m-%d").replace(tzinfo=paths.TZ))
        except ValueError:
            continue
    if not dates:
        return Suggestion("backups", "yellow", "No dated memory-*.md snapshots found.", "backups")
    latest = max(dates)
    stamp = now or paths.now()
    latest_s = latest.date().isoformat()
    # Filename dates have no clock. Treat "yesterday" as still on time
    # until tonight's nightly run, "two days ago" as yellow, older as red.
    days_behind = (stamp.date() - latest.date()).days
    if days_behind <= 1:
        return Suggestion(
            "backups",
            "green",
            f"Last memory snapshot is {latest_s}. Tonight's nightly run is still ahead."
            if days_behind == 1
            else f"Last memory snapshot is {latest_s}.",
            "backups",
        )
    if days_behind == 2:
        return Suggestion(
            "backups",
            "yellow",
            f"Last memory snapshot is {latest_s}, two days ago. A missed backup is yellow, not a coma.",
            "backups",
        )
    return Suggestion(
        "backups",
        "red",
        f"Last memory snapshot is {latest_s}, {days_behind} days ago. Needs a decision, not an automatic restore.",
        "backups",
    )


def suggest_drive(house: Path) -> Suggestion:
    config = house / "gemini" / "drive-folder.json"
    if config.is_file() and _safe(config, house):
        return Suggestion(
            "drive",
            "green",
            "Local Consultant Drive folder config is present. This check does not call Google.",
            "drive-config",
        )
    return Suggestion(
        "drive",
        "yellow",
        "No local Consultant Drive folder config was found. Not a freeze.",
        "drive-config",
    )


def suggest_pet(house: Path) -> Suggestion:
    pet = house / "pet" / "pet.json"
    text = _read_text(pet, house)
    if text is None:
        return Suggestion("pet", "yellow", "The pet's pet.json was not found.", "pet")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return Suggestion("pet", "yellow", "The pet's pet.json could not be parsed.", "pet")
    status = str(data.get("status") or "")
    health = data.get("stats", {}).get("health") if isinstance(data.get("stats"), dict) else None
    if status.lower() == "hibernating":
        return Suggestion("pet", "yellow", "The pet is hibernating (soft neglect). Not a house emergency.", "pet")
    try:
        if health is not None and float(health) <= 0:
            return Suggestion("pet", "yellow", "The pet's health is at 0. Not a house emergency.", "pet")
    except (TypeError, ValueError):
        pass
    return Suggestion("pet", "green", "The pet's pet.json is present and it is not in crisis.", "pet")


def suggest_failsafe(house: Path) -> Suggestion:
    state = house / "failsafe" / "state.json"
    text = _read_text(state, house)
    if text is None:
        return Suggestion(
            "failsafe",
            "red",
            "failsafe/state.json is missing. Status only; this kit does not read letters.",
            "failsafe",
        )
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return Suggestion("failsafe", "yellow", "failsafe/state.json could not be parsed. Letters were not read.", "failsafe")
    sent = data.get("letter_sent")
    return Suggestion(
        "failsafe",
        "green",
        f"Failsafe state file is present (letter_sent={sent}). Status only; letters were not read.",
        "failsafe",
    )


def suggest_routines(house: Path) -> Suggestion:
    log = house / "self-check-log.md"
    text = _read_text(log, house)
    if text is None:
        return Suggestion(
            "routines",
            "yellow",
            "No self-check-log.md to read. Routines were not started, stopped, or listed.",
            "self-check",
        )
    return Suggestion(
        "routines",
        "green",
        "self-check-log.md is present. This kit does not start or stop routines.",
        "self-check",
    )


def suggest_medical() -> Suggestion:
    path = paths.chart_path()
    if not path.is_file():
        return Suggestion("medical", "green", "Chart is new and empty. Chain will start at genesis.", "chart")
    try:
        import chart as chart_mod

        chart_mod.verify_chain(path)
    except Exception as exc:
        return Suggestion("medical", "red", f"Medical chart chain does not verify: {exc}", "chart")
    return Suggestion("medical", "green", "Medical chart chain verifies.", "chart")


def _overlay_flags(items: list[Suggestion]) -> list[Suggestion]:
    """Keep scan from greening a part the pen or a tourniquet has isolated."""
    try:
        import guard
    except Exception:
        return items
    pen_on = False
    cuffs: tuple[str, ...] = ()
    try:
        pen_on = guard.pen_is_on()
        cuffs = guard.isolated_parts()
    except Exception:
        return items
    out: list[Suggestion] = []
    for item in items:
        if item.part == "medical" and pen_on and item.tag == "green":
            out.append(
                Suggestion(
                    "medical",
                    "yellow",
                    "Morphine pen (safe mode) is on. Ordinary writes are frozen. Server-side routines were not paused.",
                    "safemode",
                )
            )
            continue
        if item.part in cuffs and item.tag == "green":
            out.append(
                Suggestion(
                    item.part,
                    "yellow",
                    f"Tourniquet is on for {item.part}. Writes and runs for that part are isolated.",
                    "tourniquet",
                )
            )
            continue
        out.append(item)
    return out


def collect(
    house: Path | None = None,
    *,
    now: datetime | None = None,
    integrity_report: dict[str, Any] | None = None,
) -> list[Suggestion]:
    root = house or paths.house_root()
    return _overlay_flags(
        [
            suggest_defense(root, integrity_report=integrity_report),
            suggest_range(root),
            suggest_consultant(root),
            suggest_pet(root),
            suggest_routines(root),
            suggest_pride(root),
            suggest_backups(root, now=now),
            suggest_drive(root),
            suggest_failsafe(root),
            suggest_medical(),
        ]
    )


def format_suggestions(items: Iterable[Suggestion]) -> str:
    lines = ["Suggested tags from read-only vitals (not applied):", ""]
    for item in items:
        lines.append(f"  {item.part:<10} {item.tag:<8} {item.reason}")
    lines.append("")
    lines.append("Apply with: medic.py scan --apply   (never auto-applies black)")
    return "\n".join(lines)
