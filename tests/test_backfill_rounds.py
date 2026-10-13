"""
test_backfill_rounds.py
========================
Tests for scripts/backfill_rounds.py -- the one-off catch-up script that
loops the normal single-round scrape/validate/merge pipeline across a
range of rounds (built 2026-10-13 to backfill rounds 21-27 and the 2026
finals after the Round 20 stall was fixed).

These tests NEVER touch a real browser or the real repo's data files --
every subprocess call goes through an injected fake `run_cmd` (see
backfill_rounds.run()'s own docstring for why that seam exists), and
round_range() is pure logic with no I/O at all. This mirrors
tests/test_merge_round.py's own approach: test the orchestration logic
directly, don't re-test the already-proven scrapers/validators underneath.

Run with: python3 -m unittest tests/test_backfill_rounds.py
(No third-party test framework needed -- uses only the standard library.)
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import backfill_rounds  # noqa: E402  (import after sys.path tweak, deliberately)


class FakeResult:
    def __init__(self, returncode):
        self.returncode = returncode
        self.stdout = ""
        self.stderr = ""


class FakeRunner:
    """
    Records every command it was called with and returns a scripted
    returncode for each call, in order -- lets a test say exactly which
    step in a round's pipeline should "fail" without needing a real
    failure to actually happen.
    """

    def __init__(self, returncodes):
        self.returncodes = list(returncodes)
        self.calls = []

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        code = self.returncodes.pop(0) if self.returncodes else 0
        return FakeResult(code)


class RoundRangeTests(unittest.TestCase):
    def test_simple_ascending_range(self):
        self.assertEqual(backfill_rounds.round_range(21, 23), [21, 22, 23])

    def test_single_round(self):
        self.assertEqual(backfill_rounds.round_range(21, 21), [21])

    def test_end_before_start_is_a_real_error(self):
        # Rounds must be processed in order -- merge_round.py always
        # merges "current max + 1", so a backwards or inverted range
        # could never correctly merge anyway. Must fail loud, not
        # silently return an empty list.
        with self.assertRaises(ValueError):
            backfill_rounds.round_range(23, 21)


class BackfillPlayerStatsTests(unittest.TestCase):
    def test_both_steps_succeed(self):
        runner = FakeRunner(returncodes=[0, 0])  # scrape, merge
        result = backfill_rounds.backfill_player_stats(21, run_cmd=runner)
        self.assertTrue(result)
        self.assertEqual(len(runner.calls), 2)
        self.assertIn("nrl_update_single_round.py", runner.calls[0][1])
        self.assertIn("merge_round.py", runner.calls[1][1])

    def test_scrape_failure_stops_before_merge_is_attempted(self):
        runner = FakeRunner(returncodes=[1])  # scrape fails
        result = backfill_rounds.backfill_player_stats(21, run_cmd=runner)
        self.assertFalse(result)
        # Never calls merge_round.py on real/unvalidated data if the
        # scrape itself never produced a file -- same rule
        # weekly-update.yml's own scrape-success gate enforces.
        self.assertEqual(len(runner.calls), 1)

    def test_merge_failure_is_reported_as_a_real_failure(self):
        runner = FakeRunner(returncodes=[0, 1])  # scrape ok, merge fails
        result = backfill_rounds.backfill_player_stats(21, run_cmd=runner)
        self.assertFalse(result)
        self.assertEqual(len(runner.calls), 2)


class BackfillMatchResultsTests(unittest.TestCase):
    def test_both_steps_succeed(self):
        runner = FakeRunner(returncodes=[0, 0])
        result = backfill_rounds.backfill_match_results(21, 2026, run_cmd=runner)
        self.assertTrue(result)
        self.assertIn("scrape_match_results.py", runner.calls[0][1])
        self.assertIn("merge_match_results_backfill.py", runner.calls[1][1])

    def test_uses_a_fresh_temp_dir_not_the_real_pending_dir(self):
        # Real risk being guarded against: merge_match_results_backfill.py
        # merges EVERY file in --backfill-dir matching its glob, with no
        # per-round filter. If this script reused one shared directory
        # across multiple rounds in the same run, a later round's merge
        # could accidentally sweep up an earlier round's leftover file.
        runner = FakeRunner(returncodes=[0, 0])
        backfill_rounds.backfill_match_results(21, 2026, run_cmd=runner)
        merge_cmd = runner.calls[1]
        backfill_dir_arg = merge_cmd[merge_cmd.index("--backfill-dir") + 1]
        self.assertNotIn("data/pending_match_results", backfill_dir_arg)
        self.assertNotEqual(backfill_dir_arg, str(backfill_rounds.DATA_DIR / "pending"))

    def test_scrape_failure_stops_before_merge_is_attempted(self):
        runner = FakeRunner(returncodes=[1])
        result = backfill_rounds.backfill_match_results(21, 2026, run_cmd=runner)
        self.assertFalse(result)
        self.assertEqual(len(runner.calls), 1)


class ScoreRoundIfArchivedTests(unittest.TestCase):
    def test_missing_archive_is_not_a_failure(self):
        # Rounds 21+ genuinely have no archived predictions (the
        # predictions pipeline was stuck on Round 20 too) -- this must
        # be reported as "nothing to score", never as a failure, and
        # must NEVER attempt to fabricate a retroactive prediction.
        runner = FakeRunner(returncodes=[])
        with patch.object(backfill_rounds, "DATA_DIR", Path("/tmp/definitely-does-not-exist-nrl")):
            result = backfill_rounds.score_round_if_archived(21, 2026, run_cmd=runner)
        self.assertTrue(result)
        self.assertEqual(len(runner.calls), 0)  # never even tries to run the scorer


class BackfillRoundIntegrationTests(unittest.TestCase):
    """Exercises backfill_round() end-to-end through the fake runner only."""

    def test_stops_overall_pipeline_on_player_stats_failure_without_touching_match_results(self):
        runner = FakeRunner(returncodes=[1])  # player-stats scrape fails immediately
        result = backfill_rounds.backfill_round(21, 2026, finals=False, run_cmd=runner)
        self.assertFalse(result)
        # Only the player-stats scrape was attempted -- match-results
        # scraping must never run for a round whose player stats already
        # failed, since the loop in main() would stop at this round anyway.
        self.assertEqual(len(runner.calls), 1)

    def test_full_success_runs_all_steps_in_order(self):
        # player-stats scrape, player-stats merge, match-results scrape,
        # match-results merge -- all succeed; no archive exists so scoring
        # is skipped (reported, not attempted as a real subprocess call).
        runner = FakeRunner(returncodes=[0, 0, 0, 0])
        with patch.object(backfill_rounds, "DATA_DIR", Path("/tmp/definitely-does-not-exist-nrl")):
            result = backfill_rounds.backfill_round(21, 2026, finals=False, run_cmd=runner)
        self.assertTrue(result)
        self.assertEqual(len(runner.calls), 4)


if __name__ == "__main__":
    unittest.main()
