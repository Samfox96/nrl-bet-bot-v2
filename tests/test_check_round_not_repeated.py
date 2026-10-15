"""
test_check_round_not_repeated.py
=================================
The predictions job must not quietly redo a round from an earlier week
(the "retries one round forever" failure behind the Round 20 stall).

Run with: python3 -m unittest tests/test_check_round_not_repeated.py
(Standard library only, like the rest of this repo's tests.)
"""

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import check_round_not_repeated as check  # noqa: E402

NOW = datetime(2026, 10, 22, 1, 0, tzinfo=timezone.utc)


class CheckRoundNotRepeated(unittest.TestCase):
    def run_check(self, archived_at=None, rnd=21, season=2026, write=True, raw=None):
        with tempfile.TemporaryDirectory() as d:
            if write:
                text = raw if raw is not None else json.dumps({"season": season, "round": rnd, "archived_at": archived_at})
                (Path(d) / f"{season}_round_{rnd}.json").write_text(text, encoding="utf-8")
            return check.main(["--round", str(rnd), "--season", str(season), "--history-dir", d], now=NOW)

    def test_a_new_round_goes_ahead(self):
        self.assertEqual(self.run_check(write=False), 0)

    def test_a_same_week_refresh_goes_ahead(self):
        self.assertEqual(self.run_check((NOW - timedelta(days=2)).isoformat()), 0)

    def test_the_same_round_a_week_later_is_stopped(self):
        # The exact stall: round 21 predicted on 15 Oct, and the job comes back to it on 22 Oct.
        self.assertEqual(self.run_check((NOW - timedelta(days=7)).isoformat()), 1)

    def test_a_z_suffixed_time_is_understood(self):
        self.assertEqual(self.run_check("2026-10-15T01:04:51Z"), 1)

    def test_an_unreadable_archive_never_blocks(self):
        self.assertEqual(self.run_check(raw="not json"), 0)
        self.assertEqual(self.run_check(raw=json.dumps({"season": 2026})), 0)


if __name__ == "__main__":
    unittest.main()
