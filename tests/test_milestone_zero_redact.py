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
                    "--source",
                    "cli",
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
                    "--source",
                    "cli",
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
            "--known-names {known} --rules {rules} --forgotten {forgotten} --owner-name Alex --source cli"
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
                ],
                capture_output=True,
                text=True,
                cwd=str(MZ),
            )
            # Over-dropping/over-redacting a control is the safe failure (Vault, Oct 19): no
            # benign holds, so clean controls need not pass. Leaks must still be zero.
            self.assertIn(proc.returncode, (0, 2), proc.stdout + proc.stderr)
            self.assertIn("LEAKS TOTAL: 0", proc.stdout)


    # Over-dropped / over-redacted controls are pinned exactly: a NEW one fails CI, and one that
    # disappears also fails (so it gets reported and the pin updated deliberately).
    # Each entry: set -> (over_redacted, over_excluded, ids). Reasons per id are in the comments.
    PINNED_CONTROLS = {
        "main": (1, 4, {
            "s130",  # (a) sentence-start "Chapter" is not in common_words.txt -> redacted as a name
            "s132",  # "therapy dog" hold removed (Vault 029b63a): drops as health
            "s133",  # "custody of the ... keys" hold removed: drops as legal
            "s134",  # "chapter 7 of the" hold removed: drops as legal
            "s136",  # "hospital-district" hold removed: drops as health
        }),
        "heldout": (0, 0, set()),
        "heldout2": (5, 0, {
            "u033",  # (a) sentence-start "Grace" (keep-list word, Vault N3) -> redacted as a name
            "u034",  # (a) sentence-start "Bill" (keep-list word, Vault N3) -> redacted as a name
            "u035",  # "Hunter Douglas" hold removed: brand redacted as a name
            "u036",  # "Mason jar" hold removed: "Mason" redacted as a name
            "u037",  # (a) sentence-start "Summer" (keep-list word, Vault N3) -> redacted as a name
        }),
    }

    def test_pinned_over_redacted_and_over_dropped_controls(self) -> None:
        import re as _re
        cmd = (
            "python3 export_session_to_case.py --session {in} --redacted-text-out {out} "
            "--known-names {known} --rules {rules} --forgotten {forgotten} --owner-name Alex --source cli"
        )
        dirs = {"main": FIX_MAIN, "heldout": MZ / "fixtures" / "fake_sessions_heldout",
                "heldout2": MZ / "fixtures" / "fake_sessions_heldout2"}
        for label, (want_red, want_exc, want_ids) in self.PINNED_CONTROLS.items():
            proc = subprocess.run(
                [sys.executable, str(MZ / "check_leaks.py"), "--label", label, "--cwd", str(MZ),
                 "--sessions", str(dirs[label]), "--cmd", cmd, "--strict-drop"],
                capture_output=True, text=True, cwd=str(MZ),
            )
            m = _re.search(r"over-redacted=(\d+) .*over-excluded=(\d+)", proc.stdout)
            self.assertIsNotNone(m, proc.stdout + proc.stderr)
            ids_m = _re.search(r"control ids: (\S+)", proc.stdout)
            got_ids = set(ids_m.group(1).split(",")) if ids_m else set()
            new, gone = sorted(got_ids - want_ids), sorted(want_ids - got_ids)
            self.assertEqual((new, gone), ([], []), f"{label}: new over-drop/over-redaction {new}; no longer over {gone}")
            self.assertEqual((int(m.group(1)), int(m.group(2))), (want_red, want_exc), label)


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


