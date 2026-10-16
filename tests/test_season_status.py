"""
test_season_status.py
=====================
The weekly jobs stay quiet after the Grand Final, but never silently forever.

Run with: python3 -m unittest tests/test_season_status.py
(Standard library only, like the rest of this repo's tests.)
"""

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import season_status as ss  # noqa: E402


def master(season, last_round):
    return [(season, r) for r in range(1, last_round + 1) for _ in range(2)]


def matches(season, per_round, last_round):
    rows = []
    for r in range(1, last_round + 1):
        rows += [(season, r)] * per_round.get(r, 8)
    return rows


MID = date(2026, 8, 5)
SUMMER = date(2026, 12, 10)
PRESEASON = date(2027, 2, 10)


class SeasonStatus(unittest.TestCase):
    def test_mid_season_runs_normally(self):
        s = ss.status(master(2026, 20), matches(2026, {}, 20), MID)
        self.assertEqual((s["state"], s["next_round"]), ("in_season", 21))

    def test_a_one_match_round_before_round_27_is_not_a_grand_final(self):
        s = ss.status(master(2026, 10), matches(2026, {10: 1}, 10), MID)
        self.assertEqual(s["state"], "in_season")

    def test_finals_week_with_several_matches_is_still_in_season(self):
        s = ss.status(master(2026, 28), matches(2026, {28: 4}, 28), MID)
        self.assertEqual(s["state"], "in_season")

    def test_grand_final_in_means_off_season(self):
        s = ss.status(master(2026, 31), matches(2026, {28: 4, 29: 2, 30: 2, 31: 1}, 31), SUMMER)
        self.assertEqual((s["state"], s["last_round"]), ("off_season", 31))

    def test_off_season_becomes_overdue_on_1_feb(self):
        m, r = master(2026, 31), matches(2026, {28: 4, 29: 2, 30: 2, 31: 1}, 31)
        self.assertEqual(ss.status(m, r, date(2027, 1, 31))["state"], "off_season")
        self.assertEqual(ss.status(m, r, date(2027, 2, 1))["state"], "off_season_overdue")
        self.assertEqual(ss.status(m, r, PRESEASON)["state"], "off_season_overdue")

    def test_next_round_is_per_season(self):
        both = master(2026, 31) + [(2027, 1)] * 5
        mm = matches(2026, {31: 1}, 31) + [(2027, 1)] * 8
        s = ss.status(both, mm, date(2027, 3, 10))
        self.assertEqual((s["state"], s["season"], s["next_round"]), ("in_season", 2027, 2))

    def test_no_data_runs_normally(self):
        self.assertEqual(ss.status([], [], MID)["state"], "in_season")

    def test_unreadable_files_run_normally(self):
        with tempfile.TemporaryDirectory() as d:
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = ss.main(["--data-dir", d], today=SUMMER)
        self.assertEqual(code, 0)
        self.assertIn("state=in_season", buf.getvalue())

    def test_command_line_prints_outputs(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "nrl_master.csv").write_text("season,round\n" + "\n".join("2026,31" for _ in range(3)) + "\n", encoding="utf-8")
            (Path(d) / "match_data_FINAL_fixed.csv").write_text("season,round\n2026,31\n", encoding="utf-8")
            buf = io.StringIO()
            with redirect_stdout(buf):
                ss.main(["--data-dir", d], today=SUMMER)
            out = buf.getvalue()
            nxt = io.StringIO()
            with redirect_stdout(nxt):
                ss.main(["--data-dir", d, "--next-round"], today=SUMMER)
        self.assertIn("state=off_season", out)
        self.assertIn("last_round=31", out)
        self.assertEqual(nxt.getvalue().strip(), "32")


if __name__ == "__main__":
    unittest.main()
