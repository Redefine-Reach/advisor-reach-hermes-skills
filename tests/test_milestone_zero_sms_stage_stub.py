"""RED-585: sms_stage eval stub for the milestone-zero harness. Synthetic data only.

Proves: send is always refused; stage returns the production-shaped read-back from the installed
script's own gates; no network or process call can happen while the stub runs; nothing reaches
the harness's outbound recorder; the eval home enables only the stub (never the real
arin-sms-stage plugin) and drops terminal/code execution from the CLI toolsets.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
MZ = ROOT / "evals" / "milestone-zero"
STUB = MZ / "sms_stage_stub" / "__init__.py"
FIXTURE_SCRIPT = ROOT / "tests" / "fixtures" / "sms-stage-stub" / "sms_send_confirmed.py"
sys.path.insert(0, str(MZ))

GOOD = {
    "action": "stage", "approver": "+15550100099", "dest": "+15550100901",
    "body": "Hi Jordan, it's Morgan. Just saying hi, and I'm here if you need anything.",
    "why": "Jordan closed with you last March and hasn't heard from you since.",
    "source_kind": "owner_text",
}


def load_stub():
    spec = importlib.util.spec_from_file_location("sms_stage_evalstub_test", STUB)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class StubToolTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="stub-home-"))
        scripts = self.home / "skills" / "sms-send-confirmed" / "scripts"
        scripts.mkdir(parents=True)
        shutil.copyfile(FIXTURE_SCRIPT, scripts / "sms_send_confirmed.py")
        self.log = self.home / "stub-calls.jsonl"
        self.env = mock.patch.dict(os.environ, {"HERMES_HOME": str(self.home), "ARIN_EVAL_SMS_STAGE_STUB_LOG": str(self.log)})
        self.env.start()
        self.stub = load_stub()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.home, ignore_errors=True)

    def calls(self):
        return [json.loads(x) for x in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_schema_matches_production_shape(self):
        self.assertEqual(self.stub.SCHEMA["name"], "sms_stage")
        self.assertEqual(self.stub.SCHEMA["parameters"]["properties"]["action"]["enum"], ["stage", "cancel", "send"])
        registered = []
        self.stub.register(mock.Mock(register_tool=lambda **kw: registered.append(kw)))
        self.assertEqual([(r["name"], r["toolset"]) for r in registered], [("sms_stage", "smsstage")])

    def test_send_is_always_refused(self):
        for args in ({"action": "send", "draft_id": "0123456789abcdef"}, {"action": "send"}, {"action": "SEND", "draft_id": "x"}):
            out = json.loads(self.stub.run(args))
            self.assertFalse(out["ok"])
            self.assertEqual(out["outcome"], "eval_stub_no_send")
        # even right after a successful stage of a real-looking draft
        staged = json.loads(json.loads(self.stub.run(GOOD))["result"])
        out = json.loads(self.stub.run({"action": "send", "draft_id": staged["draft_id"]}))
        self.assertEqual(out["outcome"], "eval_stub_no_send")

    def test_stage_returns_production_readback(self):
        out = json.loads(self.stub.run(GOOD))
        self.assertTrue(out["ok"])
        payload = json.loads(out["result"])
        self.assertEqual(payload["outcome"], "staged")
        self.assertFalse(payload["provider_called"])
        self.assertTrue(payload["eval_stub"])
        lines = payload["attestation"].splitlines()
        self.assertTrue(lines[0].startswith("You're about to send this text"))
        self.assertTrue(any(line.startswith("Why: Jordan closed") for line in lines))
        self.assertIn("Reply SEND to send, DROP to discard.", lines)

    def test_stage_uses_script_gates(self):
        out = json.loads(self.stub.run({**GOOD, "why": "Text Jordan a hello"}))
        self.assertFalse(out["ok"])
        self.assertEqual(json.loads(out["result"])["outcome"], "refused_why_circular")
        out = json.loads(self.stub.run({**GOOD, "why": ""}))
        self.assertEqual(out["outcome"], "refused_no_why")

    def test_no_network_or_process_during_stub(self):
        seen = []
        with self.stub._sealed():
            for call in (lambda: socket.create_connection(("api.telnyx.com", 443)),
                         self._connect_raw,
                         lambda: subprocess.Popen(["true"])):
                with self.assertRaises(RuntimeError):
                    call()
                seen.append(1)
        self.assertEqual(len(seen), 3)
        # restored afterwards
        self.assertIsNot(socket.create_connection, self.stub._no_net)
        self.assertIsNot(subprocess.Popen, self.stub._no_net)

    @staticmethod
    def _connect_raw():
        sock = socket.socket()
        try:
            sock.connect(("127.0.0.1", 9))
        finally:
            sock.close()

    def test_script_send_path_cannot_run_inside_stub(self):
        # If anything inside the stub reached the script's send(), the seal makes it fail closed.
        mod = self.stub._script()
        with self.stub._sealed():
            with self.assertRaises(RuntimeError):
                mod.send()

    def test_incompatible_script_fails_closed(self):
        (self.home / "skills" / "sms-send-confirmed" / "scripts" / "sms_send_confirmed.py").write_text("def one_line(x):\n    return x\n")
        out = json.loads(self.stub.run(GOOD))
        self.assertFalse(out["ok"])
        self.assertIn("Nothing was sent", out["say"])
        self.assertEqual(self.calls()[-1]["outcome"], "stub_script_incompatible")

    def test_no_outbound_reaches_recorder(self):
        from outbound_stub import OutboundRecorder, start_http_stub
        rec = OutboundRecorder()
        server, base = start_http_stub(rec)
        try:
            with mock.patch.dict(os.environ, {"TELNYX_SMS_API_BASE": base}):
                self.stub.run(GOOD)
                self.stub.run({"action": "send", "draft_id": "0123456789abcdef"})
                self.stub.run({"action": "cancel", "draft_id": "0123456789abcdef"})
            self.assertEqual(rec.snapshot(), [])
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual([c["action"] for c in self.calls()], ["stage", "send", "cancel"])
        self.assertEqual(self.calls()[1]["outcome"], "eval_stub_no_send")


class EvalHomeTests(unittest.TestCase):
    def setUp(self):
        self.src = Path(tempfile.mkdtemp(prefix="stub-src-home-"))
        (self.src / "config.yaml").write_text(
            "model: {provider: custom, default: test-model}\n"
            "plugins: {enabled: [arin-sms-stage, platforms/telnyx_sms], disabled: []}\n"
            "platform_toolsets: {telnyx_sms: [skills, smsstage]}\n")
        real = self.src / "plugins" / "arin-sms-stage"
        real.mkdir(parents=True)
        (real / "plugin.yaml").write_text("name: arin-sms-stage\n")
        (self.src / "skills" / "sms-send-confirmed").mkdir(parents=True)
        (self.src / "skills" / "sms-send-confirmed" / "SKILL.md").write_text("# test\n")

    def tearDown(self):
        shutil.rmtree(self.src, ignore_errors=True)

    def build(self, flag):
        import live_session
        with mock.patch.dict(os.environ, {"ARIN_EVAL_SMS_STAGE_STUB": flag}):
            return live_session, live_session.make_eval_hermes_home(self.src)

    def test_stub_off_by_default(self):
        ls, home = self.build("")
        try:
            self.assertFalse((home / "plugins").exists())
            self.assertNotIn("plugins:", (home / "config.yaml").read_text())
        finally:
            ls.shred_tree(home)

    def test_stub_on_enables_only_stub(self):
        import yaml
        ls, home = self.build("1")
        try:
            self.assertEqual(sorted(p.name for p in (home / "plugins").iterdir()), ["arin-sms-stage-evalstub"])
            cfg = yaml.safe_load((home / "config.yaml").read_text())
            self.assertEqual(cfg["plugins"]["enabled"], ["arin-sms-stage-evalstub"])
            cli = cfg["platform_toolsets"]["cli"]
            self.assertIn("smsstage", cli)
            for banned in ("terminal", "code_execution", "hermes-cli"):
                self.assertNotIn(banned, cli)
            self.assertEqual(cfg["model"]["default"], "test-model")
            for p in (home / "plugins").rglob("*"):
                self.assertEqual(p.stat().st_mode & 0o077, 0, p)
        finally:
            ls.shred_tree(home)


if __name__ == "__main__":
    unittest.main()
