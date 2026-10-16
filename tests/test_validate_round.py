"""
test_validate_round.py
=======================
Tests for scripts/validate_round.py's finals handling (built 2026-10-16,
as part of backfilling the 2026 finals -- rounds 28-31).

The regular season (rounds 1-27) checks team coverage against a FIXED
bye list (scripts/bye_schedule.json) -- that part is unchanged and
already exercised indirectly by every real weekly merge. These tests
cover the NEW branch: finals rounds, where which teams play is
ladder-dependent (no fixed bye list is possible), so validation checks
how MANY teams played instead of which ones by name.

Uses real team_aliases.json (via validate_round.load_aliases()) so the
team-name resolution these tests exercise is the exact same resolution
a real finals scrape would go through -- no browser/network involved,
just real CSV text written to a temp file, matching this repo's existing
"test the orchestration/validation logic directly" convention (see
tests/test_backfill_rounds.py's own docstring).

Run with: python3 -m unittest tests/test_validate_round.py
"""

import csv
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import validate_round  # noqa: E402  (import after sys.path tweak, deliberately)

COLUMNS = ["player_name", "team", "round", "season"]

# Real canonical team names (from data/team_aliases.json's canonical_teams
# list) -- using these directly means they resolve through the aliases
# map without any extra alias wiring needed for the test.
EIGHT_FINALS_TEAMS = [
    "Brisbane Broncos", "Canberra Raiders", "Canterbury-Bankstown Bulldogs",
    "Cronulla-Sutherland Sharks", "Dolphins", "Gold Coast Titans",
    "Manly-Warringah Sea Eagles", "Melbourne Storm",
]


def _write_round_csv(tmp_dir, teams, round_num, season=2026, players_per_team=15):
    """
    Writes a minimal real CSV covering only the columns validate_round.py
    actually reads (player_name, team, round, season) -- enough rows per
    team (>= MIN_ROWS_PER_TEAM) that the per-team row-count warning check
    never fires and muddies a test that's only trying to exercise the
    team-coverage check.
    """
    path = Path(tmp_dir) / f"round_{round_num}.csv"
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for team in teams:
            for i in range(players_per_team):
                writer.writerow({
                    "player_name": f"{team} Player {i}",
                    "team": team,
                    "round": round_num,
                    "season": season,
                })
    return path


class FinalsTeamCoverageTests(unittest.TestCase):
    def test_finals_round_with_expected_team_count_passes(self):
        # Round 28 (Finals Week 1) expects 8 teams -- give it exactly 8.
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = _write_round_csv(tmp_dir, EIGHT_FINALS_TEAMS, round_num=28)
            passed, failures, warnings = validate_round.validate(path, 28)
        self.assertTrue(passed, failures)
        self.assertEqual(failures, [])

    def test_finals_round_with_too_few_teams_fails(self):
        # Round 29 (Semi Finals) expects 4 teams -- give it only 3.
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = _write_round_csv(tmp_dir, EIGHT_FINALS_TEAMS[:3], round_num=29)
            passed, failures, warnings = validate_round.validate(path, 29)
        self.assertFalse(passed)
        self.assertTrue(any("expected to have 4 teams" in f for f in failures), failures)

    def test_finals_round_with_too_many_teams_fails(self):
        # Round 31 (Grand Final) expects 2 teams -- give it 4.
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = _write_round_csv(tmp_dir, EIGHT_FINALS_TEAMS[:4], round_num=31)
            passed, failures, warnings = validate_round.validate(path, 31)
        self.assertFalse(passed)
        self.assertTrue(any("expected to have 2 teams" in f for f in failures), failures)

    def test_round_after_grand_final_has_no_rule_and_fails_loud(self):
        # Round 32 doesn't exist in any real NRL season -- neither the
        # regular-season bye check nor the finals team-count table knows
        # it, so validate() must refuse to guess rather than silently pass.
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = _write_round_csv(tmp_dir, EIGHT_FINALS_TEAMS[:2], round_num=32)
            passed, failures, warnings = validate_round.validate(path, 32)
        self.assertFalse(passed)
        self.assertTrue(any("No validation rule exists for round 32" in f for f in failures), failures)

    def test_regular_season_round_unaffected_by_finals_change(self):
        # Round 1's only real bye is Wests Tigers (per bye_schedule.json) --
        # confirm the finals branch didn't regress the existing regular-
        # season bye-list check for a round well within 1-27.
        all_but_tigers = [
            t for t in validate_round.ALL_TEAMS if t != "Wests Tigers"
        ]
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = _write_round_csv(tmp_dir, all_but_tigers, round_num=1)
            passed, failures, warnings = validate_round.validate(path, 1)
        self.assertTrue(passed, failures)


if __name__ == "__main__":
    unittest.main()