class ExportVaultRound2(_ExportHelpers, unittest.TestCase):
    """Vault review of 63bf28a (N1-N3, T1, G1, P1/P2, D1). Synthetic names and numbers only."""

    def _blob(self, case: dict) -> str:
        return json.dumps(case)

    def test_n1_text_name_word_maps_single_name_across_turns(self) -> None:
        for phrasing in ("text Rosalind about the walkthrough", "text Rosalind tomorrow morning", "text rosalind about it"):
            sess = {"messages": [_msg("user", phrasing), _msg("assistant", "Drafted. Reply SEND to send."),
                                 _msg("user", "any update?"), _msg("assistant", "Rosalind confirmed Friday.")]}
            proc, case, _ = self._export(sess)
            self.assertEqual(proc.returncode, EXIT_OK, proc.stderr)
            self.assertNotIn("rosalind", self._blob(case).lower(), phrasing)
            # the word after the name survives (only the name is mapped)
            ctx_owner = case["input"]["context_turns"][0]["content"]
            self.assertRegex(ctx_owner, r"^text CLIENT_\d+ (about|tomorrow)")
            self.assertRegex(case["fixture"]["assistant_text"], r"^CLIENT_\d+ confirmed Friday\.$")

    def test_n1_surname_tokens_mapped_separately(self) -> None:
        sess = {"messages": [_msg("user", "text Ottoline Varga about the offer"), _msg("assistant", "Drafted."),
                             _msg("user", "and?"), _msg("assistant", "Varga said yes. Ottoline will sign tonight.")]}
        proc, case, _ = self._export(sess)
        self.assertEqual(proc.returncode, EXIT_OK, proc.stderr)
        blob = self._blob(case).lower()
        self.assertNotIn("ottoline", blob)
        self.assertNotIn("varga", blob)

    def test_n2_sentence_reply_and_why_start_names(self) -> None:
        sess = {"messages": [_msg("user", "draft the follow up for the condo"),
                             _msg("assistant", "Draft: Checking in on the condo.\nWhy: Thaddeus asked for an update Tuesday.\nReply SEND to send."),
                             _msg("user", "who called?"), _msg("assistant", "Percival called back. Leopoldine's offer is in.")]}
        proc, case, _ = self._export(sess)
        self.assertEqual(proc.returncode, EXIT_OK, proc.stderr)
        blob = self._blob(case)
        for name in ("Thaddeus", "Percival", "Leopoldine"):
            self.assertNotIn(name, blob)
        self.assertIn("Why: CLIENT_", blob)

    def test_n2_ordinary_sentence_starters_kept(self) -> None:
        sess = {"messages": [_msg("user", "status?"),
                             _msg("assistant", "Closing is Friday. Inspection came back clean. Everything is set. Showing confirmed for 4.")]}
        proc, case, _ = self._export(sess)
        self.assertEqual(proc.returncode, EXIT_OK, proc.stderr)
        self.assertEqual(case["fixture"]["assistant_text"],
                         "Closing is Friday. Inspection came back clean. Everything is set. Showing confirmed for 4.")

    def test_n3_no_builtin_keep_list_only_owner_name(self) -> None:
        text = "Alex said Frank and Grace like it. Bill Hunter, Summer and Mason too. Douglas called."
        sess = {"messages": [_msg("user", "who liked the house?"), _msg("assistant", text)]}
        proc, case, _ = self._export(sess, ["--owner-name", "David"])
        self.assertEqual(proc.returncode, EXIT_OK, proc.stderr)
        reply = case["fixture"]["assistant_text"]
        for name in ("Alex", "Frank", "Grace", "Bill", "Hunter", "Summer", "Mason", "Douglas"):
            self.assertNotRegex(reply, rf"\b{name}\b", name)
        proc, case, _ = self._export({"messages": [_msg("user", "David here, text Frank about it"),
                                                   _msg("assistant", "Done, David.")]}, ["--owner-name", "David"])
        self.assertIn("David", self._blob(case))
        self.assertNotIn("Frank", self._blob(case))
        # no fixture-fitted benign holds: brand phrases that look like names are redacted (safe side)
        proc, case, _ = self._export({"messages": [_msg("user", "Hunter Douglas blinds stay; order Mason jar centerpieces"),
                                                   _msg("assistant", "Noted.")]}, ["--owner-name", "David"])
        self.assertEqual(proc.returncode, EXIT_OK, proc.stderr)
        self.assertNotIn("Hunter", case["input"]["owner_text"])

    def test_t1_top_level_tool_calls_dropped(self) -> None:
        sess = self._long_session()
        sess["tool_calls"] = [{"name": "contacts_lookup", "arguments": {"query": "Zoltan Fakeperson"}}]
        proc, case, _ = self._export(sess)
        self.assertEqual(proc.returncode, EXIT_OK, proc.stderr)
        self.assertEqual(case["fixture"]["tool_calls"], [])
        self.assertEqual(case["export_meta"]["tool_calls_dropped"], 1)
        self.assertNotIn("Zoltan", self._blob(case))

    def _run(self, args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(MZ / "export_session_to_case.py"), *args],
                              capture_output=True, text=True, cwd=str(MZ))

    def _sess_file(self, base: Path, msgs: list[dict]) -> Path:
        p = base / "s.json"
        p.write_text(json.dumps({"messages": msgs}), encoding="utf-8")
        return p

    def test_g1_redacted_text_out_has_same_gates_and_no_tool_text(self) -> None:
        base = Path(tempfile.mkdtemp()); os.chmod(base, 0o700)
        sess = self._sess_file(base, [_msg("user", "call me back"), _msg("tool", "TOOLSECRETWORD output"),
                                      _msg("assistant", "Ok.")])
        known = ["--known-names", str(FIX_MAIN / "known_names.txt")]
        out = base / "o" / "t.txt"
        r = self._run(["--session", str(sess), "--redacted-text-out", str(out), "--source", "cli"])
        self.assertEqual(r.returncode, EXIT_BLOCKED); self.assertIn("known_names_required", r.stderr)
        r = self._run(["--session", str(sess), "--redacted-text-out", str(out), *known])
        self.assertEqual(r.returncode, EXIT_BLOCKED); self.assertIn("source_required", r.stderr)
        r = self._run(["--session", str(sess), "--redacted-text-out", str(MZ / "leak-test.txt"), *known, "--source", "cli"])
        self.assertEqual(r.returncode, EXIT_BLOCKED); self.assertIn("inside_git_worktree", r.stderr)
        self.assertFalse((MZ / "leak-test.txt").exists())
        loose = base / "loose"; loose.mkdir(); os.chmod(loose, 0o770)
        r = self._run(["--session", str(sess), "--redacted-text-out", str(loose / "t.txt"), *known, "--source", "cli"])
        self.assertEqual(r.returncode, EXIT_BLOCKED); self.assertFalse((loose / "t.txt").exists())
        r = self._run(["--session", str(sess), "--redacted-text-out", str(out), *known, "--source", "cli"])
        self.assertEqual(r.returncode, EXIT_OK, r.stderr)
        self.assertNotIn("TOOLSECRETWORD", out.read_text())
        self.assertEqual(out.stat().st_mode & 0o777, 0o600)

    def test_g1_fixture_check_with_out_keeps_git_perms_source_gates(self) -> None:
        fixture = FIX_MAIN / "s001.txt"
        base = Path(tempfile.mkdtemp()); os.chmod(base, 0o700)
        r = self._run(["--session", str(fixture), "--fixture-check", "--id", "f1", "--out", str(MZ / "x.jsonl")])
        self.assertEqual(r.returncode, EXIT_BLOCKED)
        r = self._run(["--session", str(fixture), "--fixture-check", "--id", "f1", "--source", "cli",
                       "--out", str(MZ / "x.jsonl")])
        self.assertEqual(r.returncode, EXIT_BLOCKED); self.assertIn("inside_git_worktree", r.stderr)
        self.assertFalse((MZ / "x.jsonl").exists())
        sess = self._sess_file(base, [_msg("user", "hi"), _msg("assistant", "Ok.")])
        r = self._run(["--session", str(sess), "--fixture-check", "--id", "f1", "--source", "cli",
                       "--out", str(base / "o" / "c.jsonl")])
        self.assertEqual(r.returncode, EXIT_BLOCKED); self.assertIn("fixture_check_outside_fixtures", r.stderr)
        loose = base / "loose"; loose.mkdir(); os.chmod(loose, 0o770)
        r = self._run(["--session", str(fixture), "--fixture-check", "--id", "f1", "--source", "cli",
                       "--out", str(loose / "c.jsonl")])
        self.assertEqual(r.returncode, EXIT_BLOCKED); self.assertFalse((loose / "c.jsonl").exists())

    def test_p1_p2_manifest_dir_and_file_checked_before_any_write(self) -> None:
        base = Path(tempfile.mkdtemp()); os.chmod(base, 0o700)
        red = base / "redacted"; red.mkdir(mode=0o700)
        mdir = red / "manifests"; mdir.mkdir(); os.chmod(mdir, 0o2770)
        sess = self._sess_file(base, [_msg("user", "hi"), _msg("assistant", "Ok.")])
        common = ["--session", str(sess), "--id", "p1", "--source", "cli",
                  "--known-names", str(FIX_MAIN / "known_names.txt"), "--out", str(red / "c.jsonl")]
        r = self._run([*common, "--manifest", str(mdir / "p1.json")])
        self.assertEqual(r.returncode, EXIT_BLOCKED); self.assertIn("loose_permissions", r.stderr)
        self.assertFalse((red / "c.jsonl").exists())
        os.chmod(mdir, 0o700)
        m = mdir / "p1.json"; m.write_text("{}"); os.chmod(m, 0o660)
        r = self._run([*common, "--manifest", str(m)])
        self.assertEqual(r.returncode, EXIT_BLOCKED)
        self.assertFalse((red / "c.jsonl").exists())  # exit 1 = no output, nothing appended
        os.chmod(m, 0o600)
        r = self._run([*common, "--manifest", str(m)])
        self.assertEqual(r.returncode, EXIT_OK, r.stderr)

    def test_do_not_keep_rule_naming_a_person_drops_session(self) -> None:
        base = Path(tempfile.mkdtemp()); os.chmod(base, 0o700)
        rules = base / "rules.json"; rules.write_text(json.dumps({"do_not_keep": ["Wexford morning calls"]}))
        sess = self._sess_file(base, [_msg("user", "Wexford is best reached by phone"), _msg("assistant", "Ok.")])
        r = self._run(["--session", str(sess), "--id", "d1", "--source", "cli", "--rules", str(rules),
                       "--known-names", str(FIX_MAIN / "known_names.txt"), "--out", str(base / "o" / "c.jsonl")])
        self.assertEqual(r.returncode, EXIT_EXCLUDED, r.stderr)
        self.assertFalse((base / "o" / "c.jsonl").exists())

    def test_d1_box_export_shred_block_removes_names_even_with_subdirs(self) -> None:
        doc = (MZ / "BOX-EXPORT.md").read_text(encoding="utf-8")
        self.assertNotIn("/tmp/session-raw", doc)
        start = doc.index("# Each step runs even if an earlier one fails")
        block = doc[start: doc.index("```", start)]
        base = Path(tempfile.mkdtemp()); os.chmod(base, 0o700)
        d = base / "run"; (d / "raw-input" / "sub").mkdir(parents=True); (d / "redacted").mkdir()
        (d / "raw-input" / "a.json").write_text("x"); (d / "raw-input" / "sub" / "b.json").write_text("x")
        (d / "names.txt").write_text("x"); x = base / "exporter"; x.mkdir(); (x / "e.py").write_text("x")
        subprocess.run(["bash", "-c", block], env={**os.environ, "D": str(d), "X": str(x)}, capture_output=True, check=False)
        self.assertEqual(sorted(p.name for p in d.iterdir()), ["redacted"])
        self.assertFalse(x.exists())


