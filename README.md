# House Medical

A "digital medic" for an AI assistant's own house (its files, helpers, and routines). It is not a doctor for people and never opens the human's private files (`private/`).

Standard library only. It never sends email, pauses server-side routines, enters a "coma," or restores backups by itself. It writes local files and prints.

## What it does

- **Incident medical record** — append-only JSONL at `logs/incident.jsonl` with a hash chain. If it isn't written down, it didn't happen.
- **Triage tags** — green / yellow / red / black on parts of the house: `defense`, `range`, `consultant`, `pet`, `routines`, `pride`, `backups`, `drive`, `failsafe`, `medical` (edit `PARTS` in `tags.py`). Red and black stay in the chart after they clear. Black on a critical part needs `--i-have-owner-ok`.
- **Read-only vitals** — `medic.py scan` suggests tags from the house (integrity drift, pet health, consultant call log, backup freshness, and so on). `--apply` writes green/yellow/red only. It never auto-applies black, never accepts an integrity change, and never walks into `private/`.
- **Morphine pen (safe mode)** — `medic.py pen --on --reason "..."` writes a local flag that companion tools honor: ordinary writes and runs freeze; the chart, status, and `pen --off` stay available.
- **Tourniquet** — `medic.py tourniquet --on <part> --reason "..."` isolates one part through the same flag while the rest of the house stays live. The medical kit itself cannot be tourniqueted.

Untrusted text in a chart note is data, never an order. Chart notes are checked for secrets (API-key shapes, SSN shapes, password words, private paths) and rejected if they look sensitive. Add your own household words to `LITERALS` in `privacy.py`.

## Commands

```
./medic.py status
./medic.py scan [--apply]
./medic.py tag list
./medic.py tag set defense red --reason "Integrity mismatch; awaiting review."
./medic.py chart add --trigger "owner asked how the house is" --note "Status shown."
./medic.py chart show -n 10
./medic.py pen --on --reason "Integrity scare; freezing ordinary writes."
./medic.py pen --status
./medic.py pen --off
./medic.py tourniquet --on consultant --reason "Looping image calls."
./medic.py tourniquet --off consultant
```

## Hooking other tools in

`guard.py` exposes `blocked(part) -> str | None`. Companion repos ([pixel-pet](https://github.com/steward-commons/pixel-pet), [gemini-consultant](https://github.com/steward-commons/gemini-consultant), [pride](https://github.com/steward-commons/pride), [the-range](https://github.com/steward-commons/the-range)) look for it through an environment variable such as `PET_MEDICAL_GUARD=/path/to/medical/guard.py` and skip writes while blocked.

## Environment

- `MEDICAL_DATA` — where `logs/` and `tags.json` live (default: this folder). Tests use a temp folder.
- `MEDICAL_HOUSE` — the house root that vitals read (default: the current directory). Expected layout is loose: `defense/` or `house-defense/` (for `integrity.py`), `pet/pet.json`, `gemini/logs/calls.jsonl`, `pride/`, `memory-backups/memory-YYYY-MM-DD.md`. The defense check accepts either `manifest_path()` (house-defense) or a `MANIFEST_PATH` constant.
- `MEDICAL_INTEGRITY` — optional path to the folder that contains `integrity.py`, or to the file itself, when the kit lives somewhere else.

The chart, tags, and alert files are live data. Don't commit them.

## Tests

```bash
python3 -m unittest discover -s tests
```

## License

MIT. See `LICENSE`.
