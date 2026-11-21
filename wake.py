#!/usr/bin/env python3
"""Small standalone wake for emergency coma.

This script is intentionally tiny and uses only the Python standard
library to clear the local coma flag, so it can still run if other
helpers are dark. It never sends email. It requires --i-have-owner-ok.
A flare reply, flare email reply, or inbound email cannot wake the house.

If the chart tools are importable, a chart note is appended. If they
are not, the flag is still cleared and a line is printed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Chicago")
FORBIDDEN_ACTORS = frozenset(
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


def _data_root() -> Path:
    raw = os.environ.get("MEDICAL_DATA", "").strip()
    if raw:
        return Path(raw).resolve()
    return Path(__file__).resolve().parent


def _state_path() -> Path:
    return _data_root() / "flags" / "state.json"


def _lock_path() -> Path:
    return _state_path().with_suffix(".json.lock")


def _now_iso() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


def _now_human() -> str:
    stamp = datetime.now(TZ)
    try:
        text = stamp.strftime("%Y-%m-%d %-I:%M %p")
    except ValueError:
        text = stamp.strftime("%Y-%m-%d %I:%M %p").lstrip("0").replace(" 0", " ")
    return f"{text} (America/Chicago)"


def _actor_is_forbidden(actor: str) -> bool:
    key = (actor or "").strip().lower().replace("_", "-").replace(" ", "-")
    if key in FORBIDDEN_ACTORS:
        return True
    return any(part and part in FORBIDDEN_ACTORS for part in key.split("-"))


def _load_state() -> dict[str, Any]:
    path = _state_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _dump_state(state: dict[str, Any]) -> None:
    target = _state_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(target)


def wake(*, actor: str, owner_ok: bool) -> str:
    import fcntl

    if not owner_ok:
        raise SystemExit(
            "Waking from a coma needs the owner's OK in this chat, "
            "then --i-have-owner-ok. A flare reply or inbound email cannot wake the house."
        )
    if _actor_is_forbidden(actor):
        raise SystemExit(
            "A flare reply, inbound email, or consultant comment cannot wake the house."
        )

    with open(_lock_path(), "a", encoding="utf-8") as lockf:
        fcntl.flock(lockf.fileno(), fcntl.LOCK_EX)
        try:
            state = _load_state()
            coma = state.get("coma") if isinstance(state.get("coma"), dict) else {}
            if not coma.get("on"):
                return "Emergency coma is already off."
            prior = coma.get("reason") or "no reason recorded"
            state["coma"] = {
                "on": False,
                "set_at": _now_iso(),
                "set_by": actor,
                "reason": None,
                "flare_queued": False,
                "flare_email_queued": False,
                "last_resort": False,
            }
            _dump_state(state)
            flare = _data_root() / "flags" / "flare-notice.txt"
            if flare.is_file():
                body = flare.read_text(encoding="utf-8")
                flare.write_text(
                    f"CLEARED {_now_human()} by {actor}. "
                    "Emergency coma is off.\n\n" + body,
                    encoding="utf-8",
                )
        finally:
            fcntl.flock(lockf.fileno(), fcntl.LOCK_UN)

    # Best-effort chart note. The flag is already clear if this fails.
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import chart
        import tags

        chart.append(
            {
                "kind": "coma",
                "actor": actor,
                "trigger": "wake.py",
                "note": f"Coma cleared via wake.py (was: {prior}).",
                "part": "medical",
                "tag": "green",
                "ended": "coma off; no email sent",
                "touched": "medical/ flags, chart, and tags only",
                "not_touched": "the owner's off-limits files, mail, restores",
            }
        )
        tags.set_tag(
            "medical",
            "green",
            reason="Emergency coma is off (woken with wake.py).",
            source="coma",
            actor=actor,
            owner_ok=False,
        )
    except Exception as exc:  # noqa: BLE001 — wake must succeed even if the chart is dark
        return (
            "Emergency coma is off. A chart note could not be written "
            f"({exc.__class__.__name__})."
        )
    return "Emergency coma is off."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="wake.py",
        description=(
            "Standalone wake for emergency coma. Clears the local flag only. "
            "Never sends email."
        ),
    )
    parser.add_argument(
        "--i-have-owner-ok",
        action="store_true",
        help="Required. The owner confirmed the wake in this chat.",
    )
    parser.add_argument("--actor", default="wake.py")
    args = parser.parse_args(argv)
    try:
        message = wake(actor=args.actor, owner_ok=bool(args.i_have_owner_ok))
    except SystemExit as exc:
        if isinstance(exc.code, str):
            sys.stderr.write(exc.code.rstrip() + "\n")
            return 2
        raise
    sys.stdout.write(message.rstrip() + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