class NoFixtureFitting(_ExportHelpers, unittest.TestCase):
    """Vault re-test of 029b63a: no fixture names or benign holds that hide health/legal words."""

    def test_guard_has_no_fixture_names(self) -> None:
        src = (MZ / "conservative_guard.py").read_text(encoding="utf-8").lower()
        for word in ("fakerton", "fakeman", "samplesworth", "placeholder"):
            self.assertNotIn(word, src)

    def test_no_benign_holds_for_health_or_legal_words(self) -> None:
        for path in (MZ / "conservative_guard.py", MZ / "redact.py"):
            src = path.read_text(encoding="utf-8").lower()
            for hold in ("custody of the", "chapter 7 of the", "therapy dog", "medical office lease",
                         "office building", "hospital-district", "hunter douglas", "mason jar"):
                self.assertNotIn(hold, src, (path.name, hold))

    def test_custody_and_chapter_7_wording_now_drops(self) -> None:
        for text in ("custody of the kids and the house keys are with his ex",
                     "they are filing chapter 7 of the code next month",
                     "bring the therapy dog to the showing",
                     "the medical office lease renews in May"):
            proc, case, _ = self._export({"messages": [_msg("user", text), _msg("assistant", "Ok.")]},
                                         ["--owner-name", "David"])
            self.assertEqual(proc.returncode, EXIT_EXCLUDED, (text, proc.stderr))
            self.assertIsNone(case)


