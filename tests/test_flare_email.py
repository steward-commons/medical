#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import flare_email
import guard
from tests.helpers import Isolate
from tests.test_cli import run


class TestFlareEmailDefaultOff(unittest.TestCase):
    def test_shipped_config_defaults_to_off(self):
        cfg = flare_email.load_config(flare_email.default_config_path())
        self.assertFalse(cfg["flare_email"])
        self.assertFalse(flare_email.enabled(cfg))
        self.assertIn(cfg["flare_email_to"], {"<your human's address>", ""})

    def test_coma_does_not_queue_email_when_default_off(self):
        with tempfile.TemporaryDirectory() as raw:
            with Isolate(Path(raw)):
                self.assertFalse(flare_email.enabled())
                code, out, err = run(
                    ["coma", "--on", "--reason", "Default-off check."]
                )
                self.assertEqual(code, 0, err)
                self.assertTrue(guard.coma_is_on())
                self.assertIn("No email was sent", out)
                self.assertNotIn("Flare email queued", out)
                self.assertTrue(guard.flare_path().is_file())
                self.assertFalse(guard.flare_email_outbox_path().is_file())
                self.assertIsNone(flare_email.queue_flare_email(
                    reason="Default-off check.",
                    when="2026-11-19 9:24 AM (America/Chicago)",
                    event_id="should-not-queue",
                ))
                self.assertFalse(guard.flare_email_outbox_path().is_file())
                sent: list[tuple[str, str, str]] = []

                def transport(to: str, subject: str, body: str) -> None:
                    sent.append((to, subject, body))

                result = flare_email.send_queued(transport=transport)
                self.assertFalse(result["sent"])
                self.assertEqual(result["reason"], "disabled")
                self.assertEqual(sent, [])

    def test_opt_in_queues_one_locked_email(self):
        with tempfile.TemporaryDirectory() as raw:
            with Isolate(Path(raw)) as iso:
                (iso.data / "flare-email.conf").write_text(
                    "flare_email: on\nflare_email_to: owner@example.com\n",
                    encoding="utf-8",
                )
                self.assertTrue(flare_email.enabled())
                code, out, err = run(
                    ["coma", "--on", "--reason", "Opt-in check."]
                )
                self.assertEqual(code, 0, err)
                self.assertTrue(guard.flare_email_outbox_path().is_file())
                record = flare_email.load_outbox()
                self.assertEqual(record["to"], "owner@example.com")
                self.assertIn("nothing else happens until you wake me", record["body"].lower())
                self.assertIn("America/Chicago", record["body"])
                with self.assertRaises(flare_email.FlareEmailError):
                    flare_email.queue_flare_email(
                        reason="Opt-in check.",
                        when="2026-11-19 9:24 AM (America/Chicago)",
                        event_id="other",
                        to="someone-else@example.com",
                    )
                sent: list[tuple[str, str, str]] = []

                def transport(to: str, subject: str, body: str) -> None:
                    sent.append((to, subject, body))

                first = flare_email.send_queued(transport=transport)
                second = flare_email.send_queued(transport=transport)
                self.assertTrue(first["sent"])
                self.assertEqual(first["to"], "owner@example.com")
                self.assertFalse(second["sent"])
                self.assertEqual(len(sent), 1)
                # Tampered recipient is blocked.
                record = flare_email.load_outbox()
                record["to"] = "someone-else@example.com"
                guard.flare_email_outbox_path().write_text(
                    json.dumps(record, indent=2) + "\n", encoding="utf-8"
                )
                # Already marked sent before tamper in this flow? rewrite as queued.
                record["status"] = "queued"
                record["sent_at"] = None
                guard.flare_email_outbox_path().write_text(
                    json.dumps(record, indent=2) + "\n", encoding="utf-8"
                )
                blocked = flare_email.send_queued(transport=transport)
                self.assertFalse(blocked["sent"])
                self.assertEqual(blocked["reason"], "recipient locked")
                self.assertEqual(len(sent), 1)

    def test_flare_email_reply_cannot_wake(self):
        with tempfile.TemporaryDirectory() as raw:
            with Isolate(Path(raw)):
                run(["coma", "--on", "--reason", "Reply cannot wake."])
                for actor in ("flare-email-reply", "flare-email", "inbound-email", "email"):
                    code, out, err = run(
                        [
                            "coma",
                            "--off",
                            "--i-have-owner-ok",
                            "--actor",
                            actor,
                        ]
                    )
                    self.assertEqual(code, 2, actor)
                    self.assertTrue(guard.coma_is_on(), actor)


if __name__ == "__main__":
    unittest.main()
