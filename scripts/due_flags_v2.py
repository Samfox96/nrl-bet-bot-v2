"""
due_flags_v2.py

Phase 5 rebuild (2026-06-23) of the DUE WATCH section, replacing the
original "season TPG vs position average" approach -- which was real,
working code, but measured the wrong thing. It surfaced players who are
simply below-average scorers at their position all season (e.g. Jed
Stuart, 0.08 TPG vs 0.62 league average across 12 games) rather than
players who are "due": proven scorers currently in an unusual dip, or
trending toward a breakout via team form, usage, and matchup signals.

REBUILT CONCEPT (confirmed against real Round 16 data, 2026-06-23):
A genuine DUE signal is a composite of:
  1. Drought (50% weight) -- recent form (last 4 games) well below the
     player's OWN season average. This is the anchor signal: real proven
     scorers (Reece Walsh, James Tedesco, Dylan Edwards, Josh Addo-Carr)
     who've gone cold recently, confirmed via real game-by-game data.
  2. Opponent matchup (25% weight) -- this round's opponent's historical
     ZCR (tries conceded by position, 2021-2025 baseline) at the
     player's position, vs the league-average ZCR for that position. A
     weak defensive matchup is a positive signal; a tough one is
     negative. Requires the season draw (see season_draw_2026.json) --
     team pairings ARE known well ahead of kickoff (sourced from the
     official NRL draw PDF), unlike named team lists which only firm up
     near kickoff via Job B. This was a real design correction during
     this session: the original assumption (this factor needs Job B's
     team-list data) was wrong.
  3. Team form (8.3% weight) -- team's own tries-per-game, recent vs
     season average. Rising team form means more scoring opportunities
     for everyone on it.
  4. Usage trend (8.3% weight) -- player's involvement (all_runs),
     recent vs season average. Rising usage despite a try drought is
     arguably a STRONGER due signal (more opportunity, just hasn't
     converted yet) than usage also declining.
  5. Attacking structure share (8.3% weight, APPROXIMATE -- explicitly
     labelled as such in output) -- player's share of team receipts,
     recent vs season. This is a proxy, not a direct measurement: there
     is no real play-calling/structure data available in nrl_master.csv,
     only stat outputs. Real shifts here tend to be small (single-digit
     percentage points), confirmed against real data -- this factor is
     deliberately the lightest-weighted for that reason.

HARD GATE (not weighted, must pass to appear at all):
  Proven scorer: season TPG must be at or above a credible threshold for
  the player's position (same logic as the original bug fix -- without
  this gate, a low-output player with a "rising" trend off a near-zero
  base could still surface, which isn't a real DUE signal). This gate
  is the one piece of the original design kept unchanged, since it was
  correct -- the bug was treating "below average" as sufficient on its
  own, not the gate itself.

WHAT THIS DELIBERATELY DOES NOT DO:
  - Does not require ANY drought to appear -- factor 1 is weighted, not
    gated, so a player trending up on team form + usage + a favourable
    matchup can surface even without an extreme recent dip. This was an
    explicit design decision (2026-06-23): catches breakout candidates,
    not just slump-recovery candidates.
  - season_draw_2026.json currently only covers rounds 17-18 (the
    immediately relevant rounds at time of writing), NOT the full
    27-round season. Calling this for a round beyond what's in that
    file raises a clear KeyError rather than silently returning no
    opponent-matchup signal -- extend the file as the season progresses.
"""

import csv
import json
from collections import defaultdict


def load_json(path):
    with open(path) as f:
        return json.load(f)


