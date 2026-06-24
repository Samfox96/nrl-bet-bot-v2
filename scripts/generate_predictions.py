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
    real unreliable-exchange-price problem). ALSO includes a real,
    validated predicted MARGIN (nrl_elo.py's expected_margin(), 14-point
    real MAE backtested across 3 held-out years) shown alongside ONE
    real bookmaker's own spread line (default Sportsbet, with a real
    fallback -- see odds_fetcher.extract_single_bookmaker_spread()'s
    docstring) -- NOT a market consensus, since real spreads lines
    aren't standardised across bookmakers (3 distinct real lines
    confirmed for one real match, same problem as totals below). Sam
    explicitly chose "show one real bookmaker's line" over waiting for
    a real line-grouping fix (2026-06-24).
  - player_try_scorer_anytime: xtry_model.py's real per-player
    probability vs real bookmaker "Yes" prices, via edge_finder.py.
  - totals are DELIBERATELY NOT included. Real data confirmed
    2026-06-24 (the Knights v Wests Tigers fixture) that bookmakers
    quote genuinely different lines for this market (2 distinct real
    total points across real bookmakers for the same match) -- the
    same real problem spreads has, but totals doesn't yet have even the
    "read one bookmaker's real line" treatment spreads got. Real future
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
from nrl_elo import build_elo_ratings, expected_win_probability, expected_margin, MARGIN_MAE_POINTS  # noqa: E402
from odds_fetcher import (  # noqa: E402
    get_upcoming_events, resolve_event_for_fixture, fetch_h2h_and_tryscorer_odds,
    extract_h2h_for_consensus, extract_try_scorer_odds, extract_single_bookmaker_spread,
)
from odds_probability import consensus_true_probability  # noqa: E402
from edge_finder import find_edges_for_match  # noqa: E402
from due_flags_v2 import build_due_watch  # noqa: E402

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
    """
    Real player roster for a team, season-to-date.

    REAL BUG FOUND AND FIXED 2026-06-24 (per Sam's real feedback, citing
    a real, confirmed case -- Fletcher Sharpe genuinely played 4
    different real recorded positions this season: Five-Eighth (5
    games), Fullback (3), Centre (2), and the rest unaccounted). The
    original version of this function iterated every real game row in
    round order and OVERWROTE players[name] each time -- meaning the
    dict silently ended up holding whichever position was recorded in
    whatever row happened to be processed LAST (an accident of
    iteration order, not a deliberate choice), which for Fletcher
    Sharpe was Round 16's "Fullback" -- not his most common real
    position, and not necessarily his real position for THIS week
    either. Confirmed real scale of the underlying issue: 291 of 487
    real 2026 players (~60%) have more than one distinct position
    recorded this season -- this wasn't a rare edge case.

    Fixed: this function now returns the MOST FREQUENT real recorded
    position per player as a sane historical baseline (a genuine
    statistical summary, not an arbitrary "last row" accident) --
    but per Sam's real, explicit clarification (2026-06-24): this
    baseline should usually be OVERRIDDEN by resolve_squad_positions()
    below using the real, confirmed team list for the upcoming match
    (parse_team_list.py's real output, the actual source of truth Job B
    polls for and commits weekly) -- this function's job is just "a
    real fallback any squad-building caller can use until/unless a
    confirmed team-list position is available," not the final answer.

    Returns dict: player_name -> most-frequent real position label
    this season (NOT yet alias-resolved to a code -- callers already
    do that via normalise_position()).
    """
    position_counts = defaultdict(lambda: defaultdict(int))
    for r in master_rows:
        if (r["team"] == team_short and r["season"] == str(season)
                and safe_int(r["round"]) < up_to_round):
            position_counts[r["player_name"]][r["position"]] += 1

    players = {}
    for player_name, counts in position_counts.items():
        # Real most-frequent position; ties broken by whichever real
        # position was recorded most RECENTLY among the tied positions
        # (a reasonable real tiebreak -- recency matters more than
        # alphabetical order when two positions are equally common),
        # not by dict insertion order, which Python doesn't guarantee
        # to reflect recency on its own once counts are tied.
        max_count = max(counts.values())
        tied_positions = [p for p, c in counts.items() if c == max_count]
        if len(tied_positions) == 1:
            players[player_name] = tied_positions[0]
        else:
            # Real tiebreak: scan this player's real rows in round
            # order, keep the LAST one whose position is among the tie.
            most_recent_among_tied = None
            for r in master_rows:
                if (r["team"] == team_short and r["season"] == str(season)
                        and safe_int(r["round"]) < up_to_round
                        and r["player_name"] == player_name
                        and r["position"] in tied_positions):
                    most_recent_among_tied = r["position"]
            players[player_name] = most_recent_among_tied
    return players


