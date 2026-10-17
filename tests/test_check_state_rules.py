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
TWO = [{"url": "https://example.invalid/a", "publisher": "Alpha"}, {"url": "https://example.invalid/b", "publisher": "Alpha"}]
FORM = {
    "url": "https://www.aaronline.com/form-feb-2026.pdf",
    "publisher": "Arizona Association of REALTORS",
    "label": "standard contract form, Feb 2026",
}


def rule(**kw):
    r = {
        "id": "r",
        "category": "statute",
        "source_type": "statute",
        "sources": TWO,
        "effective_date": "2020-01-01",
        "last_verified": "2026-10-01",
        "reminder_text": "Reminder only.",
    }
    r.update(kw)
    return r


def run(*rules):
    return csr.check_doc({"rules": list(rules)}, TODAY, "t")


def contract(**kw):
    base = rule(
        category="contract terms",
        source_type="standard_contract_form",
        source_edition="Feb 2026",
        sources=[dict(FORM)],
        reminder_text="These days apply under the standard form; check your signed contract.",
    )
    base.update(kw)
    return base


class Freshness(unittest.TestCase):
    def test_fixture_121_days_fails_and_120_passes(self):
        doc = yaml.safe_load((ROOT / "tests/fixtures/rules/stale-121.yaml").read_text())
        errs, _, passed = csr.check_doc(doc, TODAY, "fx")
        self.assertEqual(len(errs), 1)
        self.assertIn("fixture-stale-121", errs[0])
        self.assertIn("121 days", errs[0])
        self.assertIn("category=statute", errs[0])
        self.assertIn("sources=2", errs[0])
        self.assertEqual(passed, 1)

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
    def test_contract_terms_one_labeled_source_with_reminder_caveat_passes(self):
        self.assertEqual(run(contract())[0], [])
        edition_only = contract(sources=[{
            "url": "https://www.aaronline.com/form-feb-2026.pdf",
            "publisher": "Arizona Association of REALTORS",
        }])
        self.assertEqual(run(edition_only)[0], [])
        self.assertEqual(run(contract(reminder_text="Check your signed contract before you rely on this."))[0], [])

    def test_contract_terms_wrong_form_fails(self):
        errs = run(contract(sources=[{
            "url": "https://www.aaronline.com/form-aug-2024.pdf",
            "publisher": "Arizona Association of REALTORS",
            "label": "standard contract form, Aug 2024",
        }], source_edition="Aug 2024"))[0]
        self.assertIn("standard contract form, Feb 2026", errs[0])
        self.assertIn("category=contract terms", errs[0])
        self.assertIn("sources=1", errs[0])
        self.assertIn("t:r", errs[0])

    def test_contract_terms_without_reminder_caveat_fails(self):
        errs = run(contract(reminder_text="See the February 2026 form."))[0]
        self.assertIn("caveat", errs[0])
        self.assertIn("check your signed contract", errs[0])
        self.assertIn("sources=1", errs[0])
        field_only = contract(reminder_text="See the form.", caveat="Check your signed contract.")
        self.assertIn("reminder text", run(field_only)[0][0])

    def test_contract_terms_zero_sources_fails(self):
        errs = run(contract(sources=[]))[0]
        self.assertTrue(errs)
        self.assertIn("sources=0", errs[0])
        self.assertIn("t:r", errs[0])

    def test_contract_terms_non_az_publisher_fails(self):
        errs = run(contract(sources=[{
            "url": "https://example.invalid/form.pdf",
            "publisher": "National Association of REALTORS",
            "label": "standard contract form, Feb 2026",
        }]))[0]
        self.assertIn("AZ REALTORS", errs[0])

    def test_contract_terms_two_independent_sources_pass(self):
        self.assertEqual(run(contract(sources=TWO, reminder_text="No contract caveat here."))[0], [])

    def test_one_source_statute_fails(self):
        err = run(rule(sources=TWO[:1]))[0][0]
        self.assertIn("needs 2 sources", err)
        self.assertIn("category=statute", err)
        self.assertIn("sources=1", err)
        self.assertIn("t:r", err)

    def test_statute_two_independent_sources_pass(self):
        self.assertEqual(run(rule())[0], [])
        same_url = [
            {"url": "https://example.invalid/same", "publisher": "Alpha"},
            {"url": "https://example.invalid/same", "publisher": "Beta"},
        ]
        self.assertEqual(run(rule(sources=same_url))[0], [])

    def test_statute_duplicate_source_fails(self):
        dup = [dict(TWO[0]), dict(TWO[0])]
        err = run(rule(sources=dup))[0][0]
        self.assertIn("needs 2 sources", err)
        self.assertIn("independent", err)
        self.assertIn("category=statute", err)
        self.assertIn("sources=2", err)

    def test_adre_two_independent_sources_pass(self):
        self.assertEqual(run(rule(category="ADRE", source_type="ADRE rule (A.A.C.)"))[0], [])

    def test_adre_one_source_fails(self):
        err = run(rule(category="ADRE", sources=TWO[:1]))[0][0]
        self.assertIn("needs 2 sources", err)
        self.assertIn("category=ADRE", err)
        self.assertIn("sources=1", err)

    def test_adre_duplicate_source_fails(self):
        dup = [{"url": "https://azre.gov/same", "publisher": "Arizona Department of Real Estate"}] * 2
        err = run(rule(category="ADRE", sources=dup))[0][0]
        self.assertIn("independent", err)
        self.assertIn("category=ADRE", err)
        self.assertIn("sources=2", err)

    def test_missing_category_fails(self):
        for cat in (None, "", "  "):
            err = run(rule(category=cat))[0][0]
            self.assertIn("missing or unknown category", err)
            self.assertIn("category=missing", err)
            self.assertIn("sources=2", err)
            self.assertIn("t:r", err)

    def test_unknown_category_fails(self):
        err = run(rule(category="not-a-category"))[0][0]
        self.assertIn("missing or unknown category", err)
        self.assertIn("category=not-a-category", err)
        self.assertIn("sources=2", err)
        self.assertIn("t:r", err)


