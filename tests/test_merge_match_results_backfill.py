"""
test_merge_match_results_backfill.py
======================================
Tests for scripts/merge_match_results_backfill.py's finals handling
(built 2026-10-16, as part of backfilling the 2026 finals -- rounds
28-31).

Check 4 (per-round row count) used to silently SKIP any round not in
scripts/bye_schedule.json (which only covers rounds 1-27) -- meaning a
finals round got no real count check at all. These tests cover the new
FINALS_MATCH_COUNTS branch: a known expected match count per finals
week, and a loud failure for any round neither table recognises (never
a silent pass).

Pure logic, no real files/network -- validate() takes plain dicts, same
convention as every real validation function this project tests
directly (see tests/test_backfill_rounds.py's own docstring).

Run with: python3 -m unittest tests/test_merge_match_results_backfill.py
"""

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import merge_match_results_backfill as mmrb  # noqa: E402

TEAM_ALIASES = {
    "Broncos": "Brisbane Broncos",
    "Raiders": "Canberra Raiders",
    "Bulldogs": "Canterbury-Bankstown Bulldogs",
    "Sharks": "Cronulla-Sutherland Sharks",
    "Dolphins": "Dolphins",
    "Titans": "Gold Coast Titans",
    "Sea Eagles": "Manly-Warringah Sea Eagles",
    "Storm": "Melbourne Storm",
}


def _match(round_num, home, away, season=2026):
    return {
        "season": season, "round": str(round_num),
        "home_team": home, "away_team": away,
        "home_score": "20", "away_score": "18",
    }


class FinalsMatchCountTests(unittest.TestCase):
    def test_finals_round_with_expected_match_count_passes(self):
        # Round 28 (Finals Week 1) expects 4 matches -- give it exactly 4.
        rows = [
            _match(28, "Broncos", "Raiders"),
            _match(28, "Bulldogs", "Sharks"),
            _match(28, "Dolphins", "Titans"),
            _match(28, "Sea Eagles", "Storm"),
        ]
        passed, problems = mmrb.validate(rows, TEAM_ALIASES, existing_master_rows=[])
        self.assertTrue(passed, problems)

    def test_finals_round_with_too_few_matches_fails(self):
        # Round 29 (Semi Finals) expects 2 matches -- give it only 1.
        rows = [_match(29, "Broncos", "Raiders")]
        passed, problems = mmrb.validate(rows, TEAM_ALIASES, existing_master_rows=[])
        self.assertFalse(passed)
        self.assertTrue(
            any("expected finals match count (2)" in p for p in problems), problems
        )

    def test_finals_round_with_too_many_matches_fails(self):
        # Round 31 (Grand Final) expects 1 match -- give it 2.
        rows = [
            _match(31, "Broncos", "Raiders"),
            _match(31, "Bulldogs", "Sharks"),
        ]
        passed, problems = mmrb.validate(rows, TEAM_ALIASES, existing_master_rows=[])
        self.assertFalse(passed)
        self.assertTrue(
            any("expected finals match count (1)" in p for p in problems), problems
        )

    def test_unrecognised_round_fails_loud_instead_of_silently_passing(self):
        # Round 32 doesn't exist in any real NRL season -- before this
        # fix, a round missing from EXPECTED_BYES silently skipped the
        # count check entirely. Now it must fail loud instead.
        rows = [_match(32, "Broncos", "Raiders")]
        passed, problems = mmrb.validate(rows, TEAM_ALIASES, existing_master_rows=[])
        self.assertFalse(passed)
        self.assertTrue(any("no known expected match count" in p for p in problems), problems)

    def test_regular_season_round_unaffected_by_finals_change(self):
        # Round 1 has exactly one real bye (Wests Tigers) per
        # bye_schedule.json -> 8 expected matches. Confirm the new
        # finals branch didn't regress this existing check.
        import json
        with open(REPO_ROOT / "scripts" / "bye_schedule.json") as f:
            bye_schedule = json.load(f)
        round_1_byes = bye_schedule["1"]
        expected_matches = (17 - len(round_1_byes)) // 2
        self.assertEqual(expected_matches, 8)

        rows = [_match(1, "Broncos", "Raiders")]  # 1 match, not the expected 8
        passed, problems = mmrb.validate(rows, TEAM_ALIASES, existing_master_rows=[])
        self.assertFalse(passed)
        self.assertTrue(any("does not match the real expected count (8)" in p for p in problems), problems)


if __name__ == "__main__":
    unittest.main()
