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

from phrase_match import phrase_hit  # noqa: E402
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
    @classmethod
    def setUpClass(cls) -> None:
        for path in (
            FIX_MAIN / "known_names.txt",
            FIX_MAIN / "forgotten.txt",
            MZ / "fixtures" / "fake_sessions_heldout" / "known_names.txt",
            MZ / "fixtures" / "fake_sessions_heldout" / "forgotten.txt",
            MZ / "fixtures" / "fake_sessions_heldout2" / "known_names.txt",
            MZ / "fixtures" / "fake_sessions_heldout2" / "forgotten.txt",
        ):
            if path.exists():
                os.chmod(path, 0o600)

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

    def test_jsonl_export_requires_known_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp) / "s.json"
            session.write_text(
                json.dumps({"owner_text": "callback at 555-0142", "arin_text": "ok"}),
                encoding="utf-8",
            )
            proc = subprocess.run(
                [
                    sys.executable,
                    str(MZ / "export_session_to_case.py"),
                    "--session",
                    str(session),
                    "--id",
                    "mz-test",
                    "--category",
                    "send_draft",
                    "--out",
                    str(Path(tmp) / "cases.jsonl"),
                ],
                capture_output=True,
                text=True,
                cwd=str(MZ),
            )
            self.assertEqual(proc.returncode, EXIT_BLOCKED, proc.stderr)
            self.assertIn("known_names_required", proc.stderr)


class PhraseMatch(unittest.TestCase):
    def test_do_not_keep_stem_matches_plural(self) -> None:
        self.assertTrue(phrase_hit("please do not keep mornings chaos", "do not keep morning chaos"))
        self.assertTrue(phrase_hit("do not keep evenings only", "do not keep evening only"))


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
    @classmethod
    def setUpClass(cls) -> None:
        ExportIntegration.setUpClass()

    def test_fake_sets_zero_leaks(self) -> None:
        cmd = (
            "python3 export_session_to_case.py --session {in} --redacted-text-out {out} "
            "--known-names {known} --rules {rules} --forgotten {forgotten} --owner-name Alex"
        )
        for label, sub in (
            ("main", FIX_MAIN),
            ("heldout", MZ / "fixtures" / "fake_sessions_heldout"),
            ("heldout2", MZ / "fixtures" / "fake_sessions_heldout2"),
        ):
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



def _msg(role: str, content: str) -> dict[str, str]:
    return {"role": role, "content": content}


class _ExportHelpers:

    @classmethod
    def setUpClass(cls) -> None:
        os.chmod(FIX_MAIN / "known_names.txt", 0o600)

    def _export(self, session: dict, extra: list[str] | None = None, out_dir: Path | None = None):
        tmp = tempfile.mkdtemp()
        os.chmod(tmp, 0o700)
        base = Path(tmp)
        sess = base / "session.json"
        sess.write_text(json.dumps(session), encoding="utf-8")
        out = (out_dir or (base / "redacted")) / "cases-export.jsonl"
        proc = subprocess.run(
            [sys.executable, str(MZ / "export_session_to_case.py"), "--session", str(sess),
             "--id", "syn-01", "--category", "send_draft", "--known-names", str(FIX_MAIN / "known_names.txt"),
             "--out", str(out), "--manifest", str(base / "m.json"),
             *([] if extra and "--source" in extra else ["--source", "cli"]), *(extra or [])],
            capture_output=True, text=True, cwd=str(MZ),
        )
        text = out.read_text(encoding="utf-8").strip() if out.exists() else ""
        case = json.loads(text.splitlines()[-1]) if text else None
        return proc, case, out

    def _long_session(self) -> dict:
        msgs = []
        for i in range(7):
            msgs.append(_msg("user", f"owner turn {i} about the listing"))
            msgs.append(_msg("assistant", f"arin turn {i} noted"))
        msgs.append(_msg("tool", "tool output ignored"))
        msgs.append(_msg("user", "text Dana I am running late"))
        msgs.append(_msg("assistant", "Drafted to Dana: running 10 late."))
        msgs.append(_msg("assistant", "Why: Dana is waiting at the showing. Reply SEND to send."))
        return {"messages": msgs}