class NameShapesRound3(_ExportHelpers, unittest.TestCase):
    """Vault re-test of 029b63a, items 3-4. Synthetic names only."""

    def _reply(self, text: str, owner: str = "status?") -> dict:
        proc, case, _ = self._export({"messages": [_msg("user", owner), _msg("assistant", text)]}, ["--owner-name", "David"])
        self.assertEqual(proc.returncode, EXIT_OK, proc.stderr)
        return case

    def test_lowercase_surname_after_text(self) -> None:
        sess = {"messages": [_msg("user", "text bartholomew grindle about the deed"), _msg("assistant", "Drafted."),
                             _msg("user", "?"), _msg("assistant", "Grindle replied, Bartholomew is in.")]}
        proc, case, _ = self._export(sess, ["--owner-name", "David"])
        self.assertEqual(proc.returncode, EXIT_OK, proc.stderr)
        blob = json.dumps(case).lower()
        self.assertNotIn("grindle", blob)
        self.assertNotIn("bartholomew", blob)
        self.assertIn("about the deed", blob)
        case = self._reply("Ok.", owner="text dana im running late")
        self.assertIn("im running late", case["input"]["owner_text"])

    def test_sentence_start_comma_colon_adverb_alone_and_list(self) -> None:
        for text, name in (("Percival, can you send the disclosures?", "Percival"),
                           ("Cornelius: fine with Friday.", "Cornelius"),
                           ("Thaddeus definitely called back.", "Thaddeus"),
                           ("Ignatius probably wants the condo.", "Ignatius"),
                           ("Checked the list.\nOctavia\nThat's the only one.", "Octavia"),
                           ("Grace, Bill, and Ann are coming to the open house.", "Grace")):
            case = self._reply(text)
            self.assertNotIn(name, json.dumps(case), text)

    def test_ordinary_starters_still_kept(self) -> None:
        text = "Closing is Friday. Sure, I can. Thanks, noted. Done: staged the draft."
        self.assertEqual(self._reply(text)["fixture"]["assistant_text"], text)

    def test_known_names_any_case_anywhere(self) -> None:
        # known_names.txt has "Zelda Clientfake": every case and position is a name.
        for text in ("ZELDA, call me.", "zelda probably wants it", "Thanks.\nzelda\n", "Spoke to clientfake: fine."):
            case = self._reply(text)
            self.assertNotIn("zelda", json.dumps(case).lower(), text)
            self.assertNotIn("clientfake", json.dumps(case).lower(), text)


