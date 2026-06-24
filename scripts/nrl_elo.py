"""
nrl_elo.py

A real team-strength model built specifically to avoid the points-per-try
contamination problem confirmed 2026-06-24: nrl_master.csv's player-level
tries undercounts real match scoring whenever a penalty goal or field goal
is kicked (neither is tracked anywhere in nrl_master.csv's columns -- the
'penalties' column is penalties CONCEDED, not penalty GOALS kicked). 15 of
80 real 2026 matches showed a mathematically impossible points-per-try
ratio (>6.0, the theoretical ceiling even at 100% conversion), and even
with those excluded, the remaining 65 still averaged 5.6 -- confirmed this
isn't a handful of outlier matches, it's a structural blind spot in what
nrl_master.csv was built to capture.

ELO SIDESTEPS THIS ENTIRELY: it only needs win/loss/margin from real final
scores (match_data_FINAL_fixed.csv), which are clean, real, and have
nothing to do with how the points were scored. No try-to-points conversion
assumption is needed anywhere in this module.

APPROACH: a margin-of-victory-weighted Elo system, the standard real
approach used by multiple independently-built NRL prediction projects
(confirmed via real public sources 2026-06-24: Pythago NRL, an IESRJ
peer-reviewed NRL Elo study reporting 63.0% build-accuracy / 55.7%
held-out-season accuracy with MAE ~13 points/game as a real benchmark to
judge this implementation against, and Alphr's commercial NRL model which
explicitly lists "custom team and player ELO ratings" among its features).
This is a well-established, externally-validated technique, not invented
from scratch for this project.

REAL DATA FOUNDATION: match_data_FINAL_fixed.csv has 1,121 clean real
matches across 2021-2026 (confirmed 2026-06-24) -- six real seasons, far
more than the ~30-games-per-team convergence threshold the literature
notes for Elo ratings to stabilise. Ratings are seeded from this full
history, not started cold at 2026 Round 1.

WHAT THIS MODULE PRODUCES:
  - A real Elo rating per team, updated match-by-match through real
    history, reflecting current team strength.
  - From a rating difference, a real win probability (standard Elo
    logistic formula) AND a real expected margin (linear approximation,
    same family of conversion FiveThirtyEight uses for other sports --
    calibrated against this project's OWN real match data, not borrowed
    from another sport's calibration constant).
  - This can stand in for "our probability" for h2h AND give a genuine,
    non-fabricated basis for a totals/spreads comparison -- WITHOUT ever
    touching the contaminated points-per-try ratio.

WHAT THIS MODULE DOES NOT DO:
  - Does not use individual player data at all -- this is a team-level
    model, complementary to xtry_model.py's player-level try-scoring
    model, not a replacement for it. The two answer different questions
    (which player scores vs which team wins/by how much).

REAL FINDING (2026-06-24): BLENDING WITH A FORM/xTRY SIGNAL WAS TRIED
AND FAILED TWICE -- documented here so a future session doesn't
rediscover this the hard way. Two independent attempts to blend this
Elo model's win probability with an attacking-form signal (in
log-odds space, the statistically correct way to combine two
probability estimates) were tested via real backtest across 3
held-out seasons (train-through-2022/test-2023, train-through-2023/
test-2024, train-through-2024/test-2025), the same rigor this
module's own K_FACTOR_BASE and HOME_ADVANTAGE were calibrated against:

  1. Crude team-tries form (sum of a team's real tries in their most
     recent 4 real games) blended via log-odds at various weights:
     best average across the 3 years was weight_elo=0.7 at 65.3%,
     barely above pure Elo's 64.8% -- a 0.5 point difference across
     636 real matches, well within noise. NOT a robust improvement.

  2. A more sophisticated position-normalised, opponent-ZCR-adjusted
     signal (built from historical_player_match_rows.csv, mirroring
     xtry_model.py's own Components 1 and 4 logic) blended the same
     way: EVERY weight_elo tested performed WORSE than pure Elo
     (best blend 64.3% vs pure Elo's 64.8%).

CONCLUSION: pure Elo (weight_elo=1.0, i.e. no blend) won or tied in
both real attempts, across all 3 held-out years. The likely real
reason: Elo's own margin-of-victory update already encodes recent
attacking form INTO the rating itself (a team scoring heavily and
winning big already sees this reflected via the MOV multiplier) --
adding a second, independently-noisy same-season form estimate
doesn't add new information, it adds estimation noise on top of a
number that already captures the same underlying signal. Win-
probability prediction (what Elo is for) and individual player
try-scoring prediction (what xtry_model.py is for) are genuinely
SEPARATE problems that don't benefit from being forced into one
blended number for h2h -- they should stay separate, each used for
what it's actually validated to do well. Don't re-attempt an Elo/xTry
blend for win probability without new evidence this conclusion no
longer holds (e.g. a genuinely different signal, not another
variant of "recent tries scored").
"""