class EffectiveDate(unittest.TestCase):
    def test_null_effective_date_warns_only(self):
        errs, warns, _passed = run(rule(effective_date=None))
        self.assertEqual(errs, [])
        self.assertEqual(len(warns), 1)


class LiveFile(unittest.TestCase):
    def test_az_yaml_passes_on_its_verification_date(self):
        doc = yaml.safe_load((ROOT / "rules/states/AZ.yaml").read_text())
        errs, _warns, passed = csr.check_doc(doc, TODAY, "AZ")
        self.assertEqual(errs, [])
        self.assertEqual(passed, len(doc["rules"]))
        contract = [r for r in doc["rules"] if r.get("category") == "contract terms"]
        self.assertEqual(len(contract), 14)
        for r in contract:
            self.assertIn("check your signed contract", r["reminder_text"].casefold())
            self.assertEqual(len(r["sources"]), 1)

    def test_null_effective_dates_follow_the_session_law_review(self):
        doc = yaml.safe_load((ROOT / "rules/states/AZ.yaml").read_text())
        by_id = {r["id"]: r for r in doc["rules"]}
        term = by_id["az-license-term-two-years"]
        self.assertEqual(str(term["effective_date"]), "2010-07-29")
        self.assertIn("90-day", term["verification_note"])
        self.assertIn("ch. 166", term["verification_note"])
        fee = by_id["az-license-late-renewal-fee"]
        self.assertIsNone(fee["effective_date"])
        self.assertEqual(fee["status"], "drop")
        report = by_id["az-disclosure-subdivision-public-report"]
        self.assertEqual(str(report["effective_date"]), "2024-09-14")
        self.assertIn("ch. 41", report["verification_note"])
        self.assertIn("ch. 52, which does not amend", report["verification_note"])
        self.assertIn("90-day", report["verification_note"])
        self.assertNotEqual(report.get("status"), "drop")


if __name__ == "__main__":
    unittest.main()