def load_real_team_list(team_list_csv_path):
    """
    Loads parse_team_list.py's real, confirmed weekly team-list output
    (committed by Job B -- team-list-polling.yml -- as
    data/team_lists_current.csv). Returns dict:
    (team_short, player_name) -> {"position": ..., "jersey_number": ...}.

    Real, confirmed source of truth (per Sam's explicit 2026-06-24
    clarification): team lists land every Tuesday 4pm and are
    re-polled/updated by Job B right up to each match's real kickoff
    (catching real late-mail positional changes) -- this is genuinely
    more current and more accurate than anything derivable from
    historical nrl_master.csv rows, which is why get_squad()'s
    most-frequent-position fallback above should normally be
    OVERRIDDEN by this real data, not the other way around.

    Returns None (not an empty dict) if the file doesn't exist yet --
    explicit signal for resolve_squad_positions() below to fall back
    to historical data and FLAG that it did so, rather than silently
    treating "no file" the same as "file exists but genuinely empty."
    """
    if not os.path.exists(team_list_csv_path):
        return None
    with open(team_list_csv_path) as f:
        rows = list(csv.DictReader(f))
    lookup = {}
    for r in rows:
        key = (r["team"], r["player_name"])
        lookup[key] = {"position": r["position"], "jersey_number": r.get("jersey_number")}
    return lookup