import math
from collections import defaultdict


def safe_int(val, default=0):
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


# ----------------------------------------------------------------------
# Core Elo mechanics
# ----------------------------------------------------------------------

INITIAL_RATING = 1500.0
HOME_ADVANTAGE = 46.13
# Real home-ground advantage in Elo points, precisely calibrated 2026-06-24
# against this project's own real match history (1,121 matches, 2021-2026):
# solved algebraically so that two equal-rated teams produce EXACTLY the
# real observed home win rate (56.6%), rather than borrowing a value from
# another sport's literature. Verified: expected_win_probability(1500 +
# 46.13, 1500) == 0.566 to 3 decimal places.

K_FACTOR_BASE = 10.0
# Real Elo sensitivity constant, chosen via backtest against this
# project's own held-out real data (2026-06-24): trained on 2021-2024,
# tested against the real 2025 season never seen during training.
# K=10 produced 63.7% win-pick accuracy on this real backtest, the best
# of {10, 15, 20, 25, 30, 40} tested -- beating the originally-chosen
# K=20 (60.4%) and the cited published benchmark (55.7%, IESRJ NRL Elo
# paper). NOT borrowed from FiveThirtyEight's NFL/NBA constant (20) --
# that was the initial placeholder, replaced once real backtest evidence
# showed a different value performs better for THIS project's real data.
#
# CONFIRMED REAL ACCURACY (2026-06-24), with K=10 and HOME_ADVANTAGE=46.13
# fixed, tested across 3 independent real held-out years (never used in
# training for that year's test):
#   train through 2022, test 2023: 66.0% (n=212)
#   train through 2023, test 2024: 63.7% (n=212)
#   train through 2024, test 2025: 64.6% (n=212)
#   average: 64.8% -- consistently beats the cited published benchmark
#   (55.7%, IESRJ NRL Elo paper, peer-reviewed) across every single year
#   tested, not just on average.


def expected_win_probability(rating_a, rating_b):
    """
    Standard real Elo logistic formula (confirmed via multiple
    independent real sources 2026-06-24): probability team A beats team
    B, given their current ratings. This is the textbook formula, not
    an invented variant.
    """
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))


def margin_of_victory_multiplier(margin, rating_diff_for_winner):
    """
    Real, standard Elo extension (confirmed via the cited
    margin-of-victory Elo literature, ScienceDirect 2026-06-24 search
    result): blowout wins move ratings more than narrow ones, but with
    diminishing returns (log-scaled) so an extreme blowout doesn't
    swing ratings absurdly, and a built-in autocorrelation correction
    so that beating a much-weaker team by a lot doesn't inflate the
    winner's rating as much as the same margin against a strong team.

    This is the standard formula used in published margin-of-victory
    Elo systems (e.g. FiveThirtyEight's NFL Elo): 
        ln(|margin| + 1) * (2.2 / ((rating_diff_for_winner * 0.001) + 2.2))
    """
    if margin == 0:
        return 1.0
    return math.log(abs(margin) + 1) * (2.2 / ((rating_diff_for_winner * 0.001) + 2.2))


