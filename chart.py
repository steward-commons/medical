#!/usr/bin/env python3
"""Append-only, hash-chained incident medical record.

If it is not written down, it did not happen. This module only appends
or reads. There is no rewrite, edit, delete, or truncate API. Each
record carries the SHA-256 of the previous raw line so a mid-file edit
can be spotted.

Files live under this folder (or MEDICAL_DATA in tests). Nothing
here sends mail, freezes the house, stops a routine, or restores a backup.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Mapping

import paths
import privacy

GENESIS_HASH = "genesis"
NOTE_MAX = 240
TRIGGER_MAX = 160


class ChartError(Exception):
    """User-facing chart error."""


class ChartTampered(ChartError):
    """The append-only chain does not verify."""


def line_hash(raw_line: str) -> str:
    return hashlib.sha256(raw_line.encode("utf-8")).hexdigest()


def _read_raw_lines(path: Path) -> list[str]:
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    if not text:
        return []
    return text.splitlines()


def read_events(log_file: Path | None = None) -> list[dict[str, Any]]:
    path = log_file or paths.chart_path()
    events: list[dict[str, Any]] = []
    for raw in _read_raw_lines(path):
        if not raw.strip():
            continue
        try:
            record = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ChartError(f"Chart has a bad JSON line in {path}: {exc}") from exc
        if not isinstance(record, dict):
            raise ChartError(f"Chart line is not an object: {path}")
        events.append(record)
    return events


def verify_chain(log_file: Path | None = None) -> None:
    path = log_file or paths.chart_path()
    prev = GENESIS_HASH
    for index, raw in enumerate(_read_raw_lines(path), start=1):
        if not raw.strip():
            raise ChartTampered(f"Blank line in the chart at line {index}.")
        try:
            record = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ChartTampered(f"Chart line {index} is not JSON: {exc}") from exc
        if not isinstance(record, dict):
            raise ChartTampered(f"Chart line {index} is not an object.")
        claimed = str(record.get("prev_hash") or "")
        if claimed != prev:
            raise ChartTampered(
                f"Chart chain break at line {index}: "
                f"expected prev_hash {prev[:12]}…, found {claimed[:12] or '(missing)'}…"
            )
        seq = record.get("seq")
        if seq is not None and int(seq) != index:
            raise ChartTampered(
                f"Chart sequence break at line {index}: expected seq {index}, found {seq}."
            )
        prev = line_hash(raw)


def _tail_state(path: Path) -> tuple[str, int]:
    lines = [line for line in _read_raw_lines(path) if line.strip()]
    if not lines:
        return GENESIS_HASH, 0
    return line_hash(lines[-1]), len(lines)


def _one_line(value: str, *, label: str, limit: int) -> str:
    text = (value or "").strip()
    if not text:
        raise ChartError(f"Every chart note needs a {label}.")
    if "\n" in text or "\r" in text:
        raise ChartError(f"The {label} has to be one line.")
    if len(text) > limit:
        raise ChartError(f"The {label} is longer than {limit} characters. Keep it short.")
    privacy.assert_safe_text(text, label=label)
    return text


def append(
    record: Mapping[str, Any],
    log_file: Path | None = None,
    *,
    now_iso: str | None = None,
) -> dict[str, Any]:
    """Append one record. Never rewrites existing bytes."""
    path = log_file or paths.chart_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = (
        paths.chart_lock_path()
        if log_file is None
        else path.with_suffix(path.suffix + ".lock")
    )
    lock.parent.mkdir(parents=True, exist_ok=True)

    payload = dict(record)
    if not payload.get("id"):
        payload["id"] = uuid.uuid4().hex[:12]
    if not payload.get("ts"):
        payload["ts"] = now_iso or paths.now_iso()
    payload["kind"] = payload.get("kind") or "note"
    payload["actor"] = _one_line(
        str(payload.get("actor") or "medic.py"), label="actor", limit=80
    )
    payload["trigger"] = _one_line(str(payload.get("trigger") or ""), label="trigger", limit=TRIGGER_MAX)
    payload["note"] = _one_line(str(payload.get("note") or ""), label="note", limit=NOTE_MAX)
    if payload.get("part"):
        payload["part"] = str(payload["part"]).strip().lower()
    payload["touched"] = str(
        payload.get("touched") or "medical/ chart and tags only"
    ).strip()
    payload["not_touched"] = str(
        payload.get("not_touched")
        or "The owner's off-limits files, routines, mail, freezes, restores"
    ).strip()
    privacy.assert_safe_text(payload["touched"], label="touched")
    privacy.assert_safe_text(payload["not_touched"], label="not_touched")
    if payload.get("ended"):
        payload["ended"] = _one_line(str(payload["ended"]), label="ended", limit=160)

    with open(lock, "a", encoding="utf-8") as lockf:
        fcntl.flock(lockf.fileno(), fcntl.LOCK_EX)
        try:
            verify_chain(path)
            prev_hash, count = _tail_state(path)
            payload["prev_hash"] = prev_hash
            payload["seq"] = count + 1
            line = json.dumps(
                payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
            )
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        finally:
            fcntl.flock(lockf.fileno(), fcntl.LOCK_UN)
    return payload


def format_chart(events: Sequence[Mapping[str, Any]] | None = None, *, limit: int = 0) -> str:
    records = list(events) if events is not None else read_events()
    if limit and limit > 0:
        records = records[-limit:]
    lines = [
        "Incident medical record (America/Chicago). Append-only. "
        "If it is not written down, it did not happen.",
        "",
    ]
    if not records:
        lines.append("(empty)")
        return "\n".join(lines)
    for event in records:
        ts = str(event.get("ts") or "")
        try:
            human = _human_ts(ts)
        except ValueError:
            human = ts or "(no timestamp)"
        kind = str(event.get("kind") or "note").upper()
        part = str(event.get("part") or "")
        tag = str(event.get("tag") or "")
        actor = str(event.get("actor") or "")
        header = f"{human}  {kind}"
        if part:
            header += f"  {part}"
        if tag:
            header += f"  [{tag}]"
        if actor:
            header += f"  by {actor}"
        lines.append(header)
        lines.append(f"  trigger: {event.get('trigger')}")
        lines.append(f"  {event.get('note')}")
        if event.get("ended"):
            lines.append(f"  ended: {event['ended']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _human_ts(value: str) -> str:
    text = (value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    from datetime import datetime

    stamp = datetime.fromisoformat(text)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=paths.TZ)
    stamp = stamp.astimezone(paths.TZ)
    try:
        shown = stamp.strftime("%Y-%m-%d %-I:%M %p")
    except ValueError:
        shown = stamp.strftime("%Y-%m-%d %I:%M %p").lstrip("0").replace(" 0", " ")
    return shown
