#!/usr/bin/env python3
"""Opt-in flare email outbox for emergency coma (default off).

A local flare notice is always written. Email is off unless the human
opts in and sets their address in flare-email.conf (or a data-root
override of that file). When enabled, this module queues one outbox
file after the local notice. The coma process does not open a mailbox;
a later turn or routine sends that one message.

One email per coma event (deduped). The recipient is locked to the
configured human address; never anyone else. A flare email reply
cannot wake the house; wake still requires --i-have-owner-ok in chat.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import guard

TZ = ZoneInfo("America/Chicago")
SUBJECT = "House Medical flare: emergency coma"
PLACEHOLDER_ADDRESSES = frozenset(
    {
        "",
        "<your human's address>",
        "your human's address",
        "you@example.com",
    }
)
ON_VALUES = frozenset({"on", "true", "yes", "1"})
OFF_VALUES = frozenset({"off", "false", "no", "0", ""})
Transport = Callable[[str, str, str], Any]


class FlareEmailError(Exception):
    """User-facing flare-email error."""


def _now_iso() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


def _now_human() -> str:
    stamp = datetime.now(TZ)
    try:
        text = stamp.strftime("%Y-%m-%d %-I:%M %p")
    except ValueError:
        text = stamp.strftime("%Y-%m-%d %I:%M %p").lstrip("0").replace(" 0", " ")
    return f"{text} (America/Chicago)"


def default_config_path() -> Path:
    return Path(__file__).resolve().parent / "flare-email.conf"


def config_path() -> Path:
    override = guard.data_root() / "flare-email.conf"
    if override.is_file():
        return override
    return default_config_path()


def _looks_like_email(value: str) -> bool:
    return bool(re.fullmatch(r"[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+", value))


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Read flare_email / flare_email_to. Missing or unreadable means off."""
    cfg = {"flare_email": False, "flare_email_to": ""}
    target = path or config_path()
    if not target.is_file():
        return cfg
    try:
        raw = target.read_text(encoding="utf-8")
    except OSError:
        return cfg
    parsed: dict[str, str] = {}
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        parsed[key.strip().lower()] = value.strip()
    flag = parsed.get("flare_email", "off").lower()
    if flag in ON_VALUES:
        cfg["flare_email"] = True
    elif flag in OFF_VALUES:
        cfg["flare_email"] = False
    else:
        cfg["flare_email"] = False
    cfg["flare_email_to"] = parsed.get("flare_email_to", "").strip()
    return cfg


def enabled(config: dict[str, Any] | None = None) -> bool:
    cfg = config if config is not None else load_config()
    if not cfg.get("flare_email"):
        return False
    address = _normalize_address(str(cfg.get("flare_email_to") or ""))
    if address in PLACEHOLDER_ADDRESSES or not _looks_like_email(address):
        return False
    return True


def configured_recipient(config: dict[str, Any] | None = None) -> str:
    cfg = config if config is not None else load_config()
    return _normalize_address(str(cfg.get("flare_email_to") or ""))


def outbox_path():
    return guard.flare_email_outbox_path()


def _normalize_address(value: str) -> str:
    return (value or "").strip().lower()


def email_body(*, reason: str, when: str) -> str:
    return (
        f"Time: {when}\n"
        f"Reason: {reason}\n"
        "\n"
        "Nothing else happens until you wake me.\n"
    )


def load_outbox() -> dict[str, Any] | None:
    path = outbox_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _dump_outbox(record: dict[str, Any]) -> None:
    target = outbox_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(target)


def _recipient_ok(record: dict[str, Any], allowed: str) -> bool:
    if not allowed or allowed in PLACEHOLDER_ADDRESSES or not _looks_like_email(allowed):
        return False
    if _normalize_address(str(record.get("to") or "")) != allowed:
        return False
    if record.get("cc") or record.get("bcc") or record.get("recipients"):
        return False
    return True


def queue_flare_email(
    *,
    reason: str,
    when: str,
    event_id: str,
    to: str | None = None,
) -> dict[str, Any] | None:
    """Queue one outbox record when opted in. Default off returns None."""
    cfg = load_config()
    if not enabled(cfg):
        return None
    allowed = configured_recipient(cfg)
    reason = (reason or "").strip()
    when = (when or "").strip() or _now_human()
    event_id = (event_id or "").strip()
    if not event_id:
        raise FlareEmailError("A flare email needs the coma event id.")
    if to is not None and _normalize_address(to) != allowed:
        raise FlareEmailError("Flare email recipient is locked to the configured human address.")

    existing = load_outbox()
    if (
        existing
        and existing.get("event_id") == event_id
        and existing.get("status") in {"queued", "sent"}
        and _recipient_ok(existing, allowed)
    ):
        return existing

    record = {
        "event_id": event_id,
        "to": allowed,
        "subject": SUBJECT,
        "body": email_body(reason=reason, when=when),
        "queued_at": _now_iso(),
        "status": "queued",
        "sent_at": None,
    }
    _dump_outbox(record)
    return record


def send_queued(*, transport: Transport | None = None) -> dict[str, Any]:
    """Send the queued flare email once, only to the configured human."""
    cfg = load_config()
    if not enabled(cfg):
        return {"sent": False, "reason": "disabled"}
    allowed = configured_recipient(cfg)
    record = load_outbox()
    if not record:
        return {"sent": False, "reason": "no outbox"}
    if not _recipient_ok(record, allowed):
        record["status"] = "blocked"
        record["blocked_reason"] = "recipient locked to the configured human address"
        _dump_outbox(record)
        return {"sent": False, "reason": "recipient locked", "to": record.get("to")}
    if record.get("status") == "sent":
        return {
            "sent": False,
            "reason": "already sent",
            "event_id": record.get("event_id"),
            "to": allowed,
        }
    if transport is None:
        return {
            "sent": False,
            "reason": "no transport",
            "event_id": record.get("event_id"),
            "to": allowed,
            "subject": record.get("subject"),
            "body": record.get("body"),
        }
    transport(allowed, str(record.get("subject") or SUBJECT), str(record.get("body") or ""))
    record["status"] = "sent"
    record["sent_at"] = _now_iso()
    record["to"] = allowed
    _dump_outbox(record)
    return {
        "sent": True,
        "event_id": record.get("event_id"),
        "to": allowed,
        "subject": record.get("subject"),
        "body": record.get("body"),
    }


def format_outbox(record: dict[str, Any] | None = None) -> str:
    data = record if record is not None else load_outbox()
    if not enabled():
        return "Flare email is off (default). A local flare notice is still written."
    if not data:
        return "No flare email is queued."
    lines = [
        f"Status: {data.get('status') or 'unknown'}",
        f"To: {data.get('to')}",
        f"Subject: {data.get('subject')}",
        f"Event: {data.get('event_id')}",
    ]
    if data.get("queued_at"):
        lines.append(f"Queued at: {data['queued_at']}")
    if data.get("sent_at"):
        lines.append(f"Sent at: {data['sent_at']}")
    lines.append("")
    lines.append(str(data.get("body") or "").rstrip())
    lines.append("")
    lines.append(
        "A later turn or routine should send this one message to the "
        "configured human only, then leave a sent mark on the outbox."
    )
    lines.append("A flare email reply cannot wake the house.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="flare_email.py",
        description=(
            "Opt-in flare-email outbox (default off). This process does "
            "not open a mailbox."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("show", help="Print the queued message, if any.")
    sub.add_parser("status", help="Same as show.")
    args = parser.parse_args(argv)
    if args.command in {"show", "status"}:
        sys.stdout.write(format_outbox().rstrip() + "\n")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