class WeekdayNamedPerson(_ExportHelpers, unittest.TestCase):
    """Vault re-test of b984cba (c): no "text <weekday>" hold. Synthetic names only."""

    def test_text_weekday_surname_is_a_person_everywhere(self) -> None:
        sess = {"messages": [_msg("user", "text Sunday Quillfeather that the offer is in"), _msg("assistant", "Drafted."),
                             _msg("user", "?"), _msg("assistant", "Sunday confirmed. Quillfeather signed.")]}
        proc, case, _ = self._export(sess, ["--owner-name", "David"])
        self.assertEqual(proc.returncode, EXIT_OK, proc.stderr)
        blob = json.dumps(case)
        self.assertNotIn("Sunday", blob)
        self.assertNotIn("Quillfeather", blob)
        self.assertIn("that the offer is in", blob)

    def test_weekday_dates_still_kept(self) -> None:
        proc, case, _ = self._export({"messages": [_msg("user", "see Sunday about the walkthrough, text Monday morning"),
                                                   _msg("assistant", "Ok.")]}, ["--owner-name", "David"])
        self.assertEqual(proc.returncode, EXIT_OK, proc.stderr)
        self.assertIn("see Sunday about the walkthrough", case["input"]["owner_text"])

    def test_text_weekday_hold_cannot_hide_legal_word(self) -> None:
        proc, _, _ = self._export({"messages": [_msg("user", "text Mon re custody papers"), _msg("assistant", "Ok.")]},
                                  ["--owner-name", "David"])
        self.assertNotEqual(proc.returncode, EXIT_OK)


