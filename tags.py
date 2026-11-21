#!/usr/bin/env python3
"""Green / yellow / red / black triage tags.

Tags are visibility, not a freeze. Setting a tag writes a line in the
chart. Red and black stay visible in the chart even after they clear.
Black on a critical part needs the owner's OK. This module never stops a
routine, sends mail, or restores a backup.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import chart
import paths
import privacy

COLORS = ("green", "yellow", "red", "black")

PARTS = (
    "defense",
    "range",
    "consultant",
    "pet",
    "routines",
    "pride",
    "backups",
    "drive",
    "failsafe",
    "medical",
)

# Auto-black is refused on these. The owner can still set black with --i-have-owner-ok.
CRITICAL_PARTS = frozenset({"defense", "failsafe", "backups", "medical"})

COLOR_MEANING = {
    "green": "working as expected",
    "yellow": "off, but stable",
    "red": "failing, needs a decision",
    "black": "trusted enough to freeze or cut away (tag only; pen and tourniquet are separate commands)",
}


class TagError(chart.ChartError):
    """User-facing tag error."""


def empty_board() -> dict[str, Any]:
    return {
        "timezone": paths.TZ_LABEL,
        "updated": None,
        "source": "derived board; the chart is the official history",
        "parts": {
            name: {
                "tag": None,
                "reason": None,
                "source": None,
                "set_at": None,
                "set_by": None,
            }
            for name in PARTS
        },
    }


def load_board(path: Path | None = None) -> dict[str, Any]:
    target = path or paths.tags_path()
    if not target.is_file():
        return empty_board()
    data = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TagError(f"Tags file is not an object: {target}")
    board = empty_board()
    board["updated"] = data.get("updated")
    incoming = data.get("parts") or {}
    for name in PARTS:
        if name in incoming and isinstance(incoming[name], dict):
            board["parts"][name].update(
                {k: incoming[name].get(k) for k in board["parts"][name]}
            )
    return board


def save_board(board: dict[str, Any], path: Path | None = None) -> Path:
    target = path or paths.tags_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(board, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(target)
    return target


def set_tag(
    part: str,
    color: str,
    *,
    reason: str,
    source: str = "manual",
    actor: str = "medic.py",
    owner_ok: bool = False,
    log_refusal: bool = True,
) -> dict[str, Any]:
    """Set a tag and write a chart note. Returns the new part record."""
    part = (part or "").strip().lower()
    color = (color or "").strip().lower()
    if part not in PARTS:
        raise TagError(f"Unknown part {part!r}. Known: {', '.join(PARTS)}.")
    if color not in COLORS:
        raise TagError(f"Tag must be one of: {', '.join(COLORS)}.")
    reason = privacy.assert_safe_text((reason or "").strip(), label="reason")
    if not reason:
        raise TagError("A tag needs a one-line reason.")
    if "\n" in reason or "\r" in reason:
        raise TagError("The reason has to be one line.")
    if len(reason) > 240:
        raise TagError("The reason is longer than 240 characters. Keep it short.")

    if color == "black" and part in CRITICAL_PARTS and not owner_ok:
        if log_refusal:
            chart.append(
                {
                    "kind": "refused",
                    "actor": actor,
                    "trigger": f"refused automatic black on {part}",
                    "note": (
                        f"Black on critical part {part} needs the owner's OK. "
                        "No freeze, no mail, no restore. Tag not changed."
                    ),
                    "part": part,
                    "tag": color,
                    "ended": "refused",
                }
            )
        raise TagError(
            f"Black on critical part {part} needs the owner's OK "
            "(pass --i-have-owner-ok). No freeze was applied."
        )

    board = load_board()
    previous = board["parts"][part].get("tag")
    unchanged = previous == color and board["parts"][part].get("reason") == reason
    record = {
        "tag": color,
        "reason": reason,
        "source": source,
        "set_at": paths.now_iso(),
        "set_by": actor,
    }
    board["parts"][part] = record
    board["updated"] = record["set_at"]
    save_board(board)

    if not unchanged:
        kind = "tag"
        ended = "logged"
        if previous and previous != color:
            kind = "tag-clear" if color == "green" and previous in {"red", "black"} else "tag-change"
            ended = f"was {previous}, now {color}; history kept in this chart"
        chart.append(
            {
                "kind": kind,
                "actor": actor,
                "trigger": f"tag {part} {color}",
                "note": reason,
                "part": part,
                "tag": color,
                "ended": ended,
            }
        )
    return record


def format_board(board: dict[str, Any] | None = None) -> str:
    data = board or load_board()
    updated = data.get("updated") or "never"
    lines = [
        f"Triage tags as of {paths.now_human()}. Board updated: {updated}.",
        "Tags are visibility. The pen, tourniquet, and coma are separate commands. No mail, no restore.",
        "",
        f"{'Part':<10} {'Tag':<8} Reason",
    ]
    for name in PARTS:
        item = data["parts"][name]
        tag = item.get("tag") or "—"
        reason = item.get("reason") or "(not tagged yet)"
        lines.append(f"{name:<10} {tag:<8} {reason}")
    return "\n".join(lines)
