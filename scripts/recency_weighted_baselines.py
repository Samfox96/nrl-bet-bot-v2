"""
recency_weighted_baselines.py

Phase 7: applies recency weighting to the 2021-2025 historical baselines
(position TPG, team ZCR), so the resulting "what's normal" reference
values lean toward recent seasons (the game changes year to year --
rule changes, tactical shifts) without ignoring older seasons entirely,
and without over-trusting a thin recent sample.

DESIGN DECISIONS (locked in 2026-06-23, after real back-and-forth -- see
session history for the full discussion):

  1. SCOPE: this applies ONLY to the 2021-2025 historical baselines used
     as position/team-level REFERENCE values (e.g. "is this team
     conceding more tries to wingers than is normal"). It does NOT
     touch how a player's own 2026 season-to-date stats are computed --
     those already appropriately dominate any prediction, since they're
     live current-season data, and recency-weighting a single season
     against itself makes no sense. The two stay structurally separate:
     2026 = the live signal, 2021-2025 = a separately-weighted backdrop.

  2. RECENCY CURVE: 2025=1.00, 2024=0.85, 2023=0.70, 2022=0.55,
     2021=0.40 -- a gentler descending decay than an earlier draft
     (2025=100%/2024=75%/2023=50%, which only covered 3 of 5 seasons
     and dropped 2021-2022 entirely). Chosen deliberately gentler:
     recency still matters (the game genuinely changes year to year)
     but shouldn't swamp the multi-year pattern entirely.

  3. CONFIDENCE DAMPENING (the real complication, found by testing
     against actual data rather than assumed): 2025 has roughly 1/8th
     the data volume of every other season in BOTH source files
     checked (historical_position_tpg_baseline.csv: 850 vs ~7,000+
     player-games; historical_player_match_rows.csv: 850 vs ~7,000+
     rows) -- confirmed this is a real, structural property of the
     underlying dataset, not a one-off in a single file. At least one
     position (FB) showed a meaningfully different rate on this thin
     2025 sample vs the four full-season years, which could be a real
     emerging trend or could just be sampling noise from 50 games --
     impossible to tell apart with this little data.

     Recency weighting alone would treat 2025 as MOST trusted (weight
     1.00) despite having the LEAST evidence behind it -- backwards
     from a statistical-confidence standpoint. Fix: multiply the
     recency weight by a confidence factor = sqrt(season_games /
     max_season_games). Square root (not a linear ratio, and not an
     arbitrary hard floor) was chosen because it mirrors how standard
     error actually scales with sample size -- doubling your sample
     reduces uncertainty by sqrt(2), not by 2 -- so the penalty shape
     reflects a real statistical property rather than an invented
     cutoff. Result: 2025's combined weight comes out to ~0.34 (a real
     discount, not a crushing one) rather than ~0.12 under a naive
     linear confidence penalty.

  4. ZCR BASELINE HAD NO SEASON COLUMN AT ALL (a real, structural gap,
     not fixable by recomputing from existing files alone) -- the
     committed historical_zcr_baseline.csv is already a flat 2021-2025
     aggregate. Fixed by reconstructing per-season ZCR from
     historical_player_match_rows.csv (which DOES have a season
     column, plus team/opposition_team/position/tries -- everything
     the original flat ZCR calculation must have used). The
     reconstruction logic was validated against the real existing flat
     baseline BEFORE adding any weighting: all 170 (team, position)
     combinations reproduce their committed tries_scored_against and
     games values exactly -- confirms the reconstruction approach is
     sound, not a guess.

WHAT THIS DOES NOT DO:
  - Does not modify the original historical_position_tpg_baseline.csv
    or historical_zcr_baseline.csv files -- those remain available
    as the flat, unweighted reference they've always been. This module
    produces NEW weighted values as a separate computation, callable
    wherever a recency-aware baseline is wanted (e.g. due_flags_v2.py's
    opponent-matchup factor, the next time that's revisited).
  - Does not change the player-level 2026 data path at all.
"""

import csv
import math
from collections import defaultdict


RECENCY_WEIGHTS = {
    "2025": 1.00,
    "2024": 0.85,
    "2023": 0.70,
    "2022": 0.55,
    "2021": 0.40,
}


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


def compute_confidence_weights(games_by_season):
    """
    Returns {season: confidence_factor} where confidence_factor =
    sqrt(this_season_games / max_season_games), so the season with the
    most games gets confidence=1.0 and thinner seasons get a real but
    non-linear discount. games_by_season: dict of season -> total game
    count (across all positions/teams, i.e. the denominator that
    reflects how much real evidence that season represents overall).
    """
    max_games = max(games_by_season.values())
    return {
        season: math.sqrt(games / max_games) if max_games > 0 else 0.0
        for season, games in games_by_season.items()
    }


def compute_combined_weights(games_by_season):
    """
    Returns {season: combined_weight} = recency_weight * confidence_factor
    for each season actually present in games_by_season. Raises if a
    season appears that isn't in RECENCY_WEIGHTS, rather than silently
    defaulting it to 0 or 1 -- an unrecognised season (e.g. 2026 showing
    up here by mistake, or a future 2027 baseline year) should be a
    visible error, not a silent miscalculation.
    """
    confidence = compute_confidence_weights(games_by_season)
    combined = {}
    for season in games_by_season:
        if season not in RECENCY_WEIGHTS:
            raise KeyError(
                f"Season '{season}' has no recency weight defined in "
                f"RECENCY_WEIGHTS. Known seasons: {list(RECENCY_WEIGHTS.keys())}. "
                f"This baseline covers 2021-2025 only -- if this is a genuine "
                f"new season, add it to RECENCY_WEIGHTS deliberately rather "
                f"than letting it default silently."
            )
        combined[season] = RECENCY_WEIGHTS[season] * confidence[season]
    return combined


