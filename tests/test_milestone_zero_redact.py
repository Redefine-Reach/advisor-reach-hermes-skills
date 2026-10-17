"""Hermetic tests for milestone-zero export redaction (synthetic fixtures only)."""

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
FIX_MAIN = MZ / "fixtures" / "fake_sessions"

sys.path.insert(0, str(MZ))

from redact import (  # noqa: E402
    EXIT_BLOCKED,
    EXIT_EXCLUDED,
    EXIT_OK,
    REDACTION_VERSION,
    RedactionContext,
    redact_fail_closed,
    scan_residue_secondary,
    session_drop_reason,
    ExclusionRules,
    write_manifest,
)

VAULT_NAMED = {
    "phone_555_0142": ("callback at 555-0142", "[PHONE ***0142]"),
    "account_number": ("account number 55512345", "[REDACTED_ACCOUNT]"),
    "dani_w": ("Spoke with Dani W. about the offer", "CLIENT_"),
    "call_friday": ("call Friday about the open house", "Friday"),
}


class VaultRegression(unittest.TestCase):
    def test_named_regression_rows(self) -> None:
        ctx = RedactionContext(owner_name="Alex")
        for name, (text, frag) in VAULT_NAMED.items():
            cleaned, _, ok, residue = redact_fail_closed(text, ctx)
            self.assertTrue(ok, f"{name}: {residue} -> {cleaned}")
            self.assertIn(frag, cleaned, name)

    def test_health_session_drops_at_export_layer(self) -> None:
        session = {"owner_text": "she has cancer and needs gentle wording"}
        reason = session_drop_reason(session, ExclusionRules(), [])
        self.assertEqual(reason, "health")


class ExportIntegration(unittest.TestCase):
    def test_export_text_mode_and_exit_codes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            good = base / "s001.txt"
            good.write_text(
                (FIX_MAIN / "s001.txt").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            out = base / "out.txt"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(MZ / "export_session_to_case.py"),
                    "--session",
                    str(good),
                    "--redacted-text-out",
                    str(out),
                    "--known-names",
                    str(FIX_MAIN / "known_names.txt"),
                    "--rules",
                    str(FIX_MAIN / "donotkeep_rules.json"),
                    "--forgotten",
                    str(FIX_MAIN / "forgotten.txt"),
                    "--owner-name",
                    "Alex",
                ],
                capture_output=True,
                text=True,
                cwd=str(MZ),
            )
            self.assertEqual(proc.returncode, EXIT_OK, proc.stderr)
            body = out.read_text(encoding="utf-8")
            self.assertIn("[PHONE ***", body)
            self.assertNotIn("6025550142", body.replace(" ", ""))

            drop = base / "s063.txt"
            drop.write_text(
                (FIX_MAIN / "s063.txt").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            proc2 = subprocess.run(
                [
                    sys.executable,
                    str(MZ / "export_session_to_case.py"),
                    "--session",
                    str(drop),
                    "--redacted-text-out",
                    str(base / "drop.out"),
                    "--known-names",
                    str(FIX_MAIN / "known_names.txt"),
                    "--rules",
                    str(FIX_MAIN / "donotkeep_rules.json"),
                    "--forgotten",
                    str(FIX_MAIN / "forgotten.txt"),
                ],
                capture_output=True,
                text=True,
                cwd=str(MZ),
            )
            self.assertEqual(proc2.returncode, EXIT_EXCLUDED, proc2.stderr)
            self.assertIn("excluded_sessions: 1 category=health", proc2.stderr)
            self.assertFalse((base / "drop.out").exists())

    def test_blocked_decode_error_is_exit_1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            broken = Path(tmp) / "bad.txt"
            broken.write_bytes(b"OWNER: hi\x00there\n")
            out = Path(tmp) / "o.txt"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(MZ / "export_session_to_case.py"),
                    "--session",
                    str(broken),
                    "--redacted-text-out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                cwd=str(MZ),
            )
            self.assertEqual(proc.returncode, EXIT_BLOCKED)
            self.assertFalse(out.exists())


class LeakGuard(unittest.TestCase):
    def test_weakened_detector_makes_leak_guard_fail(self) -> None:
        raw = "account number 55512345"

        def guard(blob: str) -> None:
            self.assertNotIn("55512345", blob)
            self.assertFalse(scan_residue_secondary(blob))

        cleaned, _, ok, _ = redact_fail_closed(raw, RedactionContext())
        self.assertTrue(ok)
        guard(cleaned)

        with mock.patch("redact.redact_text", lambda t, ctx: (t, [])):
            weak, _, weak_ok, _ = redact_fail_closed(raw, RedactionContext())
        self.assertFalse(weak_ok)
        with self.assertRaises(AssertionError):
            guard(weak)


class Manifest(unittest.TestCase):
    def test_manifest_has_30_day_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "m.json"
            write_manifest(path, {"phone": 1})
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["redaction_version"], REDACTION_VERSION)
            self.assertIn("deletion_date", data)


class CheckLeaksCI(unittest.TestCase):
    def test_fake_sets_zero_leaks(self) -> None:
        cmd = (
            "python3 export_session_to_case.py --session {in} --redacted-text-out {out} "
            "--known-names {known} --rules {rules} --forgotten {forgotten} --owner-name Alex"
        )
        for label, sub in (("main", FIX_MAIN), ("heldout", MZ / "fixtures" / "fake_sessions_heldout")):
            proc = subprocess.run(
                [
                    sys.executable,
                    str(MZ / "check_leaks.py"),
                    "--label",
                    label,
                    "--cwd",
                    str(MZ),
                    "--sessions",
                    str(sub),
                    "--cmd",
                    cmd,
                    "--strict-drop",
                    "--fail-on-overredaction",
                ],
                capture_output=True,
                text=True,
                cwd=str(MZ),
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("LEAKS TOTAL: 0", proc.stdout)


if __name__ == "__main__":
    unittest.main()
