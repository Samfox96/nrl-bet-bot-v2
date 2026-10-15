"""
tests/test_scrape_match_results.py

Covers MATCH_TEXT_PATTERN, the regex scrape_match_results.py uses to pull
team names and scores out of each round-level ".match--highlighted" card's
raw text.

Added 2026-10-13 during the Round 22-27 backfill, after a real backfill
run hit a real bug on Round 23: nrl.com started printing a traditional-
custodian acknowledgment line (e.g. "Dharawal & Gadigal") directly under
the team name, before "Scored". The OLD pattern's team-name group was
[\\w\\s'-]+? -- \\s matches a newline, so it either silently swallowed the
acknowledgment line into the team name (when the line had no "&"/","), or
failed to match the card at all (when it did, since "&"/"," weren't in
that character class) and the match was silently dropped. Both failure
modes showed up in the real backfill run's log for Round 23 before the
fix landed.

These three cases are the real raw card text (reformatted only to remove
the real match's score where it isn't relevant) seen in that run:
  1. A round with no acknowledgment line at all (every round before R23).
  2. An acknowledgment line containing "&" (the case that used to be
     silently DROPPED, not merged).
  3. An acknowledgment line with no "&"/"," (the case that used to be
     silently MIS-PARSED -- e.g. "Titans\\nYugambeh" as the team name).
"""

import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from scrape_match_results import MATCH_TEXT_PATTERN  # noqa: E402


class TestMatchTextPattern(unittest.TestCase):
    def test_card_with_no_acknowledgment_line(self):
        """Every round before Round 23 -- must still parse correctly."""
        text = (
            "FRIDAY 7TH AUGUST\nFULL TIME\nhome Team\nCowboys\nScored\n24\n"
            "points\naway Team\nRoosters\nScored\n18\npoints"
        )
        m = MATCH_TEXT_PATTERN.search(text)
        self.assertIsNotNone(m)
        self.assertEqual(m.group("home_team"), "Cowboys")
        self.assertEqual(m.group("away_team"), "Roosters")
        self.assertEqual(m.group("home_score"), "24")
        self.assertEqual(m.group("away_score"), "18")

    def test_card_with_ampersand_in_acknowledgment_line(self):
        """
        Real Round 23 text -- used to fail MATCH_TEXT_PATTERN entirely
        (the "&" wasn't in the old team-name character class), so the
        whole card was dropped, NOT merged.
        """
        text = (
            "FRIDAY 7TH AUGUST\nFULL TIME\nhome Team\nRoosters\n"
            "Dharawal & Gadigal\nScored\n20\npoints\naway Team\nBulldogs\n"
            "Dharug, Bidjigal/Bediagal\nScored\n18\npoints"
        )
        m = MATCH_TEXT_PATTERN.search(text)
        self.assertIsNotNone(m)
        self.assertEqual(m.group("home_team"), "Roosters")
        self.assertEqual(m.group("away_team"), "Bulldogs")
        self.assertEqual(m.group("home_score"), "20")
        self.assertEqual(m.group("away_score"), "18")

    def test_card_with_plain_acknowledgment_line(self):
        """
        Real Round 23 text -- used to silently mis-parse the team name
        as "Titans\\nYugambeh" (acknowledgment line swallowed into the
        team name because \\s matches a newline).
        """
        text = (
            "SUNDAY 9TH AUGUST\nFULL TIME\nhome Team\nTitans\nYugambeh\n"
            "Scored\n30\npoints\naway Team\nCowboys\nWulgurukaba\nScored\n"
            "18\npoints"
        )
        m = MATCH_TEXT_PATTERN.search(text)
        self.assertIsNotNone(m)
        self.assertEqual(m.group("home_team"), "Titans")
        self.assertEqual(m.group("away_team"), "Cowboys")
        self.assertEqual(m.group("home_score"), "30")
        self.assertEqual(m.group("away_score"), "18")


if __name__ == "__main__":
    unittest.main()
