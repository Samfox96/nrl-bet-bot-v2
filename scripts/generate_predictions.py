"""
generate_predictions.py

Phase 8: the top-level script that actually wires xtry_model.py,
nrl_elo.py, odds_fetcher.py, odds_probability.py, and edge_finder.py
together into one real, callable weekly run -- the piece that was
flagged as "not yet wired into the weekly automation pipeline" in
STATUS.md right up until this was built (2026-06-24). Everything this
script calls was independently validated earlier the same day (see each
module's own docstring for its specific validation); this script's job
is ONLY orchestration, not new modelling logic.

REAL SCOPE LOCKED IN 2026-06-24 (deliberately narrower than "every
market"; see STATUS.md's Phase 8 section for the full reasoning):
  - h2h: nrl_elo.py's real, backtested win probability (64.8% avg
    accuracy across 3 held-out years, beats the cited published
    benchmark) vs the real market consensus (odds_probability.py's
    consensus_true_probability(), which already handles Betfair's
    real unreliable-exchange-price problem).
  - player_try_scorer_anytime: xtry_model.py's real per-player
    probability vs real bookmaker "Yes" prices, via edge_finder.py.
  - spreads and totals are DELIBERATELY NOT included. Real data
    confirmed 2026-06-24 (the Knights v Wests Tigers fixture) that
    bookmakers quote genuinely different lines for both markets (3
    distinct spread points, 2 distinct total points across real
    bookmakers for the same match) -- naively pooling these into one
    consensus would compare different bets, not find a real edge. A
    real fix (grouping by point value before pooling) is real future
    work, not built here.
  - player_try_scorer_first/last are DELIBERATELY NOT included. Real
    data confirmed these carry a ~97% bookmaker margin (neither clean
    like h2h's ~5% nor independent like anytime's uncapped sum) --
    too uncertain to trust a de-margined comparison against without
    further real validation.

WHAT THIS SCRIPT DOES:
  1. For every real fixture in the upcoming round (from
     season_draw_2026.json's real fixture list, matched against
     odds_fetcher.get_upcoming_events() via team_aliases.json):
     a. Fetches real h2h + player_try_scorer_anytime odds.
     b. Computes nrl_elo.py's real win probability for both teams.
     c. Computes xtry_model.py's real per-player try-scoring
        probability for every eligible player on both squads.
     d. Calls edge_finder.find_edges_for_match() for the try-scorer
        comparison, and a parallel (simpler, no name-matching needed)
        h2h comparison using odds_probability's consensus function.
  2. Writes everything to data/predictions_current.csv -- the
     committed snapshot Sam reads when asking for a manual mid-week
     odds recheck, per his own stated workflow (avoids needing to
     regenerate xtry_model's real output from scratch every time).

GRACEFUL DEGRADATION (matching generate_round_digest.py's own
established pattern -- a degraded section beats no digest at all):
  - If a real fixture's odds can't be fetched (API error, event not
    found), that fixture is skipped with a logged reason, not a hard
    failure of the whole run -- the other real fixtures still get
    processed.
  - The two real models (Elo for h2h, xTry for try-scorer) are kept
    fully independent -- one's failure never blocks the other. This
    mirrors nrl_elo.py's own documented finding that blending them
    does NOT help; there's no real reason one's failure should block
    the other either.

REAL CREDIT BUDGET (confirmed 2026-06-24 against Sam's actual account):
  1 credit per (market x region). This script requests 2 markets
  (h2h, player_try_scorer_anytime) x 1 region (au) = 2 credits per
  real fixture. An 8-match round = 16 credits. Free tier is 500
  credits/month -- confirmed comfortable headroom for once-per-round
  automated runs AND Sam's separate stated workflow of asking for
  manual mid-week rechecks.
"""

import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from xtry_model import (  # noqa: E402
    load_csv, load_json, safe_int, normalise_position,
    build_player_game_log, build_team_games_played, build_team_overall_zcr,
    build_team_ruck_speeds, calculate_player_xtry_raw, compute_real_avg_tries_per_team_per_game,
)
from recency_weighted_baselines import build_weighted_tpg_baseline, build_weighted_zcr_baseline  # noqa: E402
from nrl_elo import build_elo_ratings, expected_win_probability  # noqa: E402
from odds_fetcher import (  # noqa: E402
    get_upcoming_events, resolve_event_for_fixture, fetch_h2h_and_tryscorer_odds,
    extract_h2h_for_consensus, extract_try_scorer_odds,
)
from odds_probability import consensus_true_probability  # noqa: E402
from edge_finder import find_edges_for_match  # noqa: E402

