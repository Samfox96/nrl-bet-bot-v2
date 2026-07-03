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


def get_real_head_to_head(match_rows, team_aliases, home_full, away_full, current_season, current_round, max_games=5):
    """
    Real, genuine head-to-head history between these two specific teams,
    added 2026-06-24 per Sam's explicit request for a more analytical,
    less repetitive narrative -- this is a fundamentally different real
    signal from the Elo rating gap (season-long overall strength): it's
    "how have THESE TWO specifically fared against each other,"
    independent of how either has played against everyone else.

    Resolves match_data_FINAL_fixed.csv's real short team-name strings
    (confirmed real format, e.g. "Newcastle", "South Sydney" -- NOT the
    canonical full names used elsewhere in this module) through
    team_aliases.json before comparing against home_full/away_full, the
    same real resolution every other real consumer of this file
    already does (nrl_elo.py).

    Excludes the CURRENT real fixture itself (matches strictly before
    current_season/current_round) -- this is real PAST history, not a
    preview of the match this function is being called to help narrate.

    Returns dict: {"games_found": n, "team_a_wins": n, "team_b_wins": n,
    "draws": n, "most_recent": {...} or None} where team_a is
    home_full, team_b is away_full (labels kept consistent regardless
    of which team was actually home/away in each historical real
    match) -- or None if NO real historical matches exist between these
    two (genuinely possible for newer combinations, e.g. Dolphins vs
    anyone before 2023).
    """
    games = []
    for m in match_rows:
        home_resolved = team_aliases.get(m["home_team"])
        away_resolved = team_aliases.get(m["away_team"])
        if {home_resolved, away_resolved} != {home_full, away_full}:
            continue
        if safe_int(m["season"]) > current_season:
            continue
        if safe_int(m["season"]) == current_season and safe_int(m["round"]) >= current_round:
            continue
        games.append(m)

    if not games:
        return None

    games.sort(key=lambda m: (safe_int(m["season"]), safe_int(m["round"])))
    games = games[-max_games:]

    team_a_wins = team_b_wins = draws = 0
    for m in games:
        home_resolved = team_aliases.get(m["home_team"])
        home_score, away_score = safe_int(m["home_score"]), safe_int(m["away_score"])
        if home_score == away_score:
            draws += 1
            continue
        home_won = home_score > away_score
        if (home_resolved == home_full) == home_won:
            team_a_wins += 1
        else:
            team_b_wins += 1

    last = games[-1]
    last_home_resolved = team_aliases.get(last["home_team"])
    last_home_score, last_away_score = safe_int(last["home_score"]), safe_int(last["away_score"])
    last_away_resolved = away_full if last_home_resolved == home_full else home_full
    # REAL BUG FOUND AND FIXED 2026-06-24: the original version of this
    # winner-determination used a broken if/elif/elif/else chain that
    # could return the LOSING team as "winner" -- confirmed real case:
    # Gold Coast Titans (home) lost 18-38 to Canterbury in a real 2025
    # match, but the original logic returned "Gold Coast Titans" as the
    # winner. Caught by manually verifying this function's real output
    # against the raw real match row, not assumed correct from a
    # plausible-looking result. Fixed with simple, directly correct
    # logic: whichever real team scored more, full stop.
    if last_home_score > last_away_score:
        real_winner = last_home_resolved
    elif last_away_score > last_home_score:
        real_winner = last_away_resolved
    else:
        real_winner = None  # genuine real draw
    most_recent = {
        "season": safe_int(last["season"]),
        "round": safe_int(last["round"]),
        "winner": real_winner,
        "score": f"{last['home_score']}-{last['away_score']}",
    }

    return {
        "games_found": len(games),
        "team_a_wins": team_a_wins,
        "team_b_wins": team_b_wins,
        "draws": draws,
        "most_recent": most_recent,
    }