class ExportKeepsContextAndReply(_ExportHelpers, unittest.TestCase):
    """RED-681: cases keep context turns, last owner message and recorded reply (synthetic only)."""

    def test_keeps_last_owner_reply_and_ten_context_turns(self) -> None:
        proc, case, out = self._export(self._long_session())
        self.assertEqual(proc.returncode, EXIT_OK, proc.stderr)
        self.assertRegex(case["input"]["owner_text"], r"^text \S+ I am running late$")
        self.assertNotIn("Dana", json.dumps(case))  # third-party name replaced in owner, context AND reply
        self.assertRegex(case["fixture"]["assistant_text"].splitlines()[0], r"^Drafted to \S+: running 10 late\.$")
        self.assertIn("Reply SEND", case["fixture"]["assistant_text"])
        ctx = case["input"]["context_turns"]
        self.assertEqual(len(ctx), 10)
        self.assertEqual(ctx[-1], {"role": "arin", "content": "arin turn 6 noted"})
        self.assertEqual({t["role"] for t in ctx}, {"owner", "arin"})
        self.assertIn("owner: owner turn 6", case["input"]["context_available"])
        meta = case["export_meta"]
        self.assertTrue(meta["recorded_reply_present"])
        self.assertEqual(meta["turns_skipped_non_text"], 1)
        self.assertEqual(meta["context_turns_kept"], 10)
        self.assertIs(case["synthetic"], False)
        self.assertIsNone(case["draft_expected"])

    def test_context_turn_limit_flag(self) -> None:
        for n, want in ((0, 0), (3, 3), (50, 14)):
            proc, case, _ = self._export(self._long_session(), ["--context-turns", str(n)])
            self.assertEqual(proc.returncode, EXIT_OK, proc.stderr)
            self.assertEqual(len(case["input"]["context_turns"]), want, n)
        proc, case, _ = self._export(self._long_session(), ["--context-turns", "-1"])
        self.assertEqual(proc.returncode, EXIT_BLOCKED)
        self.assertIsNone(case)

    def test_section_ending_on_owner_has_no_reply(self) -> None:
        sess = {"messages": [_msg("user", "can you check the showing time"), _msg("assistant", "Which one?"),
                             _msg("user", "the Saturday one")]}
        proc, case, _ = self._export(sess)
        self.assertEqual(proc.returncode, EXIT_OK, proc.stderr)
        self.assertEqual(case["input"]["owner_text"], "the Saturday one")
        self.assertEqual(case["fixture"]["assistant_text"], "")
        self.assertFalse(case["export_meta"]["recorded_reply_present"])
        self.assertEqual(len(case["input"]["context_turns"]), 2)

    def test_context_and_reply_are_redacted_before_write(self) -> None:
        sess = {"messages": [_msg("user", "Zelda Clientfake cell is 602-555-0142"),
                             _msg("assistant", "Got it, saved 602 555 0142 for Zelda Clientfake"),
                             _msg("user", "text her I am late"),
                             _msg("assistant", "Drafted to Zelda Clientfake at 602-555-0142. Why: she asked for an ETA.")]}
        proc, case, out = self._export(sess)
        self.assertEqual(proc.returncode, EXIT_OK, proc.stderr)
        body = out.read_text(encoding="utf-8")
        self.assertNotIn("Clientfake", body)
        self.assertNotIn("6025550142", body.replace("-", "").replace(" ", ""))
        self.assertIn("[PHONE ***0142]", body)
        self.assertNotIn("Clientfake", proc.stderr + proc.stdout)
        self.assertNotIn("text her", proc.stderr + proc.stdout)

    def test_health_in_any_turn_excludes_whole_session(self) -> None:
        sess = {"messages": [_msg("user", "she has cancer so keep it gentle"), _msg("assistant", "Understood."),
                             _msg("user", "text her the open house time"), _msg("assistant", "Drafted.")]}
        proc, case, out = self._export(sess)
        self.assertEqual(proc.returncode, EXIT_EXCLUDED, proc.stderr)
        self.assertFalse(out.exists())

    def test_health_in_recorded_reply_excludes(self) -> None:
        sess = {"owner_text": "text her the time",
                "messages": [_msg("user", "text her the time"), _msg("assistant", "Drafted; I noted her cancer.")]}
        proc, case, out = self._export(sess)
        self.assertEqual(proc.returncode, EXIT_EXCLUDED, proc.stderr)
        self.assertFalse(out.exists())

    def test_modes_0600_file_0700_dir(self) -> None:
        proc, case, out = self._export(self._long_session())
        self.assertEqual(proc.returncode, EXIT_OK, proc.stderr)
        self.assertEqual(out.stat().st_mode & 0o777, 0o600)
        self.assertEqual(out.parent.stat().st_mode & 0o777, 0o700)

    def test_refuses_out_inside_git_worktree(self) -> None:
        proc, case, out = self._export(self._long_session(), out_dir=ROOT / "evals" / "milestone-zero" / "tmp-red681")
        self.assertEqual(proc.returncode, EXIT_BLOCKED)
        self.assertIn("out_inside_git_worktree", proc.stderr)
        self.assertFalse(out.exists())
        self.assertFalse((ROOT / "evals" / "milestone-zero" / "tmp-red681").exists())