from collections import defaultdict


def load_real_baselines(data_dir="data"):
    """
    Loads every real data source the prediction pipeline needs, once,
    so a single round's run doesn't re-read the same files per fixture.
    Mirrors generate_round_digest.py's file-path-driven loading
    pattern -- every path is a parameter with a sensible real default,
    not hardcoded inline, so this is testable against the local build
    directory's copies the same way every module was validated earlier
    today.
    """
    master_rows = load_csv(f"{data_dir}/nrl_master.csv")
    position_tpg_baseline = load_csv(f"{data_dir}/historical_position_tpg_baseline.csv")
    player_match_rows = load_csv(f"{data_dir}/historical_player_match_rows.csv")
    zcr_baseline = load_csv(f"{data_dir}/historical_zcr_baseline.csv")
    team_aliases = load_json(f"{data_dir}/team_aliases.json")["aliases"]
    position_aliases = load_json(f"{data_dir}/position_aliases.json")["aliases"]
    match_rows = load_csv(f"{data_dir}/match_data_FINAL_fixed.csv")

    weighted_tpg = build_weighted_tpg_baseline(position_tpg_baseline)
    weighted_zcr = build_weighted_zcr_baseline(player_match_rows)

    league_avg_zcr_by_position = defaultdict(list)
    for row in zcr_baseline:
        league_avg_zcr_by_position[row["position"]].append(float(row["concede_rate"]))
    league_avg_zcr_by_position = {
        k: sum(v) / len(v) for k, v in league_avg_zcr_by_position.items()
    }

    position_games_by_team = defaultdict(lambda: defaultdict(int))
    for row in player_match_rows:
        position_games_by_team[row["opposition_team"]][row["position"]] += 1
    team_overall_zcr, league_avg_overall_zcr = build_team_overall_zcr(
        weighted_zcr, position_games_by_team
    )

    return {
        "master_rows": master_rows,
        "team_aliases": team_aliases,
        "position_aliases": position_aliases,
        "weighted_tpg": weighted_tpg,
        "weighted_zcr": weighted_zcr,
        "league_avg_zcr_by_position": league_avg_zcr_by_position,
        "team_overall_zcr": team_overall_zcr,
        "league_avg_overall_zcr": league_avg_overall_zcr,
        "match_rows": match_rows,
    }


def get_squad(master_rows, team_short, season, up_to_round):
    """Real player roster for a team, season-to-date (same pattern as
    every test harness used to validate xtry_model.py earlier today)."""
    players = {}
    for r in master_rows:
        if (r["team"] == team_short and r["season"] == str(season)
                and safe_int(r["round"]) < up_to_round):
            players[r["player_name"]] = r["position"]
    return players


def build_raw_scores(baselines, by_player, team_games_played, team_season_tries,
                      attacking_speed, speed_allowed, squad, team_short,
                      opponent_full, is_home):
    """One team's full set of real per-player xTry raw scores for one
    upcoming match, reusing the exact validated pattern from this
    session's test harnesses -- not a new code path."""
    raw_scores = []
    for player_name, pos_label in squad.items():
        games = by_player.get(player_name, [])
        if len(games) < 3:
            continue
        pos_code = normalise_position(pos_label, baselines["position_aliases"])
        if pos_code is None:
            continue
        result = calculate_player_xtry_raw(
            player_name, games, pos_code, team_short, opponent_full, is_home,
            baselines["weighted_tpg"], baselines["weighted_zcr"],
            baselines["league_avg_zcr_by_position"],
            team_season_tries.get(team_short, 0), attacking_speed, speed_allowed,
            baselines["team_overall_zcr"], baselines["league_avg_overall_zcr"],
            team_games_played=team_games_played.get(team_short),
        )
        raw_scores.append(result)
    return raw_scores