class SentenceStartNonDictionary(_ExportHelpers, unittest.TestCase):
    """Vault re-test of b984cba (a): a capitalized non-dictionary word at a sentence, line or
    "Why:" start is a name whatever follows. Synthetic names only (unseen by the probes)."""

    def _reply(self, text: str) -> dict:
        proc, case, _ = self._export({"messages": [_msg("user", "status?"), _msg("assistant", text)]},
                                     ["--owner-name", "David"])
        self.assertEqual(proc.returncode, EXIT_OK, proc.stderr)
        return case

    def test_em_dash_and_should_emoji_re(self) -> None:
        for text, name in (("Wilhelmina\u2014the buyer\u2014wants Friday.", "Wilhelmina"),
                           ("Lysander and his wife liked the patio.", "Lysander"),
                           ("Wilhelmina and Lysander both signed.", "Lysander"),
                           ("Peregrine \U0001F44D", "Peregrine"),
                           ("Re: Wilhelmina \u2014 counter is in", "Wilhelmina"),
                           ("Lysander should hear back by noon.", "Lysander"),
                           ("Why: Peregrine wants the condo.", "Peregrine")):
            case = self._reply(text)
            self.assertNotIn(name, json.dumps(case, ensure_ascii=False), text)

    def test_contractions_and_ordinary_starters_kept(self) -> None:
        text = ("Don't worry. Here's the draft. Let's go. Isn't it great? Won't take long. "
                "Booked the tour. Hope you're well. Wanted to confirm.")
        self.assertEqual(self._reply(text)["fixture"]["assistant_text"], text)

    def test_dictionary_word_shape_layer_still_applies(self) -> None:
        # "Hope" is ordinary English, but "<Word> asked" still reads as a person (old layer).
        case = self._reply("Hope asked about the HOA fee.")
        self.assertNotIn("Hope", json.dumps(case))


class AllCapsNonDictionary(_ExportHelpers, unittest.TestCase):
    """Vault re-test of b984cba (b): unknown ALL-CAPS names are redacted. Synthetic only."""

    def _reply(self, text: str) -> dict:
        proc, case, _ = self._export({"messages": [_msg("user", "status?"), _msg("assistant", text)]},
                                     ["--owner-name", "David"])
        self.assertEqual(proc.returncode, EXIT_OK, proc.stderr)
        return case

    def test_unknown_all_caps_name_redacted(self) -> None:
        for text, name in (("PEREGRINE CALLED about the patio.", "PEREGRINE"),
                           ("Spoke to LYSANDER, fine with Friday.", "LYSANDER")):
            self.assertNotIn(name, json.dumps(self._reply(text)), text)

    def test_acronyms_shouting_and_placeholders_kept(self) -> None:
        text = "DON'T sign yet. FYI the MLS and HOA docs are in. Reply SEND to send. THANKS SO MUCH! ASAP."
        self.assertEqual(self._reply(text)["fixture"]["assistant_text"], text)
        case = self._reply("Call 602-555-0142 OK")
        self.assertIn("[PHONE ***0142] OK", case["fixture"]["assistant_text"])