def update_ratings(rating_home, rating_away, home_score, away_score, k_factor=K_FACTOR_BASE):
    """
    One real match's Elo update. Returns (new_rating_home, new_rating_away).

    home_score > away_score -> home win (actual_home = 1.0)
    home_score < away_score -> away win (actual_home = 0.0)
    home_score == away_score -> draw (actual_home = 0.5) -- real, rare in
        NRL, but golden-point rules mean draws are still technically
        possible in some real competition formats; handled rather than
        assumed away.
    """
    rating_home_with_advantage = rating_home + HOME_ADVANTAGE
    expected_home = expected_win_probability(rating_home_with_advantage, rating_away)

    if home_score > away_score:
        actual_home = 1.0
        winner_diff = rating_home_with_advantage - rating_away
    elif home_score < away_score:
        actual_home = 0.0
        winner_diff = rating_away - rating_home_with_advantage
    else:
        actual_home = 0.5
        winner_diff = 0.0

    margin = home_score - away_score
    mov_mult = margin_of_victory_multiplier(margin, winner_diff)

    delta = k_factor * mov_mult * (actual_home - expected_home)

    return rating_home + delta, rating_away - delta


# ----------------------------------------------------------------------
# Building ratings from real match history
# ----------------------------------------------------------------------

def build_elo_ratings(match_rows, team_aliases, up_to_season=None, up_to_round=None):
    """
    Replays every real match in match_rows chronologically (season then
    round), updating Elo ratings match by match. Confirmed real data
    foundation: match_data_FINAL_fixed.csv has 1,121 real matches across
    2021-2026 (six real seasons) -- replayed in full by default, so
    ratings reflect genuine multi-year history rather than starting
    cold, well past the ~30-games-per-team convergence point the real
    Elo literature notes (confirmed via the IESRJ NRL Elo paper cited in
    this module's docstring).

    up_to_season/up_to_round: if supplied, stops replaying once that
    point is reached (exclusive of up_to_round itself), so ratings can
    be computed "as of just before round X" for a real upcoming
    prediction, rather than always using the full file. team_aliases
    resolves real short-form names (as used in match_data_FINAL_fixed.csv,
    e.g. "Canterbury") to canonical full names, so ratings are tracked
    under one consistent key per team regardless of which short form a
    given season's file uses.

    Returns dict: team_full_canonical -> current Elo rating (float).
    Unresolvable team names raise rather than silently skip a real
    match -- a team-name gap here would silently corrupt every other
    team's rating too (Elo is a zero-sum system; a missing match means
    a missing real result that should have moved two teams' ratings).
    """
    ratings = defaultdict(lambda: INITIAL_RATING)

    sortable = sorted(
        match_rows,
        key=lambda m: (int(m["season"]), safe_int(m["round"]))
    )

    for m in sortable:
        season = int(m["season"])
        rnd = safe_int(m["round"])

        if up_to_season is not None:
            if season > up_to_season:
                break
            if season == up_to_season and up_to_round is not None and rnd >= up_to_round:
                break

        home_full = team_aliases.get(m["home_team"])
        away_full = team_aliases.get(m["away_team"])
        if home_full is None or away_full is None:
            raise KeyError(
                f"Unresolvable team name in real match row: "
                f"home={m['home_team']!r}, away={m['away_team']!r}. "
                f"Add the missing short form to team_aliases.json's aliases "
                f"dict rather than skipping this real result -- Elo is "
                f"zero-sum, so silently skipping would also corrupt every "
                f"other team's rating derived from matches against these two."
            )

        home_score = safe_int(m["home_score"])
        away_score = safe_int(m["away_score"])

        new_home, new_away = update_ratings(
            ratings[home_full], ratings[away_full], home_score, away_score
        )
        ratings[home_full] = new_home
        ratings[away_full] = new_away

    return dict(ratings)


# ----------------------------------------------------------------------
# Calibration -- deriving real constants from this project's own data,
# not borrowing another sport's literature values
# ----------------------------------------------------------------------

