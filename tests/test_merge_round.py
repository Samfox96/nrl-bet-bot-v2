"""
test_merge_round.py
====================
Regression test for the real Round 20 stall (found 2026-10-13).

The bug: merge_round.py used to grab the first pending file it found,
sorted alphabetically, and hand it to validate_round.py no matter which
round the workflow was actually expecting that week. A leftover pending
file from an earlier round (left behind because the workflow's commit
step never committed the deletion of a successfully-merged pending file)
sorted before the real, fresh pending file for the round actually due --
so every week from Round 20 onward, the WRONG file got validated against
the RIGHT round number, failed the very first "round mismatch" check, and
the weekly run committed "Round N: scrape/validation needs review" while
the genuinely fine scrape for that round sat right next to it, never
tried.

These tests reproduce exactly that directory state (a stale earlier-round
file plus the real current-round file sitting in data/pending/ together)
and confirm `find_pending_file` now picks the correct one -- and refuses
to guess when the real file for the expected round is missing.

Run with: python3 -m unittest tests/test_merge_round.py
(No third-party test framework needed -- uses only the standard library,
same as the rest of this repo's scripts.)
"""

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import merge_round  # noqa: E402  (import after sys.path tweak, deliberately)


class FindPendingFileTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.pending_dir = Path(self._tmpdir.name)
        # Point the module at our throwaway directory instead of the real
        # repo's data/pending/ -- these tests never touch real data.
        self._original_pending_dir = merge_round.PENDING_DIR
        merge_round.PENDING_DIR = self.pending_dir

    def tearDown(self):
        merge_round.PENDING_DIR = self._original_pending_dir
        self._tmpdir.cleanup()

    def _touch(self, filename):
        (self.pending_dir / filename).write_text("round\n20\n")

    def test_picks_the_file_for_the_expected_round_not_the_leftover(self):
        # Reproduces the real failure state: a stale Round 19 pending file
        # (never cleaned up from git after its retry succeeded) sitting
        # next to the real, fresh Round 20 pending file. Before the fix,
        # sorted() put "nrl_round_19_new.csv" first and that's what got
        # returned -- wrong round, every time.
        self._touch("nrl_round_19_new.csv")
        self._touch("nrl_round_20_new.csv")

        result = merge_round.find_pending_file(20)

        self.assertEqual(result, self.pending_dir / "nrl_round_20_new.csv")

    def test_ignores_multiple_leftovers_and_still_finds_the_right_one(self):
        self._touch("nrl_round_18_new.csv")
        self._touch("nrl_round_19_new.csv")
        self._touch("nrl_round_20_new.csv")

        result = merge_round.find_pending_file(20)

        self.assertEqual(result, self.pending_dir / "nrl_round_20_new.csv")

    def test_no_file_for_the_expected_round_is_a_real_failure(self):
        # Only a leftover from an earlier round exists -- the expected
        # round's own scrape never produced a file. This must fail loudly
        # (sys.exit(1)), not silently fall back to the leftover.
        self._touch("nrl_round_19_new.csv")

        with self.assertRaises(SystemExit) as ctx:
            merge_round.find_pending_file(20)
        self.assertEqual(ctx.exception.code, 1)

    def test_nothing_pending_at_all_is_a_real_failure(self):
        with self.assertRaises(SystemExit) as ctx:
            merge_round.find_pending_file(20)
        self.assertEqual(ctx.exception.code, 1)

    def test_only_the_expected_round_file_present_is_the_normal_case(self):
        self._touch("nrl_round_20_new.csv")

        result = merge_round.find_pending_file(20)

        self.assertEqual(result, self.pending_dir / "nrl_round_20_new.csv")


if __name__ == "__main__":
    unittest.main()
