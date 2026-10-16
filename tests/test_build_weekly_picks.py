"""
test_build_weekly_picks.py
==========================
The weekly picks file: ranked by edge, flags instead of hiding, honest when there
are no prices, and the sample rule never looks at the future.

Run with: python3 -m unittest tests/test_build_weekly_picks.py
(Standard library only, like the rest of this repo's tests.)
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_weekly_picks as bp  # noqa: E402


def scorer(name, team, our_p, price, bookmaker="sportsbet"):
    mkt = 1.0 / price
    return {"player_name": name, "team": team, "position_code": "WG", "bookmaker": bookmaker,
            "our_probability": our_p, "market_probability": mkt, "edge": our_p - mkt}


def fixture(home="Broncos", away="Storm", scorers=(), h2h=None):
    base = {"our_home_win_prob": 0.5, "market_home_win_prob": 0.5, "our_predicted_margin": 0.0,
            "margin_mae": 14.0, "market_spread_point": 0.5, "market_spread_price": 1.9,
            "market_spread_bookmaker": "sportsbet"}
    base.update(h2h or {})
    return {"home_team": home, "away_team": away, "status": "ok", "h2h": base, "try_scorer_edges": list(scorers)}


def games(player, season, rounds):
    return {player: {season: set(rounds)}}


class Maths(unittest.TestCase):
    def test_cover_chance_is_half_when_the_line_matches_the_prediction(self):
        self.assertAlmostEqual(bp.chance_to_cover(-6.0, 6.0, 14.0), 0.5, places=3)

    def test_cover_chance_rises_when_we_expect_a_bigger_win_than_the_line(self):
        self.assertGreater(bp.chance_to_cover(-4.5, 10.1, 14.0), 0.6)
        self.assertLess(bp.chance_to_cover(-4.5, -3.0, 14.0), 0.4)

    def test_cover_chance_handles_a_plus_line(self):
        # +7.5 covers if the home team loses by less than 7.5
        self.assertGreater(bp.chance_to_cover(7.5, -2.0, 14.0), 0.5)


class SampleRule(unittest.TestCase):
    def test_counts_only_rounds_before_the_one_being_predicted(self):
        g = games("A", 2026, [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(bp.sample_games(g, "A", 2026, 7), 6)   # rounds 1-6; round 7 is the future
        self.assertEqual(bp.sample_games(g, "A", 2026, 1), 0)

    def test_last_season_counts_until_round_5_then_stops(self):
        g = {"A": {2026: {1, 2}, 2025: set(range(1, 21))}}
        self.assertEqual(bp.sample_games(g, "A", 2026, 3), 2 + 20)
        self.assertEqual(bp.sample_games(g, "A", 2026, 5), 2 + 20)
        self.assertEqual(bp.sample_games(g, "A", 2026, 6), 2)

    def test_unknown_player_has_no_games(self):
        self.assertEqual(bp.sample_games({}, "Nobody", 2026, 10), 0)


class Candidates(unittest.TestCase):
    def test_try_scorer_edge_is_shrunk_for_few_games_and_flagged(self):
        f = fixture(scorers=[scorer("Rookie", "Broncos", 0.40, 3.0)])
        c = bp.try_scorer_candidates(f, games("Rookie", 2026, [8, 9]), 2026, 10)[0]
        self.assertEqual(c["n_games"], 2)
        self.assertLess(c["effective_edge"], c["edge"])
        self.assertIn("few_games", [x["code"] for x in c["flags"]])
        self.assertIn("Only 2 games", c["flags"][0]["text"])

    def test_a_player_with_enough_games_has_no_flag(self):
        f = fixture(scorers=[scorer("Vet", "Broncos", 0.40, 3.0)])
        c = bp.try_scorer_candidates(f, games("Vet", 2026, range(1, 10)), 2026, 10)[0]
        self.assertEqual(c["n_games"], 9)
        self.assertEqual(c["flags"], [])

    def test_price_is_the_inverse_of_the_market_chance_and_long_shots_are_flagged_not_hidden(self):
        f = fixture(scorers=[scorer("Long", "Broncos", 0.12, 15.0)])
        c = bp.try_scorer_candidates(f, games("Long", 2026, range(1, 10)), 2026, 10)[0]
        self.assertAlmostEqual(c["price"], 15.0, places=2)
        self.assertIn("long_shot", [x["code"] for x in c["flags"]])

    def test_zero_or_negative_edges_are_not_picks(self):
        f = fixture(scorers=[scorer("Fav", "Broncos", 0.30, 2.0)])   # market 50%, ours 30%
        self.assertEqual(bp.try_scorer_candidates(f, {}, 2026, 10), [])

    def test_one_entry_per_player_keeps_the_best_bookmaker(self):
        f = fixture(scorers=[scorer("P", "Broncos", 0.40, 2.5, "booka"), scorer("P", "Broncos", 0.40, 3.2, "bookb")])
        out = bp.try_scorer_candidates(f, {}, 2026, 10)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["bookmaker"], "bookb")

    def test_winner_picks_the_side_with_the_positive_edge(self):
        home = bp.winner_candidate(fixture(h2h={"our_home_win_prob": 0.70, "market_home_win_prob": 0.55}))
        self.assertEqual(home["selection"], "Broncos to win")
        away = bp.winner_candidate(fixture(h2h={"our_home_win_prob": 0.30, "market_home_win_prob": 0.45}))
        self.assertEqual(away["selection"], "Storm to win")
        self.assertTrue(away["price_is_estimate"])
        self.assertIn("estimated_price", [x["code"] for x in away["flags"]])

    def test_no_winner_pick_when_bot_and_market_agree(self):
        self.assertIsNone(bp.winner_candidate(fixture(h2h={"our_home_win_prob": 0.5, "market_home_win_prob": 0.5})))

    def test_margin_pick_when_the_bot_expects_a_bigger_win_than_the_line(self):
        c = bp.margin_candidate(fixture(h2h={"our_predicted_margin": 12.0, "market_spread_point": -4.5}))
        self.assertEqual(c["selection"], "Broncos -4.5")
        self.assertGreater(c["edge"], 0)
        self.assertFalse(c["price_is_estimate"])

    def test_no_margin_pick_without_a_price(self):
        self.assertIsNone(bp.margin_candidate(fixture(h2h={"market_spread_price": None})))


class Build(unittest.TestCase):
    def run_build(self, fixtures, master_rows=(), season=2026, rnd=10):
        with tempfile.TemporaryDirectory() as d:
            pred = Path(d) / "p.json"
            pred.write_text(json.dumps({"season": season, "round": rnd, "results": fixtures}), encoding="utf-8")
            master = Path(d) / "m.csv"
            master.write_text("player_name,team,round,season\n" + "".join(f"{n},T,{r},{s}\n" for n, r, s in master_rows), encoding="utf-8")
            return bp.build(str(pred), str(master))

    def vets(self, *names):
        return [(n, r, 2026) for n in names for r in range(1, 10)]

    def test_picks_are_ranked_by_effective_edge_and_numbered(self):
        f = fixture(scorers=[scorer("Small", "Broncos", 0.35, 3.0), scorer("Big", "Storm", 0.55, 3.0)])
        out = self.run_build([f], self.vets("Small", "Big"))
        self.assertEqual(out["status"], "ok")
        scorers = [p for p in out["picks"] if p["market"] == "try_scorer"]
        self.assertEqual([p["player_name"] for p in scorers], ["Big", "Small"])
        self.assertEqual([p["rank"] for p in out["picks"]], list(range(1, len(out["picks"]) + 1)))
        effs = [p["effective_edge"] for p in out["picks"]]
        self.assertEqual(effs, sorted(effs, reverse=True))

    def test_only_the_top_20_are_kept(self):
        f = fixture(scorers=[scorer(f"P{i}", "Broncos", 0.50, 3.0) for i in range(30)])
        out = self.run_build([f], self.vets(*[f"P{i}" for i in range(30)]))
        self.assertEqual(len(out["picks"]), bp.KEEP)

    def test_a_thin_sample_player_ranks_below_an_equal_veteran(self):
        f = fixture(scorers=[scorer("Rookie", "Broncos", 0.50, 3.0), scorer("Vet", "Storm", 0.50, 3.0)])
        out = self.run_build([f], self.vets("Vet") + [("Rookie", 9, 2026)])
        names = [p["player_name"] for p in out["picks"] if p["market"] == "try_scorer"]
        self.assertEqual(names, ["Vet", "Rookie"])

    def test_future_rounds_do_not_count_toward_the_sample(self):
        f = fixture(scorers=[scorer("P", "Broncos", 0.5, 3.0)])
        rows = [("P", r, 2026) for r in (9, 10, 11, 12, 13, 14)]   # only round 9 is before round 10
        out = self.run_build([f], rows, rnd=10)
        self.assertEqual(out["picks"][0]["n_games"], 1)

    def test_try_scorer_stake_is_halved_when_its_team_is_also_picked_to_win(self):
        f = fixture(scorers=[scorer("Star", "Broncos", 0.50, 3.0)], h2h={"our_home_win_prob": 0.70, "market_home_win_prob": 0.55})
        out = self.run_build([f], self.vets("Star"))
        star = next(p for p in out["picks"] if p["market"] == "try_scorer")
        self.assertTrue(star["correlated_with_team_pick"])
        self.assertAlmostEqual(star["stake_weight"], star["kelly_fraction"] * 0.5, places=5)

    def test_no_prices_when_every_fixture_was_skipped(self):
        skipped = {"home_team": "A", "away_team": "B", "status": "skipped: no real upcoming odds-api event found for A v B"}
        out = self.run_build([skipped, dict(skipped)])
        self.assertEqual(out["status"], "no_prices")
        self.assertEqual(out["picks"], [])
        self.assertEqual((out["fixtures_priced"], out["fixtures_total"]), (0, 2))

    def test_no_picks_when_prices_exist_but_nothing_beats_them(self):
        out = self.run_build([fixture(scorers=[scorer("Fav", "Broncos", 0.30, 2.0)])])
        self.assertEqual(out["status"], "no_picks")

    def test_a_skipped_fixture_among_priced_ones_is_ignored(self):
        skipped = {"home_team": "A", "away_team": "B", "status": "skipped: no odds"}
        out = self.run_build([skipped, fixture(scorers=[scorer("P", "Broncos", 0.5, 3.0)])], self.vets("P"))
        self.assertEqual((out["status"], out["fixtures_priced"], out["fixtures_total"]), ("ok", 1, 2))


class WriteAndExit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        (self.d / "nrl_master.csv").write_text("player_name,team,round,season\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def predictions(self, fixtures, rnd=10):
        (self.d / "predictions_current.json").write_text(json.dumps({"season": 2026, "round": rnd, "results": fixtures}), encoding="utf-8")

    def test_ok_week_writes_the_current_file_and_the_history_file_and_exits_0(self):
        self.predictions([fixture(scorers=[scorer("P", "Broncos", 0.5, 3.0)])])
        self.assertEqual(bp.main(["--data-dir", str(self.d)]), 0)
        cur = json.loads((self.d / "weekly_picks.json").read_text())
        hist = json.loads((self.d / "picks_history" / "2026_round_10.json").read_text())
        self.assertEqual(cur["status"], "ok")
        self.assertEqual(hist["picks"], cur["picks"])
        self.assertIn("archived_at", hist)

    def test_no_prices_exits_red_and_archives_nothing(self):
        self.predictions([{"home_team": "A", "away_team": "B", "status": "skipped: no odds"}])
        self.assertEqual(bp.main(["--data-dir", str(self.d)]), bp.EXIT_NO_PRICES)
        self.assertEqual(json.loads((self.d / "weekly_picks.json").read_text())["status"], "no_prices")
        self.assertFalse((self.d / "picks_history").exists())

    def test_no_picks_is_a_normal_week_not_a_failure(self):
        self.predictions([fixture(scorers=[scorer("Fav", "Broncos", 0.30, 2.0)])])
        self.assertEqual(bp.main(["--data-dir", str(self.d)]), 0)
        self.assertEqual(json.loads((self.d / "weekly_picks.json").read_text())["status"], "no_picks")


HISTORY = ROOT / "data" / "predictions_history"


@unittest.skipUnless((HISTORY / "2026_round_19.json").exists(), "saved rounds not present")
class ReplayOfSavedRounds(unittest.TestCase):
    """Rounds 18 and 19 had real prices; rounds 20 and 21 had none (the run was late / the season was over)."""

    def build(self, rnd):
        return bp.build(str(HISTORY / f"2026_round_{rnd}.json"), str(ROOT / "data" / "nrl_master.csv"))

    def test_rounds_18_and_19_give_a_full_ranked_list_of_real_picks(self):
        for rnd in (18, 19):
            out = self.build(rnd)
            self.assertEqual(out["status"], "ok", rnd)
            self.assertEqual(len(out["picks"]), bp.KEEP)
            self.assertTrue(all(p["edge"] > 0 and p["price"] > 1 for p in out["picks"]))
            effs = [p["effective_edge"] for p in out["picks"]]
            self.assertEqual(effs, sorted(effs, reverse=True))
            self.assertIn("try_scorer", {p["market"] for p in out["picks"]})

    def test_rounds_20_and_21_have_no_prices(self):
        for rnd in (20, 21):
            self.assertEqual(self.build(rnd)["status"], "no_prices", rnd)


if __name__ == "__main__":
    unittest.main()