def generate_round_predictions(season, up_to_round, the_odds_api_key, data_dir="data"):
    """
    Top-level entry point. Returns a list of per-fixture result dicts:
      {
        "home_team": ..., "away_team": ...,
        "h2h": {"our_home_win_prob": ..., "market_home_win_prob": ...,
                 "edge": ..., "status": "ok" | "skipped: <reason>"},
        "try_scorer_edges": [... edge_finder.py's real output ...],
        "status": "ok" | "skipped: <reason>"   (fixture-level)
      }

    GRACEFUL DEGRADATION: a fixture that fails (odds fetch error, no
    real event match found) is included in the output with a "skipped"
    status and reason, not silently dropped -- so a human reviewing
    predictions_current.csv can see exactly what happened for every
    real fixture, not just the ones that succeeded.
    """
    baselines = load_real_baselines(data_dir)
    master_rows = baselines["master_rows"]
    team_aliases = baselines["team_aliases"]

    season_draw = load_json(f"{data_dir}/season_draw_2026.json")
    round_key = str(up_to_round)
    if round_key not in season_draw.get("rounds", {}):
        raise ValueError(
            f"Round {up_to_round} not found in season_draw_2026.json's real "
            f"fixture list -- confirm the draw file actually covers this "
            f"round before running (it's confirmed to only cover rounds "
            f"17-18 as of 2026-06-24; extend it before using this for a "
            f"later round)."
        )
    fixtures = season_draw["rounds"][round_key]["fixtures"]

    by_player = build_player_game_log(master_rows, season, up_to_round)
    team_games_played = build_team_games_played(master_rows, season, up_to_round)
    attacking_speed, speed_allowed = build_team_ruck_speeds(master_rows, season, up_to_round)
    real_avg_tries = compute_real_avg_tries_per_team_per_game(master_rows, season, up_to_round)

    team_season_tries = defaultdict(int)
    for r in master_rows:
        if r["season"] == str(season) and safe_int(r["round"]) < up_to_round:
            team_season_tries[r["team"]] += safe_int(r["tries"])

    real_short_names = set(r["team"] for r in master_rows)
    full_to_short = {}
    for short in real_short_names:
        full = team_aliases.get(short)
        if full:
            full_to_short[full] = short

    elo_ratings = build_elo_ratings(baselines["match_rows"], team_aliases)

    real_events = get_upcoming_events(the_odds_api_key)

    results = []

    for home_full, away_full in fixtures:
        fixture_result = {"home_team": home_full, "away_team": away_full}

        event = resolve_event_for_fixture(real_events, home_full, away_full, team_aliases)
        if event is None:
            fixture_result["status"] = (
                f"skipped: no real upcoming odds-api event found for "
                f"{home_full} v {away_full}"
            )
            results.append(fixture_result)
            continue

        try:
            odds_response = fetch_h2h_and_tryscorer_odds(the_odds_api_key, event["id"])
        except Exception as e:
            fixture_result["status"] = f"skipped: odds fetch failed -- {e}"
            results.append(fixture_result)
            continue

        h2h_odds = extract_h2h_for_consensus(odds_response)
        try_scorer_odds = extract_try_scorer_odds(odds_response)

        # --- h2h via nrl_elo.py ---
        home_short = full_to_short.get(home_full)
        away_short = full_to_short.get(away_full)
        rating_home = elo_ratings.get(home_full, 1500.0)
        rating_away = elo_ratings.get(away_full, 1500.0)
        our_home_win_prob = expected_win_probability(rating_home + 46.13, rating_away)

        if h2h_odds:
            market_consensus = consensus_true_probability(h2h_odds, [home_full, away_full])
            market_home_win_prob = market_consensus.get(home_full)
            h2h_result = {
                "our_home_win_prob": round(our_home_win_prob, 4),
                "market_home_win_prob": (
                    round(market_home_win_prob, 4) if market_home_win_prob else None
                ),
                "edge": (
                    round(our_home_win_prob - market_home_win_prob, 4)
                    if market_home_win_prob else None
                ),
                "status": "ok" if market_home_win_prob else "skipped: no real consensus available",
            }
        else:
            h2h_result = {"status": "skipped: no real h2h odds in response"}
        fixture_result["h2h"] = h2h_result

        # --- player try-scorer via xtry_model.py + edge_finder.py ---
        if home_short and away_short:
            home_squad = get_squad(master_rows, home_short, season, up_to_round)
            away_squad = get_squad(master_rows, away_short, season, up_to_round)
            home_raw = build_raw_scores(
                baselines, by_player, team_games_played, team_season_tries,
                attacking_speed, speed_allowed, home_squad, home_short, away_full, True
            )
            away_raw = build_raw_scores(
                baselines, by_player, team_games_played, team_season_tries,
                attacking_speed, speed_allowed, away_squad, away_short, home_full, False
            )
            edge_result = find_edges_for_match(
                home_raw, away_raw, real_avg_tries, try_scorer_odds
            )
            fixture_result["try_scorer_edges"] = edge_result["edges"]
            fixture_result["try_scorer_unmatched_in_model"] = edge_result["unmatched_in_model"]
        else:
            fixture_result["try_scorer_edges"] = []
            fixture_result["try_scorer_unmatched_in_model"] = []
            fixture_result["try_scorer_status"] = (
                f"skipped: could not resolve short team name for "
                f"{'home' if not home_short else 'away'} side"
            )

        fixture_result["status"] = "ok"
        results.append(fixture_result)

    return results


