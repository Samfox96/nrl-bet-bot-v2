"""
test_backtest_season.py
=======================
The season backtest never looks at the future, and its summaries add up.

Run with: python3 -m unittest tests/test_backtest_season.py
(Standard library only, like the rest of this repo's tests. Needs pandas and requests,
like generate_predictions.py, which it reuses.)
"""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import backtest_season as bt  # noqa: E402


def match(h, a, hs, as_, p_home, margin=0.0):
    return {"home_team": h, "away_team": a, "home_score": hs, "away_score": as_,
            "our_home_win_prob": p_home, "our_predicted_margin": margin}


def scorer(name, p, scored, tries=None, fixture="A v B", team="A", rnd=10):
    return {"player_name": name, "team": team, "round": rnd, "fixture": fixture, "our_probability": p,
            "scored": scored, "tries": (1 if scored else 0) if tries is None else tries}


class Summaries(unittest.TestCase):
    def test_winners_margin_and_brier(self):
        ms = [match("A", "B", 20, 10, 0.8, 8.0),     # right, margin error 2
              match("C", "D", 10, 30, 0.7, 6.0),     # wrong, margin error 26
              match("E", "F", 12, 12, 0.6, 3.0)]     # draw: not scored for the winner, still in the margin
        s = bt.summarise_matches(ms)
        self.assertEqual((s["matches"], s["winners_scored"], s["winners_correct"]), (3, 2, 1))
        self.assertEqual(s["correct_pct"], 50.0)
        self.assertAlmostEqual(s["margin_mae"], (2 + 26 + 3) / 3, places=3)
        self.assertAlmostEqual(s["brier"], ((0.8 - 1) ** 2 + (0.7 - 0) ** 2) / 2, places=4)

    def test_empty_round(self):
        s = bt.summarise_matches([])
        self.assertEqual((s["matches"], s["correct_pct"], s["brier"]), (0, None, None))

    def test_try_scorer_summary_and_top3_hit_rate(self):
        group = [scorer("p1", 0.5, True), scorer("p2", 0.4, False), scorer("p3", 0.3, True),
                 scorer("p4", 0.1, True), scorer("p5", 0.05, False)]
        s = bt.summarise_scorers(group)
        self.assertEqual(s["players"], 5)
        self.assertEqual(s["top3_hit_pct"], round(100 * 2 / 3, 1))   # p1 and p3 of the top three scored
        self.assertAlmostEqual(s["base_rate"], 0.6)
        self.assertLess(s["brier"], s["brier_if_everyone_at_base_rate"] + 1)   # both defined

    def test_calibration_bands_compare_what_the_bot_said_with_what_happened(self):
        group = [scorer(f"a{i}", 0.05, i < 1) for i in range(10)] + [scorer(f"b{i}", 0.5, i < 6) for i in range(10)]
        bands = {b["from"]: b for b in bt.calibration(group)}
        self.assertEqual(bands[0.0]["really_scored_pct"], 10.0)
        self.assertEqual(bands[0.45]["really_scored_pct"], 60.0)
        self.assertEqual(bands[0.45]["bot_says_pct"], 50.0)

    def test_upsets_are_the_results_the_bot_thought_least_likely(self):
        ms = [(5, match("A", "B", 10, 20, 0.90)),     # away won, bot gave them 10%
              (6, match("C", "D", 20, 10, 0.60)),     # expected
              (7, match("E", "F", 20, 10, 0.20)),     # home won, bot gave them 20%
              (8, match("G", "H", 12, 12, 0.10))]     # draw ignored
        u = bt.upsets(ms)
        self.assertEqual([(x["round"], x["winner"]) for x in u], [(5, "B"), (7, "E")])
        self.assertEqual(u[0]["bot_gave_winner_pct"], 10.0)


class AgainstTheBot(unittest.TestCase):
    def test_thin_sample_players_never_appear_and_the_ceiling_is_flagged(self):
        games = {"Vet": {2026: set(range(1, 10))}, "Rookie": {2026: {8, 9}}}
        group = [scorer("Vet", 0.65, False), scorer("Rookie", 0.65, False),
                 scorer("Vet2", 0.01, True), scorer("Rookie2", 0.01, True)]
        games["Vet2"] = {2026: set(range(1, 10))}
        games["Rookie2"] = {2026: {9}}
        out = bt.against_the_bot(group, games, 2026)
        self.assertEqual([m["player_name"] for m in out["biggest_misses"]], ["Vet"])
        self.assertEqual([m["player_name"] for m in out["biggest_surprises"]], ["Vet2"])
        self.assertTrue(out["biggest_misses"][0]["at_model_ceiling"])

    def test_a_player_with_only_games_from_the_future_is_thin(self):
        games = {"P": {2026: {10, 11, 12, 13, 14, 15}}}      # none before round 10
        out = bt.against_the_bot([scorer("P", 0.6, False, rnd=10)], games, 2026)
        self.assertEqual(out["biggest_misses"], [])


@unittest.skipUnless((ROOT / "data" / "nrl_master.csv").exists() and (ROOT / "data" / "match_data_FINAL_fixed.csv").exists(), "data not present")
class NoLookingAtTheFuture(unittest.TestCase):
    """The same round rebuilt from data with every later round removed must give identical answers."""

    @classmethod
    def setUpClass(cls):
        from generate_predictions import load_real_baselines
        cls.b = load_real_baselines(str(ROOT / "data"))

    def rebuilt_without_the_future(self, rnd):
        master, matches = self.b["master_rows"], self.b["match_rows"]
        m2 = [r for r in master if not (r["season"] == "2026" and int(r["round"]) > rnd)]
        ma2 = [r for r in matches if not (r["season"] == "2026" and int(r["round"]) > rnd)]
        return bt.predict_round(2026, rnd, dict(self.b, master_rows=m2, match_rows=ma2), m2, ma2)

    def test_rounds_are_identical_with_and_without_later_rounds(self):
        for rnd in (4, 12, 20, 31):
            full = bt.predict_round(2026, rnd, self.b, self.b["master_rows"], self.b["match_rows"])
            cut = self.rebuilt_without_the_future(rnd)
            self.assertEqual(json.dumps(full, sort_keys=True), json.dumps(cut, sort_keys=True), f"round {rnd}")
            self.assertGreater(len(full["matches"]), 0)

    def test_the_output_is_deterministic(self):
        from datetime import datetime, timezone
        now = datetime(2026, 10, 16, tzinfo=timezone.utc)
        a = bt.build(2026, str(ROOT / "data"), now=now, first_round=28, last_round=31)
        b = bt.build(2026, str(ROOT / "data"), now=now, first_round=28, last_round=31)
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))

    def test_the_finals_give_a_grand_final(self):
        from datetime import datetime, timezone
        out = bt.build(2026, str(ROOT / "data"), now=datetime(2026, 10, 16, tzinfo=timezone.utc), first_round=28, last_round=31)
        gf = out["grand_final"]
        self.assertEqual((gf["home_team"], gf["away_team"]), ("Sydney Roosters", "Newcastle Knights"))
        self.assertEqual((gf["home_score"], gf["away_score"]), (19, 18))
        self.assertEqual(out["rounds_covered"], 4)


if __name__ == "__main__":
    unittest.main()