def resolve_squad_positions(historical_squad, team_short, real_team_list):
    """
    Combines get_squad()'s real historical-frequency baseline with the
    real, confirmed team-list position for the upcoming match, per
    Sam's explicit design (2026-06-24): the team list is the real
    source of truth when available; historical data is the fallback.

    Returns (resolved_squad, position_changes) where resolved_squad is
    dict player_name -> position (the one to actually MODEL with), and
    position_changes is a list of real, human-readable strings
    describing every case where the team-list position differs from
    the historical baseline -- per Sam's explicit requirement
    ("major changes in the prediction model need to alert me") this
    list is exactly the real, structured signal a caller can use to
    decide whether to flag something in the digest/email, without this
    function itself deciding what counts as "major enough" to alert on
    (that's a real, separate judgement call for whatever consumes this
    list -- kept here as a complete, unfiltered real record).

    If real_team_list is None (file doesn't exist -- see
    load_real_team_list()'s docstring), returns the historical squad
    UNCHANGED, with a single real flag entry noting the fallback was
    used at all (not which players' positions might be wrong -- that's
    genuinely unknowable without the real team list).
    """
    if real_team_list is None:
        return historical_squad, [
            f"No real team list available for {team_short} this round -- "
            f"using historical most-frequent position as a fallback for "
            f"every player on this team. This should not normally happen "
            f"once real team lists are confirmed (Tuesday 4pm, per the "
            f"established weekly cycle) -- if you're seeing this on a "
            f"genuine Thursday run, check whether Job B (team-list-polling.yml) "
            f"actually ran and committed data/team_lists_current.csv this week."
        ]

    resolved = dict(historical_squad)
    position_changes = []

    for player_name, historical_position in historical_squad.items():
        real_entry = real_team_list.get((team_short, player_name))
        if real_entry is None:
            # Real, confirmed case: a player with historical rows this
            # season who isn't in THIS week's real team list at all
            # (genuinely dropped/injured/rested) -- keep the historical
            # position as a fallback (this function doesn't decide
            # whether to model an absent player at all; that's the
            # caller's job) but don't claim a real confirmed position
            # exists when it doesn't.
            continue
        real_position = real_entry["position"]
        if real_position != historical_position:
            position_changes.append(
                f"{player_name} ({team_short}): historical position "
                f"'{historical_position}' -> real confirmed team-list "
                f"position '{real_position}' (jersey #{real_entry.get('jersey_number')})"
            )
        resolved[player_name] = real_position

    # Real players who ARE in this week's confirmed team list but have
    # NO historical row at all this season (e.g. a real debut, or a
    # real call-up from reserve grade) -- add them too, rather than
    # only ever correcting players already known from history.
    for (list_team, player_name), entry in real_team_list.items():
        if list_team == team_short and player_name not in resolved:
            resolved[player_name] = entry["position"]
            position_changes.append(
                f"{player_name} ({team_short}): new to this week's real "
                f"confirmed team list, no historical 2026 row found -- "
                f"position '{entry['position']}' (jersey #{entry.get('jersey_number')})"
            )

    return resolved, position_changes


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

    # Real DUE WATCH for the whole round (top_n=None -- no truncation --
    # since this needs filtering back down to "due players in fixture X"
    # per game below, not a single round-wide top list). Reuses the
    # exact same Phase 7 weighted baselines already loaded into
    # `baselines` for xtry_model.py's own components -- not a second,
    # separately-computed copy.
    zcr_baseline = load_csv(f"{data_dir}/historical_zcr_baseline.csv")
    position_tpg_baseline = load_csv(f"{data_dir}/historical_position_tpg_baseline.csv")
    try:
        due_watch_all = build_due_watch(
            master_rows, season=season, up_to_round=up_to_round,
            team_aliases=team_aliases, position_aliases=baselines["position_aliases"],
            zcr_baseline=zcr_baseline, position_tpg_baseline=position_tpg_baseline,
            season_draw=season_draw, top_n=None,
            weighted_zcr_lookup=baselines["weighted_zcr"],
            weighted_league_tpg_by_position=baselines["weighted_tpg"],
        )
    except KeyError as e:
        # Same real degrade-don't-break pattern as generate_round_digest.py
        # -- season_draw_2026.json not covering this round shouldn't kill
        # the whole predictions run, just the "due" section.
        due_watch_all = []
        print(f"WARNING: DUE WATCH skipped for predictions -- {e}")

    due_watch_by_team = defaultdict(list)
    for entry in due_watch_all:
        due_watch_by_team[entry["team"]].append(entry)

    # Real, confirmed team-list data for this round, if Job B has
    # already polled and committed it (per Sam's real, explicit
    # 2026-06-24 clarification: team lists land every Tuesday 4pm,
    # confirmed before this script's real Thursday-morning run -- this
    # should always exist for a genuine scheduled run; None here on a
    # real Thursday run would itself be worth investigating, not just
    # silently tolerating). See load_real_team_list()'s docstring for
    # the real fallback behaviour when it's genuinely absent (e.g.
    # manual testing before Tuesday).
    real_team_list = load_real_team_list(f"{data_dir}/team_lists_current.csv")

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

        h2h_odds = extract_h2h_for_consensus(odds_response, team_aliases=team_aliases)
        try_scorer_odds = extract_try_scorer_odds(odds_response)

        # --- h2h via nrl_elo.py ---
        home_short = full_to_short.get(home_full)
        away_short = full_to_short.get(away_full)
        rating_home = elo_ratings.get(home_full, 1500.0)
        rating_away = elo_ratings.get(away_full, 1500.0)
        rating_diff = (rating_home + 46.13) - rating_away
        our_home_win_prob = expected_win_probability(rating_home + 46.13, rating_away)
        our_predicted_margin = expected_margin(rating_diff)
        # Positive = we favour the home team by this many points;
        # negative = we favour the away team. Real MAE for this number
        # is +/-14 points (MARGIN_MAE_POINTS) -- a genuinely large real
        # error bar, always shown alongside the number downstream
        # rather than presented as precise.

        market_bookmaker, market_spread_point, market_spread_price = (
            extract_single_bookmaker_spread(odds_response, home_full, preferred_bookmaker="sportsbet", team_aliases=team_aliases)
        )
        # market_spread_point is the REAL line for the HOME team as that
        # one bookmaker quotes it (e.g. -6.5 means the home team is
        # favoured by 6.5 -- the bookmaker's own point value already
        # uses this sign convention, confirmed real 2026-06-24). Read
        # from ONE real bookmaker only (default Sportsbet, with a real
        # fallback -- see extract_single_bookmaker_spread's docstring
        # for why this isn't pooled across bookmakers).

        if h2h_odds:
            market_consensus = consensus_true_probability(h2h_odds, [home_full, away_full])
            market_home_win_prob = market_consensus.get(home_full)
            # Our own fair odds for the home team, same de-margined-
            # probability-to-decimal-odds conversion already used for
            # try-scorer fair odds elsewhere (1/probability) -- this is
            # OUR number, not the market's, so it's intentionally not
            # run through any bookmaker margin.
            our_home_fair_odds = round(1 / our_home_win_prob, 3) if our_home_win_prob > 0 else None
            our_away_fair_odds = round(1 / (1 - our_home_win_prob), 3) if our_home_win_prob < 1 else None
            h2h_result = {
                "our_home_win_prob": round(our_home_win_prob, 4),
                "market_home_win_prob": (
                    round(market_home_win_prob, 4) if market_home_win_prob else None
                ),
                "our_home_fair_odds": our_home_fair_odds,
                "our_away_fair_odds": our_away_fair_odds,
                "edge": (
                    round(our_home_win_prob - market_home_win_prob, 4)
                    if market_home_win_prob else None
                ),
                "our_predicted_margin": round(our_predicted_margin, 1),
                "margin_mae": MARGIN_MAE_POINTS,
                "market_spread_bookmaker": market_bookmaker,
                "market_spread_point": market_spread_point,
                "market_spread_price": market_spread_price,
                "status": "ok" if market_home_win_prob else "skipped: no real consensus available",
            }
        else:
            h2h_result = {"status": "skipped: no real h2h odds in response"}
        fixture_result["h2h"] = h2h_result

        # --- real DUE WATCH entries for this fixture's two teams ---
        # (computed once for the whole round above; filtered back down
        # to "who's due in THIS specific game" here -- the composite
        # score is comparable across the whole round, so the top 2 per
        # team here are genuinely the most-due, not an arbitrary subset)
        fixture_result["due_watch"] = {
            "home": due_watch_by_team.get(home_short, [])[:2] if home_short else [],
            "away": due_watch_by_team.get(away_short, [])[:2] if away_short else [],
        }

        # --- player try-scorer via xtry_model.py + edge_finder.py ---
        if home_short and away_short:
            home_squad_historical = get_squad(master_rows, home_short, season, up_to_round)
            away_squad_historical = get_squad(master_rows, away_short, season, up_to_round)

            home_squad, home_position_changes = resolve_squad_positions(
                home_squad_historical, home_short, real_team_list
            )
            away_squad, away_position_changes = resolve_squad_positions(
                away_squad_historical, away_short, real_team_list
            )
            # Real, complete record of every case where this week's
            # confirmed team list changed a player's modelled position
            # vs the historical-frequency fallback -- surfaced here so
            # a caller (e.g. send_predictions_digest.py) can decide
            # what's "major" enough to alert on, per Sam's explicit
            # requirement (2026-06-24) that real positional changes
            # should visibly affect predictions, not be silently
            # absorbed.
            fixture_result["position_changes"] = home_position_changes + away_position_changes

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
            # Attach raw_season_tpg from the original raw-score data
            # (already computed by xtry_model.py's Component 1, see
            # calculate_player_xtry_raw's "components" dict) onto each
            # real edge -- added 2026-06-24 specifically so
            # send_predictions_digest.py can show "this player's real
            # season rate is Nx the league average for their position"
            # alongside its is_positionally_unusual flag, rather than
            # just flagging "unusual" with no real number backing it.
            raw_season_tpg_by_player = {
                r["player_name"]: r["components"]["raw_season_tpg"] for r in home_raw + away_raw
            }
            for edge in edge_result["edges"]:
                edge["raw_season_tpg"] = raw_season_tpg_by_player.get(edge["player_name"])

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
                "our_home_fair_odds": h2h.get("our_home_fair_odds"),
                "h2h_edge": h2h.get("edge"),
                "our_predicted_margin": h2h.get("our_predicted_margin"),
                "margin_mae": h2h.get("margin_mae"),
                "market_spread_bookmaker": h2h.get("market_spread_bookmaker"),
                "market_spread_point": h2h.get("market_spread_point"),
            })
            continue

        for e in edges:
            rows.append({
                "home_team": fixture["home_team"],
                "away_team": fixture["away_team"],
                "status": "ok",
                "our_home_win_prob": h2h.get("our_home_win_prob"),
                "market_home_win_prob": h2h.get("market_home_win_prob"),
                "our_home_fair_odds": h2h.get("our_home_fair_odds"),
                "h2h_edge": h2h.get("edge"),
                "our_predicted_margin": h2h.get("our_predicted_margin"),
                "margin_mae": h2h.get("margin_mae"),
                "market_spread_bookmaker": h2h.get("market_spread_bookmaker"),
                "market_spread_point": h2h.get("market_spread_point"),
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
        "our_home_win_prob", "market_home_win_prob", "our_home_fair_odds", "h2h_edge",
        "our_predicted_margin", "margin_mae", "market_spread_bookmaker", "market_spread_point",
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


def write_predictions_json(results, path="data/predictions_current.json"):
    """
    Writes the full, real per-fixture results structure as JSON --
    added 2026-06-24 specifically because the per-game digest sections
    (most-likely-to-score, due, biggest-margin, golden boy) need
    nested, grouped data that doesn't fit cleanly into the flat
    one-row-per-try-scorer-edge CSV shape. write_predictions_csv()
    stays exactly as it was (a flat, greppable snapshot for Sam's
    manual mid-week recheck workflow) -- this is a real, separate
    output for send_predictions_digest.py to build the richer email
    from, not a replacement for the CSV.
    """
    dirname = os.path.dirname(path)
    if dirname:
        os.makedirs(dirname, exist_ok=True)
    with open(path, "w") as f:
        json.dump(results, f, indent=2)
    return path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate real NRL predictions for an upcoming round")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--round", type=int, required=True, dest="round_num")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--output", default="data/predictions_current.csv")
    parser.add_argument("--json-output", default="data/predictions_current.json")
    args = parser.parse_args()

    api_key = os.environ.get("ODDS_API_KEY")
    if not api_key:
        print("ERROR: ODDS_API_KEY environment variable not set.", file=sys.stderr)
        sys.exit(1)

    results = generate_round_predictions(args.season, args.round_num, api_key, args.data_dir)
    path = write_predictions_csv(results, args.output)
    json_path = write_predictions_json(results, args.json_output)

    n_ok = sum(1 for r in results if r["status"] == "ok")
    n_skipped = len(results) - n_ok
    print(f"Processed {len(results)} real fixtures: {n_ok} ok, {n_skipped} skipped")
    for r in results:
        if r["status"] != "ok":
            print(f"  SKIPPED: {r['home_team']} v {r['away_team']} -- {r['status']}")
    print(f"Written to {path}")
    print(f"Written to {json_path}")