def write_predictions_csv(results, path="data/predictions_current.csv"):
    """
    Flattens the real per-fixture results into one CSV row per
    try-scorer edge (the most granular real output), plus the h2h
    comparison repeated on every row for that fixture so a human
    scanning the file sees both views together without a second file.
    This is the file Sam's own stated workflow (manual mid-week
    recheck) reads from -- written fresh each real run, not appended.
    """
    rows = []
    for fixture in results:
        if fixture["status"] != "ok":
            rows.append({
                "home_team": fixture["home_team"],
                "away_team": fixture["away_team"],
                "status": fixture["status"],
            })
            continue

        h2h = fixture.get("h2h", {})
        edges = fixture.get("try_scorer_edges", [])

        if not edges:
            rows.append({
                "home_team": fixture["home_team"],
                "away_team": fixture["away_team"],
                "status": "ok (no try-scorer edges -- no real odds matched)",
                "our_home_win_prob": h2h.get("our_home_win_prob"),
                "market_home_win_prob": h2h.get("market_home_win_prob"),
                "h2h_edge": h2h.get("edge"),
            })
            continue

        for e in edges:
            rows.append({
                "home_team": fixture["home_team"],
                "away_team": fixture["away_team"],
                "status": "ok",
                "our_home_win_prob": h2h.get("our_home_win_prob"),
                "market_home_win_prob": h2h.get("market_home_win_prob"),
                "h2h_edge": h2h.get("edge"),
                "player_name": e["player_name"],
                "player_team": e["team"],
                "position_code": e["position_code"],
                "bookmaker": e["bookmaker"],
                "our_try_probability": e["our_probability"],
                "market_try_probability": e["market_probability"],
                "try_scorer_edge": e["edge"],
                "fair_odds": e.get("fair_odds_implied_by_our_model"),
            })

    fieldnames = [
        "home_team", "away_team", "status",
        "our_home_win_prob", "market_home_win_prob", "h2h_edge",
        "player_name", "player_team", "position_code", "bookmaker",
        "our_try_probability", "market_try_probability", "try_scorer_edge", "fair_odds",
    ]
    dirname = os.path.dirname(path)
    if dirname:
        os.makedirs(dirname, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate real NRL predictions for an upcoming round")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--round", type=int, required=True, dest="round_num")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--output", default="data/predictions_current.csv")
    args = parser.parse_args()

    api_key = os.environ.get("ODDS_API_KEY")
    if not api_key:
        print("ERROR: ODDS_API_KEY environment variable not set.", file=sys.stderr)
        sys.exit(1)

    results = generate_round_predictions(args.season, args.round_num, api_key, args.data_dir)
    path = write_predictions_csv(results, args.output)

    n_ok = sum(1 for r in results if r["status"] == "ok")
    n_skipped = len(results) - n_ok
    print(f"Processed {len(results)} real fixtures: {n_ok} ok, {n_skipped} skipped")
    for r in results:
        if r["status"] != "ok":
            print(f"  SKIPPED: {r['home_team']} v {r['away_team']} -- {r['status']}")
    print(f"Written to {path}")