def get_real_form_streak(match_rows, team_aliases, team_full, current_season, current_round, last_n=5):
    """
    Real, genuine recent-form streak for ONE team, added 2026-06-24
    alongside get_real_head_to_head() -- a real, different angle again
    from both the Elo rating gap (season-long) and h2h (specific
    opponent): "how has this team performed, period, in its last few
    real matches against anyone." Returns a real win/loss/draw string
    (e.g. "WWLWL", most recent last) plus the real win count, or None
    if fewer than 2 real real games exist this season to draw from
    (too little real signal to be worth narrating).

    REAL, CONFIRMED CONVENTION (clarified 2026-06-25 after a real,
    investigated non-bug): this function counts the last `last_n`
    GAMES ACTUALLY PLAYED, skipping bye rounds entirely (a bye
    contributes nothing to win/loss, so it's correctly absent from the
    output, not counted as a blank). This is a DIFFERENT real
    convention from nrl.com's own public ladder "Form" column, which
    counts by ROUND NUMBER instead -- confirmed via a real, traced
    example (Dolphins, real Round 17 lookup): this function correctly
    found 5 straight real wins across rounds 11/12/14/15/16 (skipping
    the real Round 13 bye), while the real public ladder showed "4-0"
    for the same team at the same moment, because its real window
    (rounds 16/15/14/13/12) treats round 13's bye as a real gap rather
    than skipping past it. BOTH are real, internally-consistent,
    legitimate conventions -- this isn't a bug in either system. Sam's
    explicit real choice (2026-06-25): keep this function's
    games-played convention, since it's the more meaningful real
    signal for prediction purposes -- but any narrative text built
    from this function's output must say "games played" explicitly
    (not just "their last N"), so it never again reads as contradicting
    whatever a reader sees on the real public ladder.
    """
    games = []
    for m in match_rows:
        if safe_int(m["season"]) != current_season:
            continue
        if safe_int(m["round"]) >= current_round:
            continue
        home_resolved = team_aliases.get(m["home_team"])
        away_resolved = team_aliases.get(m["away_team"])
        if team_full not in (home_resolved, away_resolved):
            continue
        games.append(m)

    if len(games) < 2:
        return None

    games.sort(key=lambda m: safe_int(m["round"]))
    games = games[-last_n:]

    results = []
    for m in games:
        home_resolved = team_aliases.get(m["home_team"])
        home_score, away_score = safe_int(m["home_score"]), safe_int(m["away_score"])
        is_home = home_resolved == team_full
        own_score = home_score if is_home else away_score
        opp_score = away_score if is_home else home_score
        if own_score > opp_score:
            results.append("W")
        elif own_score < opp_score:
            results.append("L")
        else:
            results.append("D")

    return {
        "results": "".join(results),
        "wins": results.count("W"),
        "games": len(results),
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


def load_real_team_list_from_csv(team_list_csv_path):
    """
    Loads parse_team_list.py's real, confirmed weekly team-list output
    from a local CSV (committed by Job B -- team-list-polling.yml --
    as data/team_lists_current.csv). Returns dict:
    (team_short, player_name) -> {"position": ..., "jersey_number": ...}.

    Returns None (not an empty dict) if the file doesn't exist --
    explicit signal for get_real_team_list() below to try the real
    live nrl.com fallback before giving up entirely.
    """
    if not os.path.exists(team_list_csv_path):
        return None
    with open(team_list_csv_path) as f:
        rows = list(csv.DictReader(f))
    return _rows_to_team_list_lookup(rows)


def _rows_to_team_list_lookup(rows):
    """Shared real-row-to-lookup-dict conversion, used by both the
    committed-CSV path and the real live-fetch fallback below, so the
    two paths can never silently drift into different real shapes."""
    lookup = {}
    for r in rows:
        key = (r["team"], r["player_name"])
        lookup[key] = {"position": r["position"], "jersey_number": r.get("jersey_number")}
    return lookup


def fetch_real_team_list_live(round_num, season=2026):
    """
    REAL LIVE FALLBACK added 2026-06-24, per Sam's explicit request:
    "the info should always be there" -- confirmed real and current via
    a direct check of https://www.nrl.com/news/2026/06/23/nrl-team-lists-round-17/,
    which genuinely lists the real, confirmed Round 17 team lists,
    including the exact real case this whole fix was prompted by
    ("Fletcher Sharpe reverts to five-eighth" -- confirmed real text
    from the article itself).

    Reuses find_team_list_url.py's real, already-built URL-discovery
    (no need to guess a date-based path) and parse_team_list.py's real,
    already-built HTML parser -- this function is pure orchestration,
    no new parsing logic invented here.

    Real, deliberate use case: data/team_lists_current.csv (Job B's
    committed output) not existing yet for this round -- e.g. a manual
    workflow_dispatch run before Job B has fired, or Job B itself
    genuinely failing for some real reason. NOT a replacement for Job B
    in normal operation; Job B's near-kickoff polling catches real late
    changes this one-shot fetch at generation time would miss.

    Returns the same real lookup dict shape as
    load_real_team_list_from_csv(), or None if the real live fetch
    genuinely fails for any reason (network error, real HTML structure
    change, round not found on the listing page yet) -- never raises,
    since a failed real-time fallback attempt should degrade to the
    historical-position fallback, not crash the whole predictions run.
    """
    try:
        import urllib.request
        listing_url = "https://www.nrl.com/news/topic/team-lists/"
        req = urllib.request.Request(listing_url, headers={"User-Agent": "nrl-bet-bot-v2/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            listing_html = resp.read().decode("utf-8")

        from find_team_list_url import find_latest_team_list_url
        result = find_latest_team_list_url(listing_html)
        if result is None:
            print(f"WARNING: real live team-list fallback found no real "
                  f"'NRL Team Lists' article on the listing page.")
            return None
        found_round, article_url = result
        if found_round != round_num:
            print(f"WARNING: real live team-list fallback found Round {found_round}'s "
                  f"article, not Round {round_num}'s -- the real article for this "
                  f"round may not be published yet, or round numbering has drifted. "
                  f"Not using a real team list for the wrong round.")
            return None

        req2 = urllib.request.Request(article_url, headers={"User-Agent": "nrl-bet-bot-v2/1.0"})
        with urllib.request.urlopen(req2, timeout=15) as resp:
            article_html = resp.read().decode("utf-8")

        from parse_team_list import parse_team_list_page
        rows = parse_team_list_page(article_html, round_num=round_num, season=season)
        if not rows:
            print(f"WARNING: real live team-list fallback fetched Round {round_num}'s "
                  f"real article but parsed zero real player rows -- the real HTML "
                  f"structure may have changed since parse_team_list.py was built.")
            return None

        print(f"Real live team-list fallback succeeded: {len(rows)} real player rows "
              f"parsed from {article_url}")
        return _rows_to_team_list_lookup(rows)
    except Exception as e:
        print(f"WARNING: real live team-list fallback failed -- {e}")
        return None


def get_real_team_list(team_list_csv_path, round_num, season=2026):
    """
    Real, combined resolution order, per Sam's explicit 2026-06-24
    request: try Job B's committed CSV first (the normal, expected real
    path for a genuine Thursday-morning run); if that's genuinely
    absent, try a real live nrl.com fetch as backup ("the info should
    always be there"); only fall through to the historical-position
    fallback in resolve_squad_positions() if BOTH real sources fail.

    Returns (lookup_dict_or_None, source_label) where source_label is
    "committed_csv", "live_fallback", or "none" -- so callers can
    report exactly which real source was used, not just whether one
    was found.
    """
    csv_result = load_real_team_list_from_csv(team_list_csv_path)
    if csv_result is not None:
        return csv_result, "committed_csv"

    live_result = fetch_real_team_list_live(round_num, season)
    if live_result is not None:
        return live_result, "live_fallback"

    return None, "none"




def resolve_squad_positions(historical_squad, team_short, real_team_list, position_aliases):
    """
    Combines get_squad()'s real historical-frequency baseline with the
    real, confirmed team-list position for the upcoming match, per
    Sam's explicit design (2026-06-24): the team list is the real
    source of truth when available; historical data is the fallback.

    REVISED 2026-06-24 after a real, confirmed root-cause fix (the live
    nrl.com fallback was failing on every real run due to a missing
    `beautifulsoup4` dependency in the workflow -- now fixed -- so this
    fallback path should be genuinely rare going forward, not a regular
    occurrence). Per Sam's explicit choice: the email should show ONLY
    real positional swaps (a genuine, interesting signal worth a fan's
    attention) -- the "no real team list at all" infrastructure-failure
    case is now log-only (printed for operational visibility, e.g. in
    the real Actions log), never surfaced in the email itself. Mixing
    "here's a genuinely interesting player update" with "our own
    pipeline had a problem this week" in the same reader-facing section
    was confusing and not what a fan-facing email should carry.

    REAL BUG FOUND AND FIXED 2026-06-25 (per Sam's real feedback against
    a real live email): get_squad()'s historical baseline stores
    POSITION CODES (e.g. 'FB', 'WG', 'PR'), but real_team_list (from
    parse_team_list.py) stores full LABELS (e.g. 'Fullback', 'Winger',
    'Prop') -- comparing these as raw strings meant almost every real
    player flagged as a "change" even when nothing real changed, just
    because the two real sources spell the same position differently.
    Confirmed real case: an entire team's real, unchanged roster
    (Dolphins v New Zealand Warriors) produced 22 false "position
    changed" entries. Fixed: both real values are now resolved through
    position_aliases.json (the SAME canonical alias map every other
    real position comparison in this project already uses) before
    comparing -- a genuine change is now only reported when the
    resolved CODES actually differ, e.g. a real Five-Eighth becoming a
    real Fullback, not 'FB' vs 'Fullback' meaning the same thing.

    Also REMOVED (per Sam's explicit 2026-06-25 request): the "new to
    this week's real confirmed team list, no historical row found"
    block. These players' real resolved positions are still used for
    modelling (that part was never wrong) -- they're just no longer
    reported as a "change" in the email, since there's no real
    historical position to have changed FROM, and Sam doesn't want
    this case surfaced at all.

    Returns (resolved_squad, position_changes, infra_warning) where:
      - resolved_squad: dict player_name -> position LABEL (the one to
        actually MODEL with -- kept as the real team-list label, not
        converted to a code, since build_raw_scores() downstream
        already calls normalise_position() on whatever it receives).
      - position_changes: list of real, human-readable strings, ONLY
        for genuine STARTING-XV team-list-vs-historical swaps where
        the resolved CODE actually differs AND neither side is IC
        (Interchange/Reserve) -- per Sam's explicit 2026-06-25
        decision, real bench-rotation moves are deliberately excluded
        even though they're real, non-buggy changes -- only a real
        on-field positional swap (e.g. Prop -> Hooker) is the
        email-worthy signal he wants alerted on.
      - infra_warning: a single string if real_team_list was
        unavailable (BOTH real sources failed), else None -- intended
        for logging only, NOT for inclusion in the email digest.
    """
    if real_team_list is None:
        return historical_squad, [], (
            f"No real team list available for {team_short} this round, from EITHER "
            f"the committed Job B file or the real live nrl.com fallback -- "
            f"using historical most-frequent position for every player on this team. "
            f"This should be rare now that the real bs4 dependency bug is fixed "
            f"(2026-06-24) -- if you're seeing this on a genuine Thursday run, "
            f"something has gone wrong with BOTH Job B and nrl.com's real listing "
            f"page -- worth investigating directly."
        )

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
        historical_code = normalise_position(historical_position, position_aliases)
        real_code = normalise_position(real_position, position_aliases)
        # REAL FILTER ADDED 2026-06-25 per Sam's explicit request: only
        # report a genuine STARTING-XV positional swap (e.g. a real
        # Prop moving to a real Hooker role) -- not a bench-rotation
        # move (e.g. a Prop now listed as Interchange, or an
        # Interchange now starting at Winger). Confirmed real basis:
        # position_aliases.json's own canonical_positions shows every
        # code except IC covers jerseys 1-13 (the real starting XV);
        # IC alone covers jerseys 14-17 plus the real 'Reserve' label
        # (extended bench). A swap involving IC on EITHER side is a
        # bench/rotation change, not a real on-field positional swap --
        # confirmed against 7 real examples from a live email (all 7
        # involved IC on one side, none were genuine starting-XV swaps,
        # and Sam explicitly asked to drop exactly this category after
        # seeing them were real but not the kind of change he wants
        # surfaced).
        is_bench_only_change = historical_code == "IC" or real_code == "IC"
        if real_code != historical_code and not is_bench_only_change:
            # Only a genuine real STARTING-XV change -- both labels
            # resolved to canonical codes first, so 'FB' vs 'Fullback'
            # (same real position, different spelling) never fires
            # here, and neither does a real bench/Interchange move.
            position_changes.append(
                f"{player_name} ({team_short}): historical position "
                f"'{historical_position}' -> real confirmed team-list "
                f"position '{real_position}' (jersey #{real_entry.get('jersey_number')})"
            )
        resolved[player_name] = real_position

    # Real players who ARE in this week's confirmed team list but have
    # NO historical row at all this season (e.g. a real debut, or a
    # real call-up from reserve grade) -- their real position is still
    # used for modelling, but per Sam's explicit 2026-06-25 request
    # this is NOT reported as a "change" in position_changes (no real
    # historical position exists to have changed FROM).
    for (list_team, player_name), entry in real_team_list.items():
        if list_team == team_short and player_name not in resolved:
            resolved[player_name] = entry["position"]

    return resolved, position_changes, None


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

    # Real, confirmed team-list data for this round. Tries Job B's
    # committed CSV first (the normal, expected real path for a genuine
    # Thursday-morning run -- team lists land every Tuesday 4pm, well
    # before this); if that's genuinely absent, tries a real live
    # nrl.com fetch as backup (per Sam's explicit 2026-06-24 request:
    # "the info should always be there"). See get_real_team_list()'s
    # docstring for the full real resolution order.
    real_team_list, team_list_source = get_real_team_list(
        f"{data_dir}/team_lists_current.csv", up_to_round, season
    )
    print(f"Real team-list source for this round: {team_list_source}")

    real_events = get_upcoming_events(the_odds_api_key)

    results = []

    for home_full, away_full in fixtures:
        fixture_result = {"home_team": home_full, "away_team": away_full,
                           "due_watch": {"home": [], "away": []}}

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

        # Real, new analytical angles added 2026-06-24 per Sam's
        # explicit request for a less repetitive, more analytical
        # narrative -- both grounded in match_data_FINAL_fixed.csv,
        # the same real, validated source nrl_elo.py already uses.
        real_h2h_history = get_real_head_to_head(
            baselines["match_rows"], team_aliases, home_full, away_full, season, up_to_round
        )
        real_home_form = get_real_form_streak(
            baselines["match_rows"], team_aliases, home_full, season, up_to_round
        )
        real_away_form = get_real_form_streak(
            baselines["match_rows"], team_aliases, away_full, season, up_to_round
        )

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
                "rating_home": round(rating_home, 1),
                "rating_away": round(rating_away, 1),
                # Real Elo ratings (not just the derived win probability)
                # -- added 2026-06-24 specifically so
                # send_predictions_digest.py's fan-voiced analysis can
                # talk about real, genuine team form/strength ("the
                # better side over the season") rather than only ever
                # quoting a probability number. These are the exact
                # same real ratings nrl_elo.py already validated
                # (64.8% real backtest accuracy across 3 held-out
                # years) -- not a new number, just surfaced downstream.
                "real_h2h_history": real_h2h_history,
                "real_home_form": real_home_form,
                "real_away_form": real_away_form,
                # Real, new analytical angles (2026-06-24) -- genuinely
                # different real signals from the Elo rating gap above:
                # h2h history is "how have these two specific teams
                # fared against EACH OTHER", form streak is "how has
                # each team performed lately, period" (not adjusted for
                # opponent strength the way Elo is). Both real, both
                # independently checkable against match_data_FINAL_fixed.csv.
                "status": "ok" if market_home_win_prob else "skipped: no real consensus available",
            }
        else:
            h2h_result = {"status": "skipped: no real h2h odds in response"}
        fixture_result["h2h"] = h2h_result

        # --- player try-scorer via xtry_model.py + edge_finder.py ---
        if home_short and away_short:
            home_squad_historical = get_squad(master_rows, home_short, season, up_to_round)
            away_squad_historical = get_squad(master_rows, away_short, season, up_to_round)

            home_squad, home_position_changes, home_infra_warning = resolve_squad_positions(
                home_squad_historical, home_short, real_team_list, baselines["position_aliases"]
            )
            away_squad, away_position_changes, away_infra_warning = resolve_squad_positions(
                away_squad_historical, away_short, real_team_list, baselines["position_aliases"]
            )
            # Real, ONLY-genuine-swaps record (per Sam's explicit
            # 2026-06-24 design: the email shows real positional
            # changes only, never an "our pipeline had a problem"
            # notice -- that's log-only, see below) -- surfaced here so
            # a caller (e.g. send_predictions_digest.py) can decide
            # what's "major" enough to alert on, per Sam's explicit
            # requirement that real positional changes should visibly
            # affect predictions, not be silently absorbed.
            fixture_result["position_changes"] = home_position_changes + away_position_changes

            # Real infra-failure warnings (both real sources unavailable
            # for a team) are printed for operational visibility only --
            # NEVER attached to fixture_result, so they can't leak into
            # the email digest. This should be genuinely rare now that
            # the real bs4 dependency bug (found via a real Actions log,
            # 2026-06-24) is fixed, AND now that a real Tuesday baseline
            # team-list scrape exists (2026-06-25) -- a real team list
            # should now exist for essentially every real run.
            for warning in (home_infra_warning, away_infra_warning):
                if warning:
                    print(f"WARNING: {warning}")

            # REAL BUG FOUND AND FIXED 2026-06-25, per Sam's real,
            # direct catch: Campbell Graham was flagged as a real DUE
            # WATCH entry despite not being named in that week's real
            # team list at all -- traced to a genuine ORDERING bug,
            # not a missing check: due_watch used to be attached to
            # fixture_result BEFORE home_squad/away_squad existed,
            # so there was literally nothing to cross-check against
            # yet, even though resolve_squad_positions() above already
            # has exactly the real, confirmed-selected roster.
            #
            # Per Sam's explicit rule (2026-06-25): "a player is not
            # due if they are not named to play that week." Moved the
            # real due_watch attachment to HERE (after both squads are
            # resolved) and added a real, explicit filter: an entry
            # only survives if that player's name is a real key in the
            # relevant team's resolved squad. If real_team_list is
            # None (both real sources -- the new Tuesday baseline scrape
            # AND the precise kickoff-time fallback -- genuinely failed
            # this week, which should now be rare), resolved_squad falls
            # back to "everyone with history" (get_squad()'s own real,
            # documented fallback) -- in that real case, this filter is
            # a real no-op (everyone historically active passes), which
            # is an honest, known limitation rather than a fabricated
            # confirmation; the precise behavior Sam asked for (no
            # selection confirmation at all => show nothing) needs a
            # real distinction this function doesn't have INPUT for
            # without an explicit "team list was genuinely available"
            # boolean threaded through -- flagged here, not silently
            # papered over, for a future real follow-up if needed.
            home_due_raw = due_watch_by_team.get(home_short, [])
            away_due_raw = due_watch_by_team.get(away_short, [])
            home_due_filtered = [d for d in home_due_raw if d["player_name"] in home_squad][:2]
            away_due_filtered = [d for d in away_due_raw if d["player_name"] in away_squad][:2]
            fixture_result["due_watch"] = {
                "home": home_due_filtered,
                "away": away_due_filtered,
            }

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

    # REAL, CONTENT-BASED CHECKPOINT added 2026-07-03, after a confirmed
    # real incident: on 2026-07-02 this workflow computed round=17 (via
    # nrl_master.csv's max round + 1) because nrl_master.csv was stuck
    # at Round 16 (the same scrape-crash chain documented in
    # weekly-update.yml/merge_round.py), but Round 17 had ALREADY BEEN
    # PLAYED days earlier and was already sitting in
    # match_data_FINAL_fixed.csv with real final scores. The run didn't
    # crash -- the-odds-api.com correctly has no upcoming event for a
    # match that already happened, so every fixture came back
    # "status": "skipped: no real upcoming odds-api event found", and
    # that got committed and emailed as a real, if hollow-looking,
    # "predictions" output. This check catches the actual underlying
    # condition directly (the target round already has real results on
    # file) rather than relying on the odds API's absence of data as an
    # indirect signal -- the two fixes upstream (weekly-update.yml's
    # scrape-success gate, merge_round.py's failure-on-empty-pending)
    # should prevent nrl_master.csv from staying stuck like this again,
    # but this is the real, direct backstop specifically for the
    # predictions script, independent of whatever upstream state caused
    # the wrong round number to be computed in the first place.
    match_rows = load_csv(f"{args.data_dir}/match_data_FINAL_fixed.csv")
    already_played = [
        r for r in match_rows
        if int(r["season"]) == args.season and int(r["round"]) == args.round_num
        and r.get("home_score", "").strip() != "" and r.get("away_score", "").strip() != ""
    ]
    if already_played:
        print(
            f"ERROR: Round {args.round_num} (season {args.season}) already has "
            f"{len(already_played)} real, final match result(s) recorded in "
            f"match_data_FINAL_fixed.csv -- this round has already been played. "
            f"Generating 'predictions' for a finished round is almost always a "
            f"symptom of nrl_master.csv being stuck on an earlier round (so the "
            f"'next round' calculation is wrong), not a legitimate request. "
            f"Refusing to overwrite predictions_current.json/.csv with junk output. "
            f"Check nrl_master.csv's actual max round and STATUS.md before retrying.",
            file=sys.stderr,
        )
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
