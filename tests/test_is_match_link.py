"""is_match_link must accept regular-season AND finals match links, and nothing else."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from match_links import is_match_link, teams_from_buttons  # noqa: E402

BASE = "https://www.nrl.com/draw/nrl-premiership/2026"


class IsMatchLinkTests(unittest.TestCase):
    def test_regular_season_match(self):
        self.assertTrue(is_match_link(f"{BASE}/round-21/knights-v-dragons/"))

    def test_finals_weeks(self):
        for week in (1, 2, 3):
            self.assertTrue(is_match_link(f"{BASE}/finals-week-{week}/storm-v-panthers/"))

    def test_grand_final(self):
        self.assertTrue(is_match_link(f"{BASE}/grand-final/game-1/storm-v-panthers/"))

    def test_grand_final_game_page_without_team_slug(self):
        self.assertTrue(is_match_link(f"{BASE}/grand-final/game-1/"))
        self.assertTrue(is_match_link(f"{BASE}/grand-final/storm-v-panthers/"))

    def test_trailing_fragment_ok(self):
        self.assertTrue(is_match_link(f"{BASE}/finals-week-1/storm-v-panthers/#stats"))

    def test_not_a_match_page(self):
        self.assertFalse(is_match_link(f"{BASE}/finals-week-1/"))
        self.assertFalse(is_match_link(f"{BASE}/grand-final/"))
        self.assertFalse(is_match_link(f"{BASE}/"))
        self.assertFalse(is_match_link("https://www.nrl.com/draw/"))
        self.assertFalse(is_match_link(None))
        self.assertFalse(is_match_link(""))


ALIASES = {"Roosters": "Sydney Roosters", "Sydney Roosters": "Sydney Roosters",
           "Knights": "Newcastle Knights", "Newcastle Knights": "Newcastle Knights"}


class TeamsFromButtonsTests(unittest.TestCase):
    def test_grand_final_tabs(self):
        self.assertEqual(teams_from_buttons(["MORE", "Roosters", "Knights", ""], ALIASES), ["Roosters", "Knights"])

    def test_wrong_count_returns_nothing(self):
        self.assertEqual(teams_from_buttons(["MORE", "Roosters", ""], ALIASES), [])
        self.assertEqual(teams_from_buttons(["Roosters", "Sydney Roosters"], ALIASES), [])


if __name__ == "__main__":
    unittest.main()
