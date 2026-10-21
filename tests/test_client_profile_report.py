"""Synthetic, offline regressions for the client-profile report and no-match reply."""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4


SCRIPT = Path(__file__).resolve().parents[1] / "skills/client-profile/scripts/cp.py"
SPEC = importlib.util.spec_from_file_location("client_profile", SCRIPT)
cp = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cp)


class ClientProfileReportTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.gettempdir()) / f"cp-report-{uuid4().hex}"
        self.root.mkdir()
        self.addCleanup(shutil.rmtree, self.root)
        self.client = self.root / "c0123456789abcdef"
        self.client.mkdir()
        self.write_json(self.client / "intake.json", {
            "name": "Avery Quindle", "city": "Exampleville", "type": "buyer",
        })
        # Any accidental request fails immediately; these fixtures never use a provider.
        request = patch.object(cp.urllib.request, "urlopen", side_effect=AssertionError("network forbidden"))
        request.start()
        self.addCleanup(request.stop)

    @staticmethod
    def write_json(path, value):
        path.write_text(json.dumps(value), encoding="utf-8")

    def brief(self, count):
        sources = [{
            "evidence_id": f"ev_{index:08x}",
            "title": f"Synthetic source {index}",
            "url": f"https://sources.example.test/profile/{index}",
        } for index in range(1, count + 1)]
        return {
            "appointment_playbook": {},
            "communication_style": {},
            "verified_facts": [{
                "text": "Synthetic public evidence.",
                "evidence_ids": [item["evidence_id"] for item in sources],
            }],
            "appendix": {"sources": sources},
        }

    def render(self, brief, initial_count):
        self.write_json(self.client / "search.json", {
            "status": "done", "query_count": 4, "source_count": initial_count,
        })
        return cp.build_html(self.client, brief)

    def assert_source_count(self, html, expected):
        listing = re.search(r'<ul class="sources">(.*?)</ul>', html, re.S)
        self.assertIsNotNone(listing)
        self.assertEqual(listing.group(1).count("<li>"), expected)
        noun = "source" if expected == 1 else "sources"
        banners = " ".join(re.findall(r'<p class="banner">(.*?)</p>', html, re.S))
        self.assertRegex(banners, rf"(?:kept {expected} {noun}\b|{expected} {noun} kept\b)")
        if expected == 1:
            self.assertNotRegex(banners, r"\b1 sources\b")

    def test_five_listed_sources_override_initial_six(self):
        self.assert_source_count(self.render(self.brief(5), initial_count=6), 5)

    def test_one_listed_source_uses_singular(self):
        self.assert_source_count(self.render(self.brief(1), initial_count=1), 1)

    def test_count_tracks_sources_after_a_citation_is_dropped(self):
        brief = self.brief(6)
        self.assert_source_count(self.render(brief, initial_count=6), 6)
        brief["verified_facts"][0]["evidence_ids"].pop()
        html = self.render(brief, initial_count=6)
        self.assert_source_count(html, 5)
        self.assertNotIn("https://sources.example.test/profile/6", html)

    def test_count_tracks_identity_drop_after_initial_search_count(self):
        brief = self.brief(6)
        rows = [dict(source, identity_status="confirmed") for source in brief["appendix"]["sources"]]
        rows[-1]["identity_status"] = "unconfirmed"
        brief["verified_facts"][0]["evidence_ids"].pop()
        brief["appendix"]["sources"] = []
        errors, _warnings = cp.complete_kept_sources(brief, rows)
        self.assertEqual(errors, [])
        self.assert_source_count(self.render(brief, initial_count=6), 5)

    def test_unknown_name_gets_public_match_next_step_without_profile(self):
        self.write_json(self.root / "config.json", {"enabled": True})
        self.write_json(self.client / "search.json", {
            "status": "couldnt_find", "query_count": 4, "source_count": 0,
            "sources": [], "intake_name": "Avery Quindle",
        })
        output = io.StringIO()
        with patch.dict(os.environ, {"CLIENT_PROFILE_ROOT": str(self.root)}):
            with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as stopped:
                cp.main([str(SCRIPT), "identity", "candidates", self.client.name])
        self.assertEqual(stopped.exception.code, 0)
        reply = json.loads(output.getvalue())
        self.assertEqual(reply["status"], "couldnt_find")
        self.assertEqual(reply["candidates"], [])
        message = reply["message"]
        self.assertRegex(message.lower(), r"no public match|could(?:n't| not) find a public match")
        self.assertRegex(message.lower(), r"(?:send|provide|share).*(?:city|company).*(?:linkedin|website).*(?:link)?")
        self.assertNotEqual(message, "couldn't find")
        for extension in ("json", "html", "pdf"):
            self.assertFalse((self.client / f"brief.{extension}").exists())


if __name__ == "__main__":
    unittest.main()