def build_weighted_tpg_baseline(position_tpg_baseline_rows):
    """
    Computes a recency+confidence weighted TPG per position from the
    real historical_position_tpg_baseline.csv rows (season, position,
    total_tries, total_player_games columns).

    Returns dict: position_code -> weighted_tpg (float)

    Weighting math: for each position, compute a weighted average of
    each season's TPG, weighted by combined_weight (recency x
    confidence). This is a weighted MEAN OF RATES, not a weighted sum
    of raw tries/games -- deliberately, since season-level confidence
    is already folded into the weight itself rather than double-counted
    through raw totals.
    """
    games_by_season = defaultdict(int)
    for row in position_tpg_baseline_rows:
        games_by_season[row["season"]] += safe_int(row["total_player_games"])

    combined_weights = compute_combined_weights(games_by_season)

    weighted_sum_by_position = defaultdict(float)
    weight_total_by_position = defaultdict(float)

    for row in position_tpg_baseline_rows:
        position = row["position"]
        season = row["season"]
        tpg = safe_float(row["tpg"])
        weight = combined_weights[season]
        weighted_sum_by_position[position] += tpg * weight
        weight_total_by_position[position] += weight

    return {
        position: (weighted_sum_by_position[position] / weight_total_by_position[position])
        for position in weighted_sum_by_position
        if weight_total_by_position[position] > 0
    }


def build_weighted_zcr_baseline(player_match_rows):
    """
    Reconstructs per-season (team, position) tries-conceded data from
    historical_player_match_rows.csv (since the committed
    historical_zcr_baseline.csv has no season breakdown at all -- a
    real, structural gap, not something fixable without going back to
    a source file that DOES have per-season granularity), then applies
    the same recency+confidence weighting.

    Returns dict: (defending_team_full, position_code) -> weighted_concede_rate

    Validated 2026-06-23: this reconstruction logic, with weights
    removed, exactly reproduces all 170 rows of the real committed
    historical_zcr_baseline.csv (tries_scored_against and games columns
    both matched exactly for every team/position combination) -- so the
    underlying per-row logic is proven correct before any weighting is
    layered on top.
    """
    games_by_season = defaultdict(int)
    for row in player_match_rows:
        games_by_season[row["season"]] += 1

    combined_weights = compute_combined_weights(games_by_season)

    # Per (team, position, season): tries conceded and games faced.
    conceded_by_key_season = defaultdict(lambda: defaultdict(int))
    games_by_key_season = defaultdict(lambda: defaultdict(int))

    for row in player_match_rows:
        tries = safe_int(row["tries"])
        defending_team = row["opposition_team"]
        position = row["position"]
        season = row["season"]
        conceded_by_key_season[(defending_team, position)][season] += tries
        games_by_key_season[(defending_team, position)][season] += 1

    weighted_rates = {}
    for key in conceded_by_key_season:
        weighted_sum = 0.0
        weight_total = 0.0
        for season in conceded_by_key_season[key]:
            tries = conceded_by_key_season[key][season]
            games = games_by_key_season[key][season]
            if games == 0:
                continue
            rate = tries / games
            weight = combined_weights[season]
            weighted_sum += rate * weight
            weight_total += weight
        if weight_total > 0:
            weighted_rates[key] = weighted_sum / weight_total

    return weighted_rates


if __name__ == "__main__":
    position_tpg_baseline = load_csv("historical_position_tpg_baseline.csv")
    player_match_rows = load_csv("historical_player_match_rows.csv")

    print("=== Combined (recency x confidence) weights by season ===")
    games_by_season = defaultdict(int)
    for row in position_tpg_baseline:
        games_by_season[row["season"]] += safe_int(row["total_player_games"])
    combined = compute_combined_weights(games_by_season)
    for season in sorted(combined):
        print(f"  {season}: {combined[season]:.3f}")

    print()
    print("=== Weighted TPG by position (vs flat unweighted average) ===")
    weighted_tpg = build_weighted_tpg_baseline(position_tpg_baseline)

    flat_avg = defaultdict(lambda: [0, 0])
    for row in position_tpg_baseline:
        flat_avg[row["position"]][0] += safe_int(row["total_tries"])
        flat_avg[row["position"]][1] += safe_int(row["total_player_games"])

    for position in sorted(weighted_tpg):
        flat = flat_avg[position][0] / flat_avg[position][1]
        print(f"  {position}: weighted={weighted_tpg[position]:.3f}, flat_unweighted={flat:.3f}")

    print()
    print("=== Weighted ZCR sample (first 5 team/position combos) ===")
    weighted_zcr = build_weighted_zcr_baseline(player_match_rows)
    for i, (key, rate) in enumerate(weighted_zcr.items()):
        if i >= 5:
            break
        print(f"  {key}: weighted_concede_rate={rate:.3f}")
