#!/usr/bin/env python3
"""Morphine pen (safe mode) and tourniquet: write the local flags.

This module writes a flag file under the medical data root, appends a
chart note, sets a tag, and — for the pen only — queues one local alert
file plus a printed message. It never sends email, never pauses a
server-side routine, and never walks into private/.
"""

from __future__ import annotations

import fcntl
import json
from pathlib import Path
from typing import Any

import chart
import guard
import paths
import privacy
import tags

# Never isolatable: the medic, the chart, and the wake path must stay up.
NEVER_CUFF = frozenset({"medical"})
# Not auto-tourniqueted. The owner can still isolate one with --i-have-owner-ok.
CRITICAL_CUFF = tags.CRITICAL_PARTS

PEN_ON_TAG_REASON = (
    "Morphine pen (safe mode) is on. Ordinary writes are frozen. "
    "Server-side routines were not paused."
)
PEN_OFF_TAG_REASON = (
    "Morphine pen is off. House writes are allowed again "
    "(any still-active tourniquets continue to apply)."
)


class SafeModeError(chart.ChartError):
    """User-facing pen / tourniquet error."""


def _lock_path() -> Path:
    return guard.state_path().with_suffix(".json.lock")


def _dump_state(state: dict[str, Any]) -> None:
    target = guard.state_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(target)


def _with_lock():
    path = _lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    return open(path, "a", encoding="utf-8")


def format_status(state: dict[str, Any] | None = None) -> str:
    data = state or guard.load_state()
    pen = data["pen"]
    lines = []
    if pen.get("on"):
        lines.append(
            f"Morphine pen: ON since {pen.get('set_at') or 'unknown'} "
            f"by {pen.get('set_by') or 'unknown'}."
        )
        if pen.get("reason"):
            lines.append(f"  Reason: {pen['reason']}")
        if pen.get("alert_queued"):
            lines.append(
                f"  Alert queued at {guard.alert_path()} "
                "(local file and print only; no email, no routine pause)."
            )
    else:
        lines.append("Morphine pen: off. Ordinary writes are allowed.")
    cuffs = data["tourniquets"]
    if cuffs:
        lines.append("Tourniquets:")
        for name in sorted(cuffs):
            rec = cuffs[name]
            lines.append(
                f"  {name}: ON since {rec.get('set_at') or 'unknown'} "
                f"({rec.get('reason') or 'no reason recorded'})"
            )
    else:
        lines.append("Tourniquets: none.")
    lines.append(
        "No mail, no restore. Server-side routines are only paused in the main chat."
    )
    return "\n".join(lines)


def _alert_text(*, reason: str, when: str) -> str:
    return (
        "MORPHINE PEN (safe mode) is ON\n"
        f"Time: {when}\n"
        f"Reason: {reason}\n"
        "\n"
        "Ordinary writes and helper runs on this computer are frozen via a "
        "local flag (the pet, the consultant, the range, and pride honor it).\n"
        "\n"
        "Server-side routines were NOT paused. They can only be paused in "
        "the assistant's main chat. Please pause any still-running helpers "
        "(Nightly Backup, Studio Hours, Weekly Self-Check, and any other "
        "live routine) until the pen is turned off.\n"
        "\n"
        "This is the only queued alert for this event. No email was sent.\n"
        "Clear with: medic.py pen --off\n"
    )


