"""
test_score_picks.py
===================
Every saved pick gets a result once the round is in, and the pretend-money numbers add up.

Run with: python3 -m unittest tests/test_score_picks.py
(Standard library only, like the rest of this repo's tests.)
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import score_picks as sp  # noqa: E402


class StakeShares(unittest.TestCase):
    def test_shares_sum_to_one_and_follow_the_weights(self):
        s = sp.stake_shares([3.0, 2.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0])
        self.assertAlmostEqual(sum(s), 1.0, places=9)
        self.assertGreater(s[0], s[1])
        self.assertGreater(s[1], s[2])

    def test_nobody_gets_more_than_40_percent_and_the_excess_is_shared_out(self):
        s = sp.stake_shares([100.0, 1.0, 1.0, 1.0, 1.0])
        self.assertAlmostEqual(s[0], 0.40, places=9)
        self.assertAlmostEqual(sum(s), 1.0, places=9)
        self.assertTrue(all(abs(x - 0.15) < 1e-9 for x in s[1:]))

    def test_two_big_picks_are_both_capped(self):
        s = sp.stake_shares([50.0, 50.0, 1.0, 1.0])
        self.assertAlmostEqual(s[0], 0.40, places=9)
        self.assertAlmostEqual(s[1], 0.40, places=9)
        self.assertAlmostEqual(s[2] + s[3], 0.20, places=9)

    def test_too_few_picks_for_the_cap_split_equally(self):
        self.assertEqual(sp.stake_shares([5.0, 1.0]), [0.5, 0.5])
        self.assertEqual(sp.stake_shares([5.0]), [1.0])
        self.assertEqual(sp.stake_shares([]), [])

    def test_all_zero_weights_split_equally(self):
        self.assertEqual(sp.stake_shares([0, 0, 0]), [1 / 3] * 3)


def pick(market, **kw):
    base = {"market": market, "home_team": "Broncos", "away_team": "Storm", "price": 3.0,
            "our_probability": 0.4, "market_probability": 1 / 3.0, "stake_weight": 0.02}
    base.update(kw)
    return base


SCORES = {("Broncos", "Storm"): (20, 14)}


class PickResults(unittest.TestCase):
    def test_try_scorer_won_lost_and_void(self):
        tries = {("A", "Broncos"): 2, ("B", "Storm"): 0}
        self.assertEqual(sp.pick_result(pick("try_scorer", player_name="A", team="Broncos"), SCORES, tries), "won")
        self.assertEqual(sp.pick_result(pick("try_scorer", player_name="B", team="Storm"), SCORES, tries), "lost")
        self.assertEqual(sp.pick_result(pick("try_scorer", player_name="Ghost", team="Storm"), SCORES, tries), "void")

    def test_winner_home_away_and_draw(self):
        self.assertEqual(sp.pick_result(pick("winner", team="Broncos"), SCORES, {}), "won")
        self.assertEqual(sp.pick_result(pick("winner", team="Storm"), SCORES, {}), "lost")
        self.assertEqual(sp.pick_result(pick("winner", team="Storm"), {("Broncos", "Storm"): (12, 12)}, {}), "push")

    def test_margin_covers_the_home_line(self):
        # home won by 6
        self.assertEqual(sp.pick_result(pick("margin", line=-4.5), SCORES, {}), "won")
        self.assertEqual(sp.pick_result(pick("margin", line=-6.5), SCORES, {}), "lost")
        self.assertEqual(sp.pick_result(pick("margin", line=7.5), SCORES, {}), "won")
        self.assertEqual(sp.pick_result(pick("margin", line=-6.0), SCORES, {}), "push")

    def test_a_match_missing_from_the_results_is_not_scored(self):
        self.assertIsNone(sp.pick_result(pick("winner", team="Broncos", home_team="X", away_team="Y"), SCORES, {}))

    def test_multipliers(self):
        self.assertEqual(sp.multiplier("won", 3.0), 3.0)
        self.assertEqual(sp.multiplier("lost", 3.0), 0.0)
        self.assertEqual(sp.multiplier("push", 3.0), 1.0)
        self.assertEqual(sp.multiplier("void", 3.0), 1.0)


class ScoreAWeek(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        (self.d / "picks_history").mkdir()
        (self.d / "team_aliases.json").write_text(json.dumps({"aliases": {"Broncos": "Broncos", "Storm": "Storm"}}))
        (self.d / "match_data_FINAL_fixed.csv").write_text("season,round,home_team,home_score,away_team,away_score\n2026,10,Broncos,20,Storm,14\n")
        (self.d / "nrl_master.csv").write_text("season,round,player_name,team,tries\n2026,10,Scorer,Broncos,1\n2026,10,Misser,Storm,0\n")

    def tearDown(self):
        self.tmp.cleanup()

    def save(self, picks, rnd=10):
        (self.d / "picks_history" / f"2026_round_{rnd}.json").write_text(json.dumps({"season": 2026, "round": rnd, "picks": picks}))

    def week(self, **kw):
        return sp.score(2026, 10, str(self.d), **kw)

    def test_the_week_adds_up(self):
        self.save([
            pick("try_scorer", player_name="Scorer", team="Broncos", price=4.0, stake_weight=0.04),   # won
            pick("winner", team="Storm", price=2.0, stake_weight=0.04),                                # lost
        ])
        w = self.week()
        s = w["scoring"]
        self.assertEqual((s["won"], s["lost"], s["picks_counted"]), (1, 1, 2))
        self.assertEqual([p["share"] for p in w["picks"]], [0.5, 0.5])
        self.assertAlmostEqual(s["return_multiplier"], 0.5 * 4.0, places=4)   # 2.0 back on 1.0 staked
        self.assertTrue(s["results_in"])

    def test_only_the_top_8_are_counted_but_every_pick_gets_a_result(self):
        picks = [pick("winner", team="Broncos", price=2.0, stake_weight=0.03) for _ in range(10)]
        self.save(picks)
        w = self.week()
        self.assertEqual(w["scoring"]["picks_counted"], 8)
        self.assertTrue(all(p["result"] == "won" for p in w["picks"]))
        self.assertIsNone(w["picks"][9]["share"])
        self.assertAlmostEqual(sum(p["share"] for p in w["picks"][:8]), 1.0, places=2)

    def test_void_and_push_return_the_stake(self):
        self.save([pick("try_scorer", player_name="Ghost", team="Storm", price=9.0, stake_weight=0.02),
                   pick("winner", team="Storm", price=9.0, stake_weight=0.02)])
        # first is void (did not play); second is lost
        w = self.week()
        self.assertEqual(w["picks"][0]["result"], "void")
        self.assertAlmostEqual(w["scoring"]["return_multiplier"], 0.5, places=4)

    def test_bot_and_market_expectations(self):
        self.save([pick("winner", team="Broncos", price=2.0, our_probability=0.6, market_probability=0.5, stake_weight=0.02)])
        s = self.week()["scoring"]
        self.assertAlmostEqual(s["expected_return_bot"], 1.2, places=4)
        self.assertAlmostEqual(s["expected_return_market"], 1.0, places=4)

    def test_missing_picks_or_results_are_refused_not_guessed(self):
        with self.assertRaises(FileNotFoundError):
            sp.score(2026, 99, str(self.d))
        self.save([pick("winner", team="Broncos")], rnd=11)
        with self.assertRaises(ValueError):
            sp.score(2026, 11, str(self.d))

    def test_scoring_twice_gives_the_same_answer(self):
        self.save([pick("winner", team="Broncos", price=2.0, stake_weight=0.02)])
        first = self.week()["scoring"]["return_multiplier"]
        second = self.week()["scoring"]["return_multiplier"]
        self.assertEqual(first, second)


HISTORY = ROOT / "data" / "picks_history"


@unittest.skipUnless((HISTORY / "2026_round_19.json").exists(), "replayed rounds not present")
class ReplayOfRounds18And19(unittest.TestCase):
    """Rounds 18 and 19, rebuilt from the saved predictions and scored against the real results."""

    def test_the_two_replayed_weeks(self):
        w18 = json.loads((HISTORY / "2026_round_18.json").read_text())
        w19 = json.loads((HISTORY / "2026_round_19.json").read_text())
        s18, s19 = w18["scoring"], w19["scoring"]
        self.assertEqual((s18["won"], s18["lost"]), (4, 4))
        self.assertEqual((s19["won"], s19["lost"]), (2, 6))
        self.assertAlmostEqual(s18["return_multiplier"], 1.3775, places=3)
        self.assertAlmostEqual(s19["return_multiplier"], 0.6505, places=3)
        for w in (w18, w19):
            self.assertAlmostEqual(sum(p["share"] for p in w["picks"] if p["share"]), 1.0, places=2)
            self.assertLessEqual(max(p["share"] for p in w["picks"] if p["share"]), 0.4001)
            self.assertAlmostEqual(w["scoring"]["expected_return_market"], 1.0, delta=0.01)


if __name__ == "__main__":
    unittest.main()
