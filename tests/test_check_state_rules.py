import datetime as dt
import importlib.util
import pathlib
import subprocess
import sys
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("csr", ROOT / "scripts" / "check_state_rules.py")
csr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(csr)
TODAY = dt.date(2026, 10, 12)
TWO = [{"url": "a"}, {"url": "b"}]


def rule(**kw):
    r = {"id": "r", "source_type": "statute", "sources": TWO, "effective_date": "2020-01-01", "last_verified": "2026-10-01"}
    r.update(kw)
    return r


def run(*rules):
    return csr.check_doc({"rules": list(rules)}, TODAY, "t")


class Freshness(unittest.TestCase):
    def test_fixture_121_days_fails_and_120_passes(self):
        doc = yaml.safe_load((ROOT / "tests/fixtures/rules/stale-121.yaml").read_text())
        errs, _ = csr.check_doc(doc, TODAY, "fx")
        self.assertEqual(len(errs), 1)
        self.assertIn("fixture-stale-121", errs[0])
        self.assertIn("121 days", errs[0])

    def test_cli_exit_code_on_fixture(self):
        p = subprocess.run([sys.executable, str(ROOT / "scripts/check_state_rules.py"), "--today", "2026-10-12",
                            str(ROOT / "tests/fixtures/rules/stale-121.yaml")], capture_output=True, text=True)
        self.assertEqual(p.returncode, 1, p.stdout)

    def test_missing_or_bad_last_verified_fails(self):
        self.assertTrue(run(rule(last_verified=None))[0])
        self.assertTrue(run(rule(last_verified="10/01/2026"))[0])

    def test_phoenix_date_not_utc(self):
        # 2026-10-12 03:30Z is still 2026-10-11 in Phoenix (UTC-7, no DST).
        now = dt.datetime(2026, 10, 12, 3, 30, tzinfo=dt.timezone.utc)
        self.assertEqual(csr.phoenix_today(now), dt.date(2026, 10, 11))
        # July (US DST) is still UTC-7 in Phoenix.
        self.assertEqual(csr.phoenix_today(dt.datetime(2026, 7, 1, 6, 59, tzinfo=dt.timezone.utc)), dt.date(2026, 6, 30))
        # Rule verified 2026-06-13: 121 days old on Phoenix 10-12 but 120 on Phoenix 10-11.
        r = rule(last_verified="2026-06-13")
        self.assertTrue(csr.check_doc({"rules": [r]}, dt.date(2026, 10, 12), "t")[0])
        self.assertFalse(csr.check_doc({"rules": [r]}, dt.date(2026, 10, 11), "t")[0])


class Sources(unittest.TestCase):
    def test_one_source_statute_fails(self):
        self.assertIn("needs 2 sources", run(rule(sources=TWO[:1]))[0][0])

    def test_contract_form_one_source_with_caveat_passes(self):
        self.assertEqual(run(rule(source_type="standard_contract_form", sources=TWO[:1], caveat="Check your signed contract."))[0], [])

    def test_contract_form_without_caveat_fails(self):
        self.assertIn("caveat", run(rule(source_type="standard_contract_form", sources=TWO[:1]))[0][0])
        self.assertIn("caveat", run(rule(source_type="standard_contract_form", sources=TWO[:1], caveat="  "))[0][0])

    def test_contract_form_zero_sources_fails(self):
        self.assertTrue(run(rule(source_type="standard_contract_form", sources=[], caveat="x"))[0])


class EffectiveDate(unittest.TestCase):
    def test_null_effective_date_warns_only(self):
        errs, warns = run(rule(effective_date=None))
        self.assertEqual(errs, [])
        self.assertEqual(len(warns), 1)


class LiveFile(unittest.TestCase):
    def test_az_yaml_passes_on_its_verification_date(self):
        doc = yaml.safe_load((ROOT / "rules/states/AZ.yaml").read_text())
        errs, _ = csr.check_doc(doc, TODAY, "AZ")
        self.assertEqual(errs, [])


if __name__ == "__main__":
    unittest.main()