def load_csv(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def safe_int(val, default=0):
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def safe_float(val, default=0.0):
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def normalise_position(label, position_aliases):
    return position_aliases.get(label)


def clip(value, lo, hi):
    return max(lo, min(hi, value))


def build_player_game_log(master_rows, season, up_to_round):
    """
    Per-player list of their own game rows for the given season, only
    rounds strictly before up_to_round (so "recent form" never includes
    the round the digest is currently reporting on), sorted by round.
    """
    by_player = defaultdict(list)
    for row in master_rows:
        if row["season"] != str(season):
            continue
        if safe_int(row["round"]) >= up_to_round:
            continue
        by_player[row["player_name"]].append(row)
    for player in by_player:
        by_player[player].sort(key=lambda r: safe_int(r["round"]))
    return by_player


def build_team_round_aggregates(master_rows, season, up_to_round):
    """
    Team-level per-round totals (tries, receipts) -- needed for the team
    form and structure-share factors, which compare a player's numbers
    against their own team's totals, not the league's.
    """
    team_round_tries = defaultdict(lambda: defaultdict(int))
    team_round_receipts = defaultdict(lambda: defaultdict(int))
    for row in master_rows:
        if row["season"] != str(season):
            continue
        if safe_int(row["round"]) >= up_to_round:
            continue
        rnd = safe_int(row["round"])
        team_round_tries[row["team"]][rnd] += safe_int(row["tries"])
        team_round_receipts[row["team"]][rnd] += safe_int(row["receipts"])
    return team_round_tries, team_round_receipts


def drought_signal(games, recent_n=4):
    """
    Factor 1 (50% weight). Returns (raw_diff, normalised) where raw_diff
    is season_tpg - recent_tpg (positive = drought, negative = hot
    streak) and normalised is clipped to [-1, 1] using +/-0.6 as the
    bound -- chosen from the real observed distribution of this metric
    across the whole 2026 season to date (5th/95th percentile sat at
    roughly +/-0.37, so 0.6 gives headroom without letting one extreme
    outlier dominate the score).
    """
    season_tpg = sum(safe_int(g["tries"]) for g in games) / len(games)
    recent = games[-recent_n:]
    recent_tpg = sum(safe_int(g["tries"]) for g in recent) / len(recent)
    raw_diff = season_tpg - recent_tpg
    normalised = clip(raw_diff / 0.6, -1, 1)
    return season_tpg, recent_tpg, normalised


def team_form_signal(team, team_round_tries, recent_n=4):
    """
    Factor 3 (8.3% weight). Positive = team scoring MORE lately than
    their season average (more opportunity for everyone on the team).
    """
    rounds_played = sorted(team_round_tries[team].keys())
    if len(rounds_played) < 4:
        return None
    tries_seq = [team_round_tries[team][r] for r in rounds_played]
    season_avg = sum(tries_seq) / len(tries_seq)
    recent_avg = sum(tries_seq[-recent_n:]) / min(recent_n, len(tries_seq))
    if season_avg == 0:
        return 0.0
    raw_pct_change = (recent_avg - season_avg) / season_avg
    normalised = clip(raw_pct_change / 0.5, -1, 1)  # +/-50% change maps to +/-1
    return normalised


def usage_trend_signal(games, recent_n=4):
    """
    Factor 4 (8.3% weight). Positive = rising involvement (all_runs)
    recently vs season average.
    """
    season_runs = sum(safe_int(g["all_runs"]) for g in games) / len(games)
    recent = games[-recent_n:]
    recent_runs = sum(safe_int(g["all_runs"]) for g in recent) / len(recent)
    if season_runs == 0:
        return 0.0
    raw_pct_change = (recent_runs - season_runs) / season_runs
    normalised = clip(raw_pct_change / 0.5, -1, 1)
    return normalised


def structure_share_signal(games, team, team_round_receipts, recent_n=4):
    """
    Factor 5 (8.3% weight, APPROXIMATE). Player's share of team receipts,
    recent vs season. Real shifts here are small (confirmed against real
    data: single-digit percentage-point changes even for genuine cases),
    so this factor is deliberately light-weighted and explicitly labelled
    as approximate wherever it's surfaced in output.
    """
    season_shares = []
    for g in games:
        rnd = safe_int(g["round"])
        team_total = team_round_receipts[team][rnd]
        if team_total > 0:
            season_shares.append(safe_int(g["receipts"]) / team_total)
    if len(season_shares) < 4:
        return None
    recent_shares = season_shares[-recent_n:]
    season_avg = sum(season_shares) / len(season_shares)
    recent_avg = sum(recent_shares) / len(recent_shares)
    if season_avg == 0:
        return 0.0
    raw_pct_change = (recent_avg - season_avg) / season_avg
    normalised = clip(raw_pct_change / 0.5, -1, 1)
    return normalised


def opponent_matchup_signal(position_code, opponent_team_short, team_aliases, zcr_baseline_lookup, league_avg_zcr_by_position):
    """
    Factor 2 (25% weight). Compares the upcoming opponent's historical
    ZCR at this player's position against the league-average ZCR for
    that position. Positive = favourable (weak defensive) matchup.

    Returns None if the opponent can't be resolved to a canonical name,
    or if there's no ZCR baseline entry for that (team, position) pair
    -- never guesses a value.
    """
    opponent_full = team_aliases.get(opponent_team_short)
    if opponent_full is None:
        return None
    opponent_rate = zcr_baseline_lookup.get((opponent_full, position_code))
    league_avg = league_avg_zcr_by_position.get(position_code)
    if opponent_rate is None or league_avg is None or league_avg == 0:
        return None
    raw_pct_diff = (opponent_rate - league_avg) / league_avg
    normalised = clip(raw_pct_diff / 0.5, -1, 1)
    return normalised


def is_proven_scorer(games, position_code, league_tpg_by_position, min_games=8, min_total_tries=2):
    """
    Hard gate, refined twice during the 2026-06-23 session after real
    Round 17 test data exposed two separate problems with the original
    simple ratio gate (season_tpg >= 0.5 * league_baseline):

    Problem 1 (caught first): for low-scoring positions (props, hookers,
    locks, halves -- league baseline 0.076-0.254), HALF of an already-
    tiny number is still tiny in absolute terms, so the ratio barely
    filtered anything. First fix: raised the ratio to 0.75x for those
    positions specifically.

    Problem 2 (caught testing the first fix against the FULL set of
    real 2026 props, not just the borderline case that prompted it):
    even a RAISED ratio against PR's league baseline (0.079) sits so
    close to zero that it passed all 19 of 19 props who scored even
    once this season -- the ratio gate does literally nothing for that
    position no matter how high the multiplier goes, since the
    baseline itself is too compressed for a ratio to ever bind
    meaningfully. Real fix: an ABSOLUTE minimum tries floor in addition
    to the ratio, which scales itself to "did this person do something
    notable" rather than chasing a ratio across position baselines of
    wildly different magnitudes. min_total_tries=2 was chosen by testing
    candidate floors (1-4) against every low-scoring position's real
    2026 data: 2 gives a genuine, non-trivial cut at every position
    (e.g. PR: 7/19 pass instead of 19/19) without being so aggressive
    it leaves a position with almost no candidates (LK at a floor of 3
    drops to just 2 passers).

    Both gates must pass: the ratio gate still matters for high-scoring
    positions (CE/FB/WG) where it's doing real work, and the absolute
    floor catches what the ratio structurally cannot for low-scoring
    ones.
    """
    if len(games) < min_games:
        return False
    total_tries = sum(safe_int(g["tries"]) for g in games)
    if total_tries < min_total_tries:
        return False
    season_tpg = total_tries / len(games)
    league_baseline = league_tpg_by_position.get(position_code)
    if not league_baseline or league_baseline < 0.05:
        return False

    LOW_SCORING_POSITIONS = {"IC", "PR", "LK", "HK", "HB", "2RF", "FE"}
    required_ratio = 0.75 if position_code in LOW_SCORING_POSITIONS else 0.5
    return season_tpg >= league_baseline * required_ratio


def build_league_tpg_by_position(position_tpg_baseline):
    league_tpg_by_position = defaultdict(lambda: [0, 0])
    for row in position_tpg_baseline:
        code = row["position"]
        league_tpg_by_position[code][0] += safe_int(row["total_tries"])
        league_tpg_by_position[code][1] += safe_int(row["total_player_games"])
    return {
        code: (tries / games if games else 0)
        for code, (tries, games) in league_tpg_by_position.items()
    }


def build_due_watch(master_rows, season, up_to_round, team_aliases, position_aliases,
                     zcr_baseline, position_tpg_baseline, season_draw, top_n=5):
    """
    Top-level entry point. Returns a sorted list of dicts, each with the
    composite score, every contributing factor's raw + normalised value
    (so the email can show WHY a player is flagged, not just a number),
    and which factors were unavailable (e.g. no opponent data, too few
    games for structure share) rather than silently treating missing
    data as zero.
    """
    round_key = str(up_to_round)
    if round_key not in season_draw["rounds"]:
        raise KeyError(
            f"No draw data for round {up_to_round} in season_draw_2026.json. "
            f"This file currently covers rounds: {list(season_draw['rounds'].keys())}. "
            f"Extend it with the next rounds from the official NRL draw PDF."
        )
    fixtures = season_draw["rounds"][round_key]["fixtures"]
    opponent_of = {}
    for home, away in fixtures:
        opponent_of[home] = away
        opponent_of[away] = home

    zcr_lookup = {}
    for row in zcr_baseline:
        zcr_lookup[(row["defending_team"], row["position"])] = safe_float(row["concede_rate"])

    league_avg_zcr_by_position = defaultdict(list)
    for row in zcr_baseline:
        league_avg_zcr_by_position[row["position"]].append(safe_float(row["concede_rate"]))
    league_avg_zcr_by_position = {
        code: sum(vals) / len(vals) for code, vals in league_avg_zcr_by_position.items()
    }

    league_tpg_by_position = build_league_tpg_by_position(position_tpg_baseline)
    by_player = build_player_game_log(master_rows, season, up_to_round)
    team_round_tries, team_round_receipts = build_team_round_aggregates(master_rows, season, up_to_round)

    WEIGHTS = {
        "drought": 0.50,
        "opponent_matchup": 0.25,
        "team_form": 0.083,
        "usage_trend": 0.083,
        "structure_share": 0.083,
    }

    results = []
    for player, games in by_player.items():
        if len(games) < 8:
            continue

        most_recent = games[-1]
        team = most_recent["team"]
        position_code = normalise_position(most_recent["position"], position_aliases)
        if position_code is None:
            continue

        if not is_proven_scorer(games, position_code, league_tpg_by_position):
            continue

        season_tpg, recent_tpg, drought_norm = drought_signal(games)
        team_form_norm = team_form_signal(team, team_round_tries)
        usage_norm = usage_trend_signal(games)
        structure_norm = structure_share_signal(games, team, team_round_receipts)

        opponent_short = opponent_of.get(team)
        opponent_norm = None
        if opponent_short is not None:
            opponent_norm = opponent_matchup_signal(
                position_code, opponent_short, team_aliases, zcr_lookup, league_avg_zcr_by_position
            )

        factor_values = {
            "drought": drought_norm,
            "opponent_matchup": opponent_norm,
            "team_form": team_form_norm,
            "usage_trend": usage_norm,
            "structure_share": structure_norm,
        }

        # Composite score uses only the factors that resolved to a real
        # value -- a missing factor is excluded and its weight is NOT
        # silently redistributed to other factors (that would let a
        # player with lots of missing data get an inflated score from
        # fewer inputs). Instead we track total_weight_used so a low
        # total_weight_used is itself visible in the output.
        composite = 0.0
        total_weight_used = 0.0
        for factor, value in factor_values.items():
            if value is not None:
                composite += WEIGHTS[factor] * value
                total_weight_used += WEIGHTS[factor]

        if total_weight_used == 0:
            continue

        results.append({
            "player_name": player,
            "team": team,
            "position_code": position_code,
            "season_tpg": round(season_tpg, 3),
            "recent_tpg": round(recent_tpg, 3),
            "opponent_this_round": opponent_short,
            "composite_score": round(composite, 3),
            "weight_coverage": round(total_weight_used, 3),
            "factors": {k: (round(v, 3) if v is not None else None) for k, v in factor_values.items()},
            "structure_share_is_approximate": True,
        })

    results.sort(key=lambda r: r["composite_score"], reverse=True)
    if top_n is not None:
        results = results[:top_n]
    return results


if __name__ == "__main__":
    master_rows = load_csv("nrl_master.csv")
    team_aliases = load_json("team_aliases.json")["aliases"]
    position_aliases = load_json("position_aliases.json")["aliases"]
    zcr_baseline = load_csv("historical_zcr_baseline.csv")
    position_tpg_baseline = load_csv("historical_position_tpg_baseline.csv")
    season_draw = load_json("season_draw_2026.json")

    due_list = build_due_watch(
        master_rows, season=2026, up_to_round=17,
        team_aliases=team_aliases, position_aliases=position_aliases,
        zcr_baseline=zcr_baseline, position_tpg_baseline=position_tpg_baseline,
        season_draw=season_draw, top_n=5,
    )
    print(json.dumps(due_list, indent=2))
