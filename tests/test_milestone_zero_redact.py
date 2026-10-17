"""Hermetic redaction hardening tests for milestone-zero export (synthetic only)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
MZ = ROOT / "evals" / "milestone-zero"
FIX = ROOT / "tests" / "fixtures" / "milestone-zero"

sys.path.insert(0, str(MZ))

from redact import (  # noqa: E402
    REDACTION_VERSION,
    ExclusionRules,
    RedactionContext,
    collect_session_text,
    load_forgotten,
    load_known_names,
    redact_fail_closed,
    redact_object,
    scan_residue_secondary,
    secure_write_text,
    session_should_exclude,
    write_manifest,
)

VAULT_REGRESSION: dict[str, tuple[str, list[str]]] = {
    "dani_w": ("Spoke with Dani W. about the offer", ["CLIENT_"]),
    "phone_555_0142": ("callback at 555-0142", ["[REDACTED_PHONE]"]),
    "account_number": ("account number 55512345", ["[REDACTED_ACCOUNT]"]),
    "checking_ending": ("checking ending 4455", ["[REDACTED_ACCOUNT]"]),
    "card_spaced": ("paid with 4111 1111 1111 1111", ["[REDACTED_CARD]"]),
    "ein": ("EIN 12-3456789", ["[REDACTED_EIN]"]),
    "loan": ("loan 0042-77 on file", ["[REDACTED_LOAN]"]),
    "knee_surgery": ("scheduled knee surgery next week", ["[REDACTED_HEALTH]"]),
    "has_cancer": ("she has cancer", ["[REDACTED_HEALTH]"]),
    "therapy": ("started therapy again", ["[REDACTED_HEALTH]"]),
    "divorce_attorney": ("talked to divorce attorney", ["[REDACTED_LEGAL]"]),
    "custody": ("custody hearing moved", ["[REDACTED_LEGAL]"]),
    "dob": ("DOB 03/15/1988", ["[REDACTED_DOB]"]),
    "drive_url": ("see https://drive.google.com/file/d/abc123/view", ["[REDACTED_URL]"]),
    "listing_url": ("https://www.zillow.com/homedetails/123-main", ["[REDACTED_URL]"]),
}

HEALTH_WORDINGS = [
    "patient has diabetes type 2",
    "underwent hip replacement last year",
    "diagnosed with bipolar disorder",
    "chemotherapy starts Monday",
    "medication for anxiety disorder",
    "hospitalized after the fall",
]

LEGAL_WORDINGS = [
    "pending lawsuit against the HOA",
    "filed bankruptcy chapter 7",
    "received a subpoena yesterday",
    "probate court date set",
    "restraining order was granted",
    "their lawyer sent a letter",
]

PLANTED_SECRETS = [
    "555-0199",
    "555-0142",
    "123-45-6789",
    "secret.patient@example.com",
    "4111 1111 1111 1111",
    "12-3456789",
    "loan 0042-77",
    "account number 99887766",
    "Dani W.",
    "https://drive.google.com/file/d/planted99/view",
    "lockbox code is 9182",
    "DOB 01/02/1990",
]


def generate_synthetic_sessions(count: int = 110) -> list[dict[str, object]]:
    sessions: list[dict[str, object]] = []
    templates = [
        "my client {name} emailed {email} about {health}",
        "meeting with {name} at {addr}",
        "call {name} at {phone} re {legal}",
        "Mr. {name} DOB {dob} acct {acct}",
        "{url} and gate code is {code}",
    ]
    for i in range(count):
        secret = PLANTED_SECRETS[i % len(PLANTED_SECRETS)]
        health = HEALTH_WORDINGS[i % len(HEALTH_WORDINGS)]
        legal = LEGAL_WORDINGS[i % len(LEGAL_WORDINGS)]
        body = templates[i % len(templates)].format(
            name="Dani W." if i % 7 == 0 else f"Pat{i}",
            email=f"user{i}@example.com",
            addr=f"{100 + i} Oak St, Phoenix, AZ 8500{i % 10}",
            phone=f"555-01{i % 10:02d}",
            health=health,
            legal=legal,
            dob="03/15/1988",
            acct=f"account number {55510000 + i}",
            url="https://www.zillow.com/homedetails/plant",
            code=f"{9000 + i}",
        )
        sessions.append(
            {
                "session_id": f"syn-{i:04d}",
                "owner_text": body + " " + secret,
                "messages": [{"role": "user", "content": body}],
            }
        )
    return sessions


def assert_no_leaks(blob: str, planted: list[str]) -> None:
    lowered = blob.lower()
    for value in planted:
        if value.lower() in lowered:
            raise AssertionError(f"leak detected: {value!r}")
    residue = scan_residue_secondary(blob)
    if residue:
        raise AssertionError(f"residue kinds: {residue}")


class VaultRegression(unittest.TestCase):
    def test_section_2_named_cases(self) -> None:
        for name, (text, must_include) in VAULT_REGRESSION.items():
            cleaned, _codes, ok, residue = redact_fail_closed(text)
            self.assertTrue(ok, f"{name}: residue={residue} text={cleaned}")
            for frag in must_include:
                self.assertIn(frag, cleaned, name)
            assert_no_leaks(cleaned, [text] if "Dani" not in text else ["Dani W."])


class SyntheticLeakSuite(unittest.TestCase):
    def test_hundred_plus_sessions_redact_clean(self) -> None:
        sessions = generate_synthetic_sessions(110)
        ctx = RedactionContext(known_names=["Pat42"])
        for session in sessions:
            redacted, _codes, ok, residue = redact_object(session, ctx)
            self.assertTrue(ok, residue)
            blob = json.dumps(redacted, ensure_ascii=False)
            assert_no_leaks(blob, PLANTED_SECRETS + ["@example.com", "Oak St", "Phoenix"])

    def test_weakened_detector_makes_leak_test_fail(self) -> None:
        raw = "she has cancer and account number 55512345"

        def leak_guard(blob: str, secrets: list[str]) -> None:
            assert_no_leaks(blob, secrets)

        cleaned, _, ok, _ = redact_fail_closed(raw)
        self.assertTrue(ok)
        leak_guard(cleaned, ["cancer", "55512345"])

        def noop_redact(text: str, ctx: RedactionContext | None = None) -> tuple[str, list[str]]:
            return text, []

        with mock.patch("redact.redact_text", noop_redact):
            weak, _, weak_ok, _ = redact_fail_closed(raw)
        self.assertFalse(weak_ok)
        with self.assertRaises(AssertionError):
            leak_guard(weak, ["cancer", "55512345"])


class ExclusionRulesTest(unittest.TestCase):
    def test_do_not_keep_exact_and_reworded(self) -> None:
        rules = ExclusionRules.load(FIX / "rules.json")
        exact = {"owner_text": "please save bankruptcy filing details here"}
        reword = {"owner_text": "bankruptcy filing detail note for files"}
        self.assertEqual(session_should_exclude(exact, rules, []), "do_not_keep")
        self.assertEqual(session_should_exclude(reword, rules, []), "do_not_keep")

    def test_forgotten_opt_out_minor_forget(self) -> None:
        rules = ExclusionRules.load(FIX / "rules.json")
        with tempfile.TemporaryDirectory() as tmp:
            forgotten_path = Path(tmp) / "forgotten.txt"
            forgotten_path.write_text("purple elephant story\n", encoding="utf-8")
            os.chmod(forgotten_path, 0o600)
            forgotten = load_forgotten(forgotten_path)
        self.assertEqual(
            session_should_exclude({"owner_text": "purple elephant story retold"}, rules, forgotten),
            "forgotten",
        )
        self.assertEqual(session_should_exclude({"owner_opt_out": True}, rules, []), "owner_opt_out")
        self.assertEqual(session_should_exclude({"owner_text": "my 12-year-old child"}, rules, []), "minor_mentioned")
        self.assertEqual(session_should_exclude({"owner_text": "run /new thread"}, rules, []), "forget_command")


class ExportIntegration(unittest.TestCase):
    def test_export_fail_closed_and_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            os.chmod(base, 0o700)
            session_path = base / "session.json"
            session_path.write_text(
                json.dumps({"owner_text": "Text at 555-010-0999", "assistant_text": "ok"}),
                encoding="utf-8",
            )
            out_path = base / "out.jsonl"
            manifest = base / "out.manifest.json"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(MZ / "export_session_to_case.py"),
                    "--session",
                    str(session_path),
                    "--id",
                    "mz-t",
                    "--category",
                    "no_answer",
                    "--out",
                    str(out_path),
                    "--manifest",
                    str(manifest),
                ],
                capture_output=True,
                text=True,
                cwd=str(MZ),
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stdout.strip(), "")
            self.assertIn("session_index=", proc.stderr)
            self.assertNotIn(str(session_path), proc.stderr)
            line = out_path.read_text(encoding="utf-8").strip()
            assert_no_leaks(line, ["555-010-0999"])
            meta = json.loads(line)["export_meta"]
            self.assertNotIn("source", meta)
            self.assertIn("session_index", meta)
            self.assertEqual(meta["redaction_version"], REDACTION_VERSION)
            self.assertEqual(oct(out_path.stat().st_mode & 0o777), "0o600")
            self.assertEqual(oct(manifest.stat().st_mode & 0o777), "0o600")
            manifest_body = manifest.read_text(encoding="utf-8")
            assert_no_leaks(manifest_body, ["555-010-0999"])

    def test_excluded_session_emits_count_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            session_path = base / "session.json"
            session_path.write_text(json.dumps({"owner_opt_out": True, "owner_text": "hi"}), encoding="utf-8")
            out_path = base / "out.jsonl"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(MZ / "export_session_to_case.py"),
                    "--session",
                    str(session_path),
                    "--id",
                    "mz-x",
                    "--category",
                    "no_answer",
                    "--out",
                    str(out_path),
                    "--rules",
                    str(FIX / "rules.json"),
                ],
                capture_output=True,
                text=True,
                cwd=str(MZ),
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("excluded_sessions: 1", proc.stderr)
            self.assertFalse(out_path.exists())

    def test_known_names_file_requires_0600(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            names = Path(tmp) / "names.txt"
            names.write_text("Dana Example\n", encoding="utf-8")
            os.chmod(names, 0o644)
            with self.assertRaises(Exception):
                load_known_names(names)


class ManifestAndPhones(unittest.TestCase):
    def test_manifest_content_free(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "m.json"
            write_manifest(path, {"phone": 2})
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["redaction_version"], REDACTION_VERSION)
            self.assertEqual(data["counts"], {"phone": 2})
            self.assertIn("deletion_date", data)

    def test_phones_only_redacted_phone_token(self) -> None:
        cleaned, _, ok, _ = redact_fail_closed("call 555-0142 or 6025551212")
        self.assertTrue(ok)
        self.assertNotIn("0142", cleaned)
        self.assertEqual(cleaned.count("[REDACTED_PHONE]"), 2)
        self.assertNotRegex(cleaned, r"\d{4}")


if __name__ == "__main__":
    unittest.main()
