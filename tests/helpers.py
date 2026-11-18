"""Test helpers: isolate medical data so tests never touch the live chart."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

MEDICAL = Path(__file__).resolve().parents[1]
if str(MEDICAL) not in sys.path:
    sys.path.insert(0, str(MEDICAL))


class Isolate:
    """Point medical data and a fake house at a temp folder."""

    def __init__(self, tmp: Path) -> None:
        self.data = tmp / "medical-data"
        self.house = tmp / "house"
        self.data.mkdir()
        (self.data / "logs").mkdir()
        self.house.mkdir()
        self._old = {
            "MEDICAL_DATA": os.environ.get("MEDICAL_DATA"),
            "MEDICAL_HOUSE": os.environ.get("MEDICAL_HOUSE"),
        }
        os.environ["MEDICAL_DATA"] = str(self.data)
        os.environ["MEDICAL_HOUSE"] = str(self.house)

    def close(self) -> None:
        for key, value in self._old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def __enter__(self) -> "Isolate":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def write(self, rel: str, content: str | dict) -> Path:
        path = self.house / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, dict):
            path.write_text(json.dumps(content, indent=2) + "\n", encoding="utf-8")
        else:
            path.write_text(content, encoding="utf-8")
        return path
