#!/usr/bin/env python3
"""canon-lint hardening tests — a rate-limited sweep is INCOMPLETE, never PASS.

Doctrine (2026-09-20 sweep reversal + hardening): GitHub 403/429 mid-sweep
must stop the run with exit 2 and an INCOMPLETE report — never crash
(HTTPError traceback), never print PASS over unchecked repos.

  1. 403 converts      _open_checked turns HTTPError 403 into RateLimited
                       carrying the repo label + Retry-After.
  2. 429 converts      same for 429 (no Retry-After header -> hint absent).
  3. other codes pass  HTTPError 500 is NOT swallowed; success passthrough.
  4. fetch phase       fetch_canon_remote raising RateLimited -> exit 2,
                       "INCOMPLETE" on stdout, "--remote" accepted by argparse.
  5. staleness phase   RateLimited from the pushed_at API -> exit 2,
                       "staleness phase" on stdout.
  6. schema spot-check valid stub passes check_schema (guards the fixture).

Run: python3 test/test_canon_lint_hard.py   (stdlib only, no network)
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import sys
import unittest
import urllib.error
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location(
    "canon_lint", os.path.join(ROOT, "fleet-canon", "lint.py"))
lint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lint)

VALID_STUB = """---
canon: 1
name: {repo}
mission: fleet vessel
state: active
family: fleet
vessel: {repo}
born_from: seed
feeds: []
owed_by: []
canonical_docs: []
ledger: git-log
verified: 2026-09-20
---
"""


def _http_error(code: int, retry_after: str | None = None):
    headers = {"Retry-After": retry_after} if retry_after else {}
    return urllib.error.HTTPError("https://api.github.com/x", code, "msg",
                                  headers, None)


class OpenCheckedTest(unittest.TestCase):
    def test_403_becomes_rate_limited(self):
        with mock.patch("urllib.request.urlopen",
                        side_effect=_http_error(403, "60")):
            with self.assertRaises(lint.RateLimited) as ctx:
                lint._open_checked(object(), "hermit")
        self.assertEqual(ctx.exception.repo, "hermit")
        self.assertEqual(ctx.exception.retry_after, "60")
        self.assertIn("hermit", str(ctx.exception))
        self.assertIn("60s", str(ctx.exception))

    def test_429_becomes_rate_limited_no_hint(self):
        with mock.patch("urllib.request.urlopen",
                        side_effect=_http_error(429)):
            with self.assertRaises(lint.RateLimited) as ctx:
                lint._open_checked(object(), "tidepool")
        self.assertEqual(ctx.exception.repo, "tidepool")
        self.assertIsNone(ctx.exception.retry_after)
        self.assertNotIn("Retry-After", str(ctx.exception))

    def test_other_http_error_reraises(self):
        with mock.patch("urllib.request.urlopen",
                        side_effect=_http_error(500)):
            with self.assertRaises(urllib.error.HTTPError):
                lint._open_checked(object(), "quilt")

    def test_success_passthrough(self):
        sentinel = object()
        with mock.patch("urllib.request.urlopen", return_value=sentinel):
            self.assertIs(lint._open_checked(object(), "hermit"), sentinel)


class MainIncompleteTest(unittest.TestCase):
    def _run_main(self, argv):
        out = io.StringIO()
        with mock.patch.object(sys, "argv", argv), \
                contextlib.redirect_stdout(out):
            code = lint.main()
        return code, out.getvalue()

    def test_fetch_phase_rate_limited_exits_2(self):
        def boom(repo):
            raise lint.RateLimited(repo, None)
        with mock.patch.object(lint, "fetch_canon_remote", side_effect=boom):
            code, out = self._run_main(["lint.py", "--remote"])
        self.assertEqual(code, 2, out)
        self.assertIn("INCOMPLETE", out)
        self.assertIn("never a PASS", out)
        self.assertIn("0/27", out)

    def test_staleness_phase_rate_limited_exits_2(self):
        def fetch(repo):
            return VALID_STUB.format(repo=repo) if repo == "hermit" else None
        def boom(path, accept="application/vnd.github+json"):
            raise lint.RateLimited(path, None)
        with mock.patch.object(lint, "fetch_canon_remote", side_effect=fetch), \
                mock.patch.object(lint, "api", side_effect=boom):
            code, out = self._run_main(["lint.py", "--remote"])
        self.assertEqual(code, 2, out)
        self.assertIn("staleness phase", out)
        self.assertIn("INCOMPLETE", out)

    def test_valid_stub_passes_schema(self):
        parsed = lint.parse_front_matter(VALID_STUB.format(repo="hermit"))
        self.assertIsInstance(parsed, dict)
        self.assertEqual(lint.check_schema("hermit", parsed), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
