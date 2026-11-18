#!/usr/bin/env python3
"""Shared paths and time helpers for House Medical (step 2: chart, tags, pen, tourniquet).

The live tree is this folder. Tests may redirect data with
MEDICAL_DATA so they never touch the live chart or tags.
The house root (for read-only vitals) is the current directory, overridable
with MEDICAL_HOUSE. This kit never walks into private/.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Chicago")
TZ_LABEL = "America/Chicago"

CODE_ROOT = Path(__file__).resolve().parent
DEFAULT_HOUSE = Path.cwd()
PRIVATE_DIR_NAME = "private"


def data_root() -> Path:
    raw = os.environ.get("MEDICAL_DATA")
    return Path(raw).resolve() if raw else CODE_ROOT


def house_root() -> Path:
    raw = os.environ.get("MEDICAL_HOUSE")
    return Path(raw).resolve() if raw else DEFAULT_HOUSE


def logs_dir() -> Path:
    return data_root() / "logs"


def chart_path() -> Path:
    return logs_dir() / "incident.jsonl"


def chart_lock_path() -> Path:
    return logs_dir() / "incident.jsonl.lock"


def tags_path() -> Path:
    return data_root() / "tags.json"


def now() -> datetime:
    return datetime.now(TZ)


def now_iso() -> str:
    return now().isoformat(timespec="seconds")


def now_human() -> str:
    stamp = now()
    try:
        text = stamp.strftime("%Y-%m-%d %-I:%M %p")
    except ValueError:
        text = stamp.strftime("%Y-%m-%d %I:%M %p").lstrip("0").replace(" 0", " ")
    return f"{text} ({TZ_LABEL})"


def is_private_path(path: Path, house: Path | None = None) -> bool:
    """True if path is under the house's private/ directory."""
    root = (house or house_root()).resolve()
    try:
        rel = path.resolve().relative_to(root)
    except (ValueError, OSError):
        # Also refuse a literal ".../private/..." anywhere under that name
        # when we cannot resolve against the house.
        return PRIVATE_DIR_NAME in path.parts
    return rel.parts[:1] == (PRIVATE_DIR_NAME,)
