#!/usr/bin/env python3
"""Emergency coma and a local flare notice.

A deeper freeze than the morphine pen. Ordinary writes, helpers, Moot
chatter, drills, consultants, and cloud sync are frozen via a local
flag. The chart, the flare notice, and the wake path stay up.

This module queues one local flare notice per activation. A flare
email is opt-in and off by default (see flare_email.py and
flare-email.conf). When enabled, one outbox message is queued after
the local notice; this process does not open a mailbox. A flare
reply, inbound mail, or a consultant comment cannot wake the house.
Wake needs the owner's explicit OK on the wake command
(medic.py coma --off --i-have-owner-ok, or wake.py).
"""

from __future__ import annotations

import fcntl
from pathlib import Path
from typing import Any

import chart
import flare_email
import guard
import paths
import privacy
import tags

FORBIDDEN_WAKE_ACTORS = frozenset(
    {
        "email",
        "flare",
        "flare-reply",
        "inbound-email",
        "auto-reply",
        "flare-email",
        "flare-email-reply",
        "consultant",
    }
)

COMA_ON_TAG_REASON = (
    "Emergency coma is on. Ordinary writes are frozen. "
    "A local flare notice was queued. No email was sent."
)
COMA_OFF_TAG_REASON = (
    "Emergency coma is off. House writes are allowed again "
    "(any still-active morphine pen or tourniquets continue to apply)."
)


class ComaError(chart.ChartError):
    """User-facing coma / wake error."""


def _lock_path() -> Path:
    return guard.state_path().with_suffix(".json.lock")


def _with_lock():
    path = _lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    return open(path, "a", encoding="utf-8")


def _dump_state(state: dict[str, Any]) -> None:
    import json

    target = guard.state_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(target)


def _flare_text(*, reason: str, when: str, email_queued: bool = False) -> str:
    if email_queued:
        mail_line = (
            "One flare email is queued for your human. A later turn sends "
            "that one message. A reply to that email cannot wake the house."
        )
    else:
        mail_line = "This is a local notice only. No email was sent."
    return (
        "EMERGENCY COMA is ON\n"
        f"Time: {when}\n"
        f"Reason: {reason}\n"
        "\n"
        "The house is in a deeper freeze. Ordinary writes, helpers, "
        "Moot chatter, drills, consultants, and cloud sync are frozen "
        "via a local flag. Only this notice, the chart, and the wake "
        "path stay up.\n"
        "\n"
        "Nothing else will happen until you wake me.\n"
        "\n"
        f"{mail_line}\n"
        "Wake with: medic.py coma --off --i-have-owner-ok\n"
        "Or, if that helper is dark: wake.py --i-have-owner-ok\n"
    )


def format_status(state: dict[str, Any] | None = None) -> str:
    data = state or guard.load_state()
    coma = data.get("coma") or {}
    if coma.get("on"):
        lines = [
            f"Emergency coma: ON since {coma.get('set_at') or 'unknown'} "
            f"by {coma.get('set_by') or 'unknown'}."
        ]
        if coma.get("reason"):
            lines.append(f"  Reason: {coma['reason']}")
        if coma.get("flare_queued"):
            if coma.get("flare_email_queued"):
                mail = (
                    f"  Flare queued at {guard.flare_path()} "
                    "(local file and print)."
                )
                lines.append(mail)
                lines.append(
                    f"  Flare email queued at {guard.flare_email_outbox_path()} "
                    "(one message; a later turn sends it; a reply cannot wake the house)."
                )
            else:
                lines.append(
                    f"  Flare queued at {guard.flare_path()} "
                    "(local file and print only; no email)."
                )
        lines.append(
            "Wake with: medic.py coma --off --i-have-owner-ok "
            "(or wake.py --i-have-owner-ok)."
        )
        return "\n".join(lines)
    return "Emergency coma: off."