def apply_pen(*, reason: str, actor: str = "medic.py") -> dict[str, Any]:
    """Turn the morphine pen on. Queues at most one alert per activation."""
    reason = privacy.assert_safe_text((reason or "").strip(), label="reason")
    if not reason:
        raise SafeModeError("Firing the morphine pen needs a one-line reason.")
    if len(reason) > 240:
        raise SafeModeError("The reason is longer than 240 characters. Keep it short.")
    actor = (actor or "medic.py").strip() or "medic.py"

    with _with_lock() as lockf:
        fcntl.flock(lockf.fileno(), fcntl.LOCK_EX)
        try:
            state = guard.load_state()
            if state["pen"].get("on"):
                return {
                    "changed": False,
                    "state": state,
                    "alert_path": guard.alert_path() if state["pen"].get("alert_queued") else None,
                    "message": (
                        "Morphine pen is already on. No second alert was queued.\n"
                        + format_status(state)
                    ),
                }
            stamp = paths.now_iso()
            human = paths.now_human()
            alert = guard.alert_path()
            alert.parent.mkdir(parents=True, exist_ok=True)
            alert.write_text(_alert_text(reason=reason, when=human), encoding="utf-8")
            state["pen"] = {
                "on": True,
                "set_at": stamp,
                "set_by": actor,
                "reason": reason,
                "alert_queued": True,
            }
            _dump_state(state)
        finally:
            fcntl.flock(lockf.fileno(), fcntl.LOCK_UN)

    chart.append(
        {
            "kind": "pen",
            "actor": actor,
            "trigger": "morphine pen --on",
            "note": reason,
            "part": "medical",
            "tag": "yellow",
            "ended": "safe mode on; one local alert queued; routines were not paused; no email sent",
            "touched": "medical/ flags, chart, and tags only",
            "not_touched": (
                "The owner's off-limits files, mail, coma, restores; "
                "server-side routines were not paused"
            ),
        }
    )
    tags.set_tag(
        "medical",
        "yellow",
        reason=PEN_ON_TAG_REASON,
        source="pen",
        actor=actor,
        owner_ok=False,
    )
    return {
        "changed": True,
        "state": state,
        "alert_path": alert,
        "message": format_status(state) + "\n\n" + alert.read_text(encoding="utf-8"),
    }


def release_pen(*, actor: str = "medic.py") -> dict[str, Any]:
    """Turn the morphine pen off. Tourniquets, if any, stay on."""
    actor = (actor or "medic.py").strip() or "medic.py"
    with _with_lock() as lockf:
        fcntl.flock(lockf.fileno(), fcntl.LOCK_EX)
        try:
            state = guard.load_state()
            if not state["pen"].get("on"):
                return {
                    "changed": False,
                    "state": state,
                    "message": "Morphine pen is already off.\n" + format_status(state),
                }
            prior = state["pen"].get("reason") or "no reason recorded"
            state["pen"] = {
                "on": False,
                "set_at": paths.now_iso(),
                "set_by": actor,
                "reason": None,
                "alert_queued": False,
            }
            _dump_state(state)
            alert = guard.alert_path()
            if alert.is_file():
                body = alert.read_text(encoding="utf-8")
                alert.write_text(
                    f"CLEARED {paths.now_human()} by {actor}. "
                    "Safe mode is off. If routines were paused in the main chat, "
                    "they can be started again when the owner says so.\n\n"
                    + body,
                    encoding="utf-8",
                )
        finally:
            fcntl.flock(lockf.fileno(), fcntl.LOCK_UN)

    chart.append(
        {
            "kind": "pen",
            "actor": actor,
            "trigger": "morphine pen --off",
            "note": f"Safe mode cleared (was: {prior}).",
            "part": "medical",
            "tag": "green",
            "ended": "safe mode off; tourniquets unchanged; no email sent",
            "touched": "medical/ flags, chart, and tags only",
            "not_touched": (
                "The owner's off-limits files, mail, coma, restores; "
                "server-side routines were not started"
            ),
        }
    )
    tags.set_tag(
        "medical",
        "green",
        reason=PEN_OFF_TAG_REASON,
        source="pen",
        actor=actor,
        owner_ok=False,
    )
    return {
        "changed": True,
        "state": state,
        "message": format_status(state),
    }