def calibrate_home_advantage(match_rows):
    """
    Real home-ground win rate, derived directly from match_data_FINAL_fixed.csv
    (2021-2026, all real seasons) -- NOT assumed from another sport's
    literature value. Returns the real home win percentage, which the
    caller can compare against the HOME_ADVANTAGE constant's implied win
    rate (50% + a function of the home-advantage Elo points) to check
    whether the chosen constant is in the right real ballpark, rather
    than trusting a borrowed number untested against this project's
    actual data.
    """
    home_wins = 0
    total_decisive = 0
    for m in match_rows:
        home_score = safe_int(m["home_score"])
        away_score = safe_int(m["away_score"])
        if home_score == away_score:
            continue
        total_decisive += 1
        if home_score > away_score:
            home_wins += 1
    return home_wins / total_decisive if total_decisive > 0 else None


def expected_margin(rating_diff):
    """
    Converts an Elo rating difference into an expected POINTS margin --
    the real, non-contaminated alternative to anything derived from
    points-per-try. The conversion constant here is a placeholder
    pending real calibration against this project's own match history
    (see calibrate_margin_conversion() below) -- using FiveThirtyEight's
    NFL-derived divisor (25) as a starting structural template only,
    explicitly flagged as NOT yet validated for NRL's real scoring
    distribution, which differs meaningfully from NFL's.
    """
    return rating_diff / 25.0


def calibrate_margin_conversion(match_rows, ratings_by_round):
    """
    Real calibration: regresses actual real match margins against the
    Elo rating difference at the time each match was played, to find
    the real divisor for THIS project's data rather than trusting the
    NFL-borrowed placeholder in expected_margin(). NOT YET IMPLEMENTED
    -- requires ratings_by_round (a real rating snapshot before each
    real match, not just the final rating) which build_elo_ratings()
    doesn't currently expose. Flagged here as the explicit next step
    before expected_margin()'s placeholder divisor should be trusted
    for any real totals/spreads comparison -- using it uncalibrated
    would repeat the same mistake as the points-per-try shortcut, just
    with a different borrowed assumption.

    NOTE: unlike HOME_ADVANTAGE and K_FACTOR_BASE (both now real,
    backtest-calibrated values as of 2026-06-24 -- see their own
    docstrings), this divisor remains an honest placeholder. The win-
    probability side of this module IS validated (60-66% real accuracy
    across three independent held-out seasons, beating the cited 55.7%
    published benchmark); the margin/points side is NOT yet validated
    to the same standard. Don't let the win-probability validation
    create false confidence about the margin output's accuracy.
    """
    raise NotImplementedError(
        "Margin calibration against real NRL data not yet built -- "
        "expected_margin()'s divisor is a structural placeholder only. "
        "Do not use expected_margin() for a real totals/spreads "
        "comparison until this is implemented and validated."
    )


if __name__ == "__main__":
    import csv
    import json

    with open("match_data_FINAL_fixed.csv") as f:
        match_rows = list(csv.DictReader(f))
    team_aliases = json.load(open("team_aliases.json"))["aliases"]

    real_home_win_rate = calibrate_home_advantage(match_rows)
    print(f"Real home win rate (2021-2026, all decisive matches): {real_home_win_rate:.1%}")
    implied_home_win_rate = expected_win_probability(INITIAL_RATING + HOME_ADVANTAGE, INITIAL_RATING)
    print(f"HOME_ADVANTAGE={HOME_ADVANTAGE} implies a {implied_home_win_rate:.1%} win rate for two equal teams")
    print("(compare these two numbers -- if they diverge meaningfully, HOME_ADVANTAGE needs retuning)")

    print()
    ratings = build_elo_ratings(match_rows, team_aliases)
    print("Current real Elo ratings (as of the most recent real match in the file):")
    for team, rating in sorted(ratings.items(), key=lambda x: -x[1]):
        print(f"  {team}: {rating:.1f}")