def enter_coma(
    *,
    reason: str,
    actor: str = "medic.py",
    last_resort: bool = False,
) -> dict[str, Any]:
    """Turn emergency coma on. Queues at most one local flare per activation."""
    reason = privacy.assert_safe_text((reason or "").strip(), label="reason")
    if not reason:
        raise ComaError("Entering a coma needs a one-line reason.")
    if len(reason) > 240:
        raise ComaError("The reason is longer than 240 characters. Keep it short.")
    actor = (actor or "medic.py").strip() or "medic.py"

    with _with_lock() as lockf:
        fcntl.flock(lockf.fileno(), fcntl.LOCK_EX)
        try:
            state = guard.load_state()
            if state["coma"].get("on"):
                return {
                    "changed": False,
                    "state": state,
                    "flare_path": guard.flare_path()
                    if state["coma"].get("flare_queued")
                    else None,
                    "message": (
                        "Emergency coma is already on. No second flare was queued.\n"
                        + format_status(state)
                    ),
                }
            stamp = paths.now_iso()
            human = paths.now_human()
            flare = guard.flare_path()
            flare.parent.mkdir(parents=True, exist_ok=True)
            email_record = flare_email.queue_flare_email(
                reason=reason,
                when=human,
                event_id=stamp,
            )
            email_queued = bool(email_record) and email_record.get("status") == "queued"
            flare.write_text(
                _flare_text(reason=reason, when=human, email_queued=email_queued),
                encoding="utf-8",
            )
            state["coma"] = {
                "on": True,
                "set_at": stamp,
                "set_by": actor,
                "reason": reason,
                "flare_queued": True,
                "flare_email_queued": email_queued,
                "last_resort": bool(last_resort),
            }
            _dump_state(state)
        finally:
            fcntl.flock(lockf.fileno(), fcntl.LOCK_UN)

    chart.append(
        {
            "kind": "coma",
            "actor": actor,
            "trigger": "coma --on" + (" (last resort)" if last_resort else ""),
            "note": reason,
            "part": "medical",
            "tag": "red",
            "ended": (
                "coma on; one local flare queued; one flare email queued; routines were not paused"
                if state["coma"].get("flare_email_queued")
                else "coma on; one local flare queued; no email sent; routines were not paused"
            ),
            "touched": "medical/ flags, chart, and tags only",
            "not_touched": (
                "the owner's off-limits files, mail, restores; "
                "server-side routines were not paused"
            ),
        }
    )
    tags.set_tag(
        "medical",
        "red",
        reason=(
            "Emergency coma is on. Ordinary writes are frozen. "
            "A local flare notice was queued. One flare email is queued for the owner."
            if state["coma"].get("flare_email_queued")
            else COMA_ON_TAG_REASON
        ),
        source="coma",
        actor=actor,
        owner_ok=False,
    )
    return {
        "changed": True,
        "state": state,
        "flare_path": flare,
        "message": format_status(state) + "\n\n" + flare.read_text(encoding="utf-8"),
    }


def _actor_is_forbidden(actor: str) -> bool:
    key = (actor or "").strip().lower().replace("_", "-").replace(" ", "-")
    if key in FORBIDDEN_WAKE_ACTORS:
        return True
    return any(part and part in FORBIDDEN_WAKE_ACTORS for part in key.split("-"))


def wake_coma(*, actor: str = "medic.py", owner_ok: bool = False) -> dict[str, Any]:
    """Turn emergency coma off. Requires the human's explicit OK."""
    actor = (actor or "medic.py").strip() or "medic.py"
    if not owner_ok:
        raise ComaError(
            "Waking from a coma needs the owner's OK in this chat, "
            "then --i-have-owner-ok. A flare reply or inbound email cannot wake the house."
        )
    if _actor_is_forbidden(actor):
        raise ComaError(
            "A flare reply, inbound email, or consultant comment cannot wake the house. "
            "The owner has to confirm in this chat."
        )

    with _with_lock() as lockf:
        fcntl.flock(lockf.fileno(), fcntl.LOCK_EX)
        try:
            state = guard.load_state()
            if not state["coma"].get("on"):
                return {
                    "changed": False,
                    "state": state,
                    "message": "Emergency coma is already off.\n" + format_status(state),
                }
            prior = state["coma"].get("reason") or "no reason recorded"
            state["coma"] = {
                "on": False,
                "set_at": paths.now_iso(),
                "set_by": actor,
                "reason": None,
                "flare_queued": False,
                "flare_email_queued": False,
                "last_resort": False,
            }
            _dump_state(state)
            flare = guard.flare_path()
            if flare.is_file():
                body = flare.read_text(encoding="utf-8")
                flare.write_text(
                    f"CLEARED {paths.now_human()} by {actor}. "
                    "Emergency coma is off. If a morphine pen is still on, "
                    "clear it separately with medic.py pen --off. "
                    "If routines were paused in the main chat, they can be "
                    "started again when the owner says so.\n\n"
                    + body,
                    encoding="utf-8",
                )
        finally:
            fcntl.flock(lockf.fileno(), fcntl.LOCK_UN)

    chart.append(
        {
            "kind": "coma",
            "actor": actor,
            "trigger": "coma --off",
            "note": f"Coma cleared (was: {prior}).",
            "part": "medical",
            "tag": "green",
            "ended": "coma off; pen and tourniquets unchanged; no email sent",
            "touched": "medical/ flags, chart, and tags only",
            "not_touched": "the owner's off-limits files, mail, restores",
        }
    )
    tags.set_tag(
        "medical",
        "green",
        reason=COMA_OFF_TAG_REASON,
        source="coma",
        actor=actor,
        owner_ok=False,
    )
    return {
        "changed": True,
        "state": state,
        "message": format_status(state),
    }
