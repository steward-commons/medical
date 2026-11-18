#!/usr/bin/env python3
"""Refuse secrets and private paths in the medical chart.

A pointer is enough. Vault data, passwords, money info, the owner's medical
files, and private/ paths do not belong in a chart note.
"""

from __future__ import annotations

import re
from pathlib import Path

import paths

SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
KEY_RE = re.compile(
    r"\b(AIza[0-9A-Za-z\-_]{20,}|sk-[A-Za-z0-9]{16,}|GEMINI_API_KEY\s*=)\b"
)

# Add your own household literals (an email handle, a street name) here.
LITERALS = (
    "vault",
    "password",
    "passwd",
    "~/.config",
    "private - sensitive records",
    "private/medical",
    "private/sensitive",
    "api key",
    "apikey",
    "secret token",
)


class PrivacyError(Exception):
    """Chart text was rejected because it looks like a secret or private path."""


def assert_safe_text(text: str, *, label: str = "note") -> str:
    raw = text or ""
    lowered = raw.lower()
    for lit in LITERALS:
        if lit in lowered:
            raise PrivacyError(
                f"The {label} looks like it contains a secret or a private "
                "path. Keep chart notes short and boring: a pointer is enough."
            )
    if SSN_RE.search(raw) or KEY_RE.search(raw):
        raise PrivacyError(
            f"The {label} looks like it contains a secret. "
            "A pointer is enough; do not paste keys, vault data, or numbers."
        )
    # Refuse any path that resolves under private/.
    for token in raw.split():
        if "private/" in token.lower() or token.lower().endswith("/private"):
            raise PrivacyError(
                f"The {label} points at private/. House Medical never opens, "
                "copies, or cites the owner's private files."
            )
        if token.startswith("/") and ".." not in token:
            try:
                if paths.is_private_path(Path(token.split(":")[0])):
                    raise PrivacyError(
                        f"The {label} points at private/. That is off-limits."
                    )
            except PrivacyError:
                raise
            except (OSError, ValueError):
                pass
    return raw.strip()