def apply_tourniquet(
    part: str,
    *,
    reason: str,
    actor: str = "medic.py",
    owner_ok: bool = False,
) -> dict[str, Any]:
    name = (part or "").strip().lower()
    if name not in tags.PARTS:
        raise SafeModeError(f"Unknown part {part!r}. Known: {', '.join(tags.PARTS)}.")
    if name in NEVER_CUFF:
        raise SafeModeError(
            "The medical kit, the chart, and the wake path cannot be tourniqueted."
        )
    if name in CRITICAL_CUFF and not owner_ok:
        raise SafeModeError(
            f"{name} is a critical part and is not auto-tourniqueted. "
            "Pass --i-have-owner-ok if the owner confirmed it."
        )
    reason = privacy.assert_safe_text((reason or "").strip(), label="reason")
    if not reason:
        raise SafeModeError("A tourniquet needs a one-line reason.")
    if len(reason) > 240:
        raise SafeModeError("The reason is longer than 240 characters. Keep it short.")
    actor = (actor or "medic.py").strip() or "medic.py"

    with _with_lock() as lockf:
        fcntl.flock(lockf.fileno(), fcntl.LOCK_EX)
        try:
            state = guard.load_state()
            current = state["tourniquets"].get(name)
            if current and current.get("on"):
                return {
                    "changed": False,
                    "state": state,
                    "message": (
                        f"Tourniquet is already on for {name}.\n" + format_status(state)
                    ),
                }
            state["tourniquets"][name] = {
                "on": True,
                "set_at": paths.now_iso(),
                "set_by": actor,
                "reason": reason,
            }
            _dump_state(state)
        finally:
            fcntl.flock(lockf.fileno(), fcntl.LOCK_UN)

    chart.append(
        {
            "kind": "tourniquet",
            "actor": actor,
            "trigger": f"tourniquet --on {name}",
            "note": reason,
            "part": name,
            "tag": "yellow",
            "ended": "part isolated; rest of the house stays live; no email sent",
            "touched": "medical/ flags, chart, and tags only",
            "not_touched": "The owner's off-limits files, mail, coma, restores, other parts",
        }
    )
    tags.set_tag(
        name,
        "yellow",
        reason=f"Tourniquet is on: {reason}",
        source="tourniquet",
        actor=actor,
        owner_ok=False,
    )
    return {
        "changed": True,
        "state": state,
        "message": format_status(state),
    }


def release_tourniquet(part: str, *, actor: str = "medic.py") -> dict[str, Any]:
    name = (part or "").strip().lower()
    if name not in tags.PARTS:
        raise SafeModeError(f"Unknown part {part!r}. Known: {', '.join(tags.PARTS)}.")
    actor = (actor or "medic.py").strip() or "medic.py"

    with _with_lock() as lockf:
        fcntl.flock(lockf.fileno(), fcntl.LOCK_EX)
        try:
            state = guard.load_state()
            if name not in state["tourniquets"]:
                return {
                    "changed": False,
                    "state": state,
                    "message": (
                        f"No tourniquet is on for {name}.\n" + format_status(state)
                    ),
                }
            prior = state["tourniquets"][name].get("reason") or "no reason recorded"
            del state["tourniquets"][name]
            _dump_state(state)
        finally:
            fcntl.flock(lockf.fileno(), fcntl.LOCK_UN)

    chart.append(
        {
            "kind": "tourniquet",
            "actor": actor,
            "trigger": f"tourniquet --off {name}",
            "note": f"Tourniquet released for {name} (was: {prior}).",
            "part": name,
            "tag": "yellow",
            "ended": "released; not automatically declared healthy",
            "touched": "medical/ flags, chart, and tags only",
            "not_touched": "The owner's off-limits files, mail, coma, restores",
        }
    )
    tags.set_tag(
        name,
        "yellow",
        reason=f"Tourniquet released for {name}; awaiting a check or a green tag.",
        source="tourniquet",
        actor=actor,
        owner_ok=False,
    )
    return {
        "changed": True,
        "state": state,
        "message": format_status(state),
    }