class ExportVaultRequirements(_ExportHelpers, unittest.TestCase):
    """Vault Oct 19: source filter, whole-case redaction, owner name, perms, ids/counts-only listing."""

    def test_unknown_third_party_name_and_number_redacted_in_reply_and_context(self) -> None:
        sess = {"messages": [
            _msg("user", "text Priya that the inspection moved"),
            _msg("assistant", "Drafted to Priya. Why: Priya asked about the inspection. Her cell 480-555-0199."),
            _msg("user", "also tell Marco and Priya the new time"),
            _msg("assistant", "Drafted to Marco and Priya at 480 555 0199 and (602) 555-0123."),
        ]}
        proc, case, out = self._export(sess, ["--owner-name", "David"])
        self.assertEqual(proc.returncode, EXIT_OK, proc.stderr)
        body = out.read_text(encoding="utf-8")
        for raw in ("Priya", "Marco", "4805550199", "6025550123"):
            self.assertNotIn(raw, body.replace("-", "").replace(" ", "").replace("(", "").replace(")", "") if raw.isdigit() else body)
        self.assertIn("[PHONE ***0199]", body)
        self.assertNotIn("Priya", proc.stderr + proc.stdout)

    def test_owner_name_david_is_kept(self) -> None:
        sess = {"messages": [_msg("user", "David here, text Priya I am late"),
                             _msg("assistant", "Drafted for David to Priya.")]}
        proc, case, _ = self._export(sess, ["--owner-name", "David"])
        self.assertEqual(proc.returncode, EXIT_OK, proc.stderr)
        self.assertIn("David", case["input"]["owner_text"])
        self.assertNotIn("Priya", json.dumps(case))

    def test_automated_source_excluded_and_source_required(self) -> None:
        for src in ("cron", "telegram", "webhook"):
            proc, case, out = self._export(self._long_session(), ["--source", src])
            self.assertEqual(proc.returncode, EXIT_EXCLUDED, src)
            self.assertFalse(out.exists())
        sess = dict(self._long_session(), source="cron")
        proc, case, out = self._export(sess, ["--source", "cli"])
        self.assertEqual(proc.returncode, EXIT_EXCLUDED)
        for src in ("telnyx_sms", "cli", "api_server"):
            proc, case, _ = self._export(self._long_session(), ["--source", src])
            self.assertEqual(proc.returncode, EXIT_OK, src)
            self.assertEqual(case["export_meta"]["source"], src)
        tmp = Path(tempfile.mkdtemp())
        sess_path = tmp / "s.json"
        sess_path.write_text(json.dumps(self._long_session()), encoding="utf-8")
        proc = subprocess.run([sys.executable, str(MZ / "export_session_to_case.py"), "--session", str(sess_path),
                               "--id", "x", "--known-names", str(FIX_MAIN / "known_names.txt"),
                               "--out", str(tmp / "r" / "c.jsonl")], capture_output=True, text=True, cwd=str(MZ))
        self.assertEqual(proc.returncode, EXIT_BLOCKED)
        self.assertIn("source_required", proc.stderr)

    def test_category_is_a_label_default_unlabeled(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        sess_path = tmp / "s.json"
        sess_path.write_text(json.dumps(self._long_session()), encoding="utf-8")
        out = tmp / "r" / "c.jsonl"
        proc = subprocess.run([sys.executable, str(MZ / "export_session_to_case.py"), "--session", str(sess_path),
                               "--id", "x", "--source", "cli", "--known-names", str(FIX_MAIN / "known_names.txt"),
                               "--out", str(out)], capture_output=True, text=True, cwd=str(MZ))
        self.assertEqual(proc.returncode, EXIT_OK, proc.stderr)
        self.assertEqual(json.loads(out.read_text())["category"], "unlabeled")

    def test_loose_output_dir_or_file_fails_closed(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        rdir = tmp / "redacted"
        rdir.mkdir(mode=0o700)
        os.chmod(rdir, 0o770)  # what an fsGroup relabel looks like
        proc, case, out = self._export(self._long_session(), out_dir=rdir)
        self.assertEqual(proc.returncode, EXIT_BLOCKED)
        self.assertIn("loose_permissions", proc.stderr)
        self.assertFalse(out.exists())
        os.chmod(rdir, 0o700)
        out.write_text("", encoding="utf-8")
        os.chmod(out, 0o660)
        proc, case, _ = self._export(self._long_session(), out_dir=rdir)
        self.assertEqual(proc.returncode, EXIT_BLOCKED)
        self.assertEqual(out.read_text(), "")

    def test_check_perms_reports_paths_only(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        os.chmod(tmp, 0o700)
        (tmp / "sub").mkdir(mode=0o700)
        f = tmp / "sub" / "c.jsonl"
        f.write_text("SYNTHETIC-SECRET-TEXT", encoding="utf-8")
        os.chmod(f, 0o600)
        run = lambda: subprocess.run([sys.executable, str(MZ / "export_session_to_case.py"), "--check-perms", str(tmp)],
                                     capture_output=True, text=True, cwd=str(MZ))
        ok = run()
        self.assertEqual(ok.returncode, EXIT_OK, ok.stdout)
        os.chmod(f, 0o640)
        os.chmod(tmp / "sub", 0o2770)
        bad = run()
        self.assertEqual(bad.returncode, EXIT_BLOCKED)
        self.assertEqual(json.loads(bad.stdout)["loose_paths"], 2)
        self.assertNotIn("SYNTHETIC-SECRET-TEXT", bad.stdout + bad.stderr)
        os.chmod(tmp / "sub", 0o2700)  # setgid alone is fine
        os.chmod(f, 0o600)
        self.assertEqual(run().returncode, EXIT_OK)

    def test_summarize_prints_ids_and_counts_only(self) -> None:
        proc, case, out = self._export(self._long_session())
        self.assertEqual(proc.returncode, EXIT_OK, proc.stderr)
        res = subprocess.run([sys.executable, str(MZ / "export_session_to_case.py"), "--summarize", str(out)],
                             capture_output=True, text=True, cwd=str(MZ))
        self.assertEqual(res.returncode, EXIT_OK)
        body = json.loads(res.stdout)
        self.assertEqual(body["cases"], 1)
        self.assertEqual(set(body["rows"][0]), {"id", "category", "source", "context_turns_kept",
                                                "recorded_reply_present", "redaction_counts"})
        for frag in ("owner turn", "arin turn", "running late", "Why:"):
            self.assertNotIn(frag, res.stdout)


if __name__ == "__main__":
    unittest.main()