class VaultDf95Followups(_ExportHelpers, unittest.TestCase):
    """Vault df95508 non-blocking follow-ups (1)-(4). Synthetic data only."""

    LINT = MZ.parents[1] / ".github" / "workflows" / "lint.yml"

    def _reply(self, text: str) -> dict:
        proc, case, _ = self._export({"messages": [_msg("user", "status?"), _msg("assistant", text)]},
                                     ["--owner-name", "David"])
        self.assertEqual(proc.returncode, EXIT_OK, proc.stderr)
        return case

    # (1) lint.yml's leak step passes --source cli and pins the same ids as the unittest gate.
    def test_lint_leak_step_has_source_and_matching_pins(self) -> None:
        import re as _re
        text = self.LINT.read_text()
        steps = _re.findall(r"check_leaks\.py --label (\w+).*?--expect-over-ids '([^']*)' \\\n\s+--cmd '([^']+)'", text)
        self.assertEqual(sorted(s[0] for s in steps), ["heldout", "heldout2", "main"])
        for label, ids, cmd in steps:
            self.assertIn("--source cli", cmd, label)
            want = CheckLeaksCI.PINNED_CONTROLS[label][2]
            self.assertEqual(set(x for x in ids.split(",") if x), want, label)

    # (2) any redactor crash or timeout fails check_leaks (exit 4), it is not just an exclusion.
    def _check(self, cmd: str, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(MZ / "check_leaks.py"), "--label", "t", "--cwd", str(MZ),
                               "--sessions", str(MZ / "fixtures" / "fake_sessions_heldout"), "--cmd", cmd, *extra],
                              capture_output=True, text=True, cwd=str(MZ))

    def test_check_leaks_crash_fails(self) -> None:
        proc = self._check(f"{sys.executable} -c \"raise SystemExit(__import__('sys').exit(70))\"")
        self.assertEqual(proc.returncode, 4, proc.stdout)
        self.assertIn("CRASHES:", proc.stdout)
        proc = self._check(f"{sys.executable} -c \"raise RuntimeError('boom')\"")
        self.assertEqual(proc.returncode, 4, proc.stdout)

    def test_check_leaks_timeout_fails(self) -> None:
        proc = self._check(f"{sys.executable} -c \"import time; time.sleep(5)\"", "--timeout", "0.2")
        self.assertEqual(proc.returncode, 4, proc.stdout)

    def test_check_leaks_clean_drop_exit_is_not_a_crash(self) -> None:
        # exit 2 (dropped) from the redactor is an exclusion, not a crash.
        proc = self._check(f"{sys.executable} -c \"raise SystemExit(2)\"")
        self.assertNotIn("CRASHES:", proc.stdout)
        self.assertNotEqual(proc.returncode, 4)

    def test_expect_over_ids_mismatch_fails(self) -> None:
        cmd = ("python3 export_session_to_case.py --session {in} --redacted-text-out {out} --known-names {known} "
               "--rules {rules} --forgotten {forgotten} --owner-name Alex --source cli")
        ok = self._check(cmd, "--strict-drop", "--fail-on-overredaction", "--expect-over-ids", "")
        self.assertEqual(ok.returncode, 0, ok.stdout)
        bad = self._check(cmd, "--strict-drop", "--fail-on-overredaction", "--expect-over-ids", "zz999")
        self.assertEqual(bad.returncode, 2, bad.stdout)
        self.assertIn("gone=zz999", bad.stdout)

    # (3) non-ASCII and Mc/Mac names mid-sentence (and at a sentence start).
    def test_non_ascii_and_mc_mac_names(self) -> None:
        for text, name in (("I spoke with Zo\u00eb about the patio.", "Zo\u00eb"),
                           ("Send it to Siobh\u00e1n and the lender.", "Siobh\u00e1n"),
                           ("We met \u0141ukasz at the condo.", "\u0141ukasz"),
                           ("The agent for McAllister countered.", "McAllister"),
                           ("Ask MacKenzie's lender for the letter.", "MacKenzie"),
                           ("Zo\u00eb wants Friday.", "Zo\u00eb")):
            self.assertNotIn(name, json.dumps(self._reply(text), ensure_ascii=False), text)

    def test_lowercase_non_ascii_words_kept(self) -> None:
        text = "The cr\u00e8me-colored trim looks great, na\u00efve pricing aside."
        self.assertEqual(self._reply(text)["fixture"]["assistant_text"], text)

    # (4) "let" is not on the starter list the do-not-keep rule check reads; "Let's" still kept.
    def test_let_off_starter_list_and_lets_kept(self) -> None:
        import redact as _r
        self.assertNotIn("let", _r._COMMON_STARTERS)
        self.assertTrue(_r._rule_name_hit("Let mentioned on Friday", "Let morning calls"))
        self.assertEqual(self._reply("Let's go. Here's the draft.")["fixture"]["assistant_text"],
                         "Let's go. Here's the draft.")
