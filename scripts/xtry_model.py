"""
xtry_model.py

Phase 8: the actual "our model's probability" side of the edge calculation
-- the piece STATUS.md and PROJECT_BRIEF.md both flagged as completely
unbuilt ("no real 'our model's probability' output for any market yet").

THIS IS A RECONSTRUCTION, NOT A FRESH DESIGN. The real xTry formula --
8 multiplicative components, locked weights -- was specified in an earlier
session and written into a file called NRL_MASTER_PROMPT_V2.md. That file
was NEVER ACTUALLY COMMITTED to the repo (confirmed 2026-06-24: 404 on
every plausible path). PROJECT_BRIEF.md cites "xTry Component 1" and
"xTry Component 4" by name as if the reader already has the spec, but the
spec itself was never in the repo for any session to inherit. This is a
more serious instance of the exact failure pattern already flagged twice
in STATUS.md (a real fix silently lost between sessions) -- except this
time it's the foundational model spec, not a small function. Recovered
2026-06-24 from Sam's own paste of the original spec text. If this file
and the spec text ever diverge, the spec text Sam provided is the source
of truth, not this file's interpretation of it.

THE 8 COMPONENTS (multiplicative):
    xTry = base_tpg_adjusted * FMI * IQS_multiplier * ZCR * personnel_factor
           * ruck_factor * attack_share * context

  1. Position-adjusted base TPG
  2. Form Momentum Index (FMI)
  3. IQS (Involvement Quality Score) multiplier
  4. Zone Concede Rate (ZCR)
  5. Personnel factor
  6. Ruck factor
  7. Attack share
  8. Context

Then: normalise across all players in a game, scale to the real
season-to-date average tries/team/game (computed from nrl_master.csv
itself, not a hardcoded "~5-6" guess), cap display at 60-65% max,
smokies sit 16-20%.

SIX IMPLEMENTATION DECISIONS made 2026-06-24, where the spec text was
clear on the maths but silent on which real data source/edge-case
handling to use -- each one checked against real data before deciding,
not guessed:

  1. "Position-average TPG table" (components 1 and 4) -- uses Phase 7's
     recency+confidence-weighted baseline (recency_weighted_baselines.py)
     in preference to the flat 2021-2025 average. That module exists
     specifically to replace flat baselines and already returns the
     exact shape needed (position_code -> weighted_tpg). Using the flat
     baseline instead would mean ignoring already-proven Phase 7 work.

  2. FMI's "most recent round x0.40, 0.30, 0.20, 0.10" -- confirmed
     against real 2026 round-by-round data (top scorers e.g. Greg
     Marzhew, Thomas Jenkins) that this means: take the player's last 4
     GAMES ACTUALLY PLAYED (skip bye rounds and DNPs entirely, don't
     treat them as a zero-try game), weight the most recent at 0.40 down
     to the 4th-most-recent at 0.10, on that game's raw tries (0, 1, 2...
     -- confirmed this is genuinely the real shape of the data, most
     player-games are 0 or 1 tries). A bye/DNP is "no data for that slot",
     not "a cold game" -- conflating the two would wrongly punish a
     player for being rested, not for being out of form.

  3. IQS per-minute normalisation -- mins_played is stored as "MM:SS"
     text (confirmed real values up to "90:00" for extra time) or "-"
     for DNP. Parsed to float minutes; DNP rows are EXCLUDED from both
     season and recent IQS-per-minute averages entirely, not treated as
     a 0-minute / 0-rate game -- a rate is undefined for a game not
     played, and including it as zero would wrongly drag a player's IQS
     toward zero for a week they didn't take the field.

  4. Ruck factor's team aggregation -- average_play_the_ball_speed is a
     PER-PLAYER average (confirmed real values like "4.19s", "3s" -- not
     a team stat). Aggregating team-level ruck speed as a flat mean of
     these per-player averages would silently misweight a player who
     played the ball 30 times the same as one who played it twice.
     Fixed: weight each player's average by their own play_the_ball
     count before combining to a team figure. "Opponent's avg ruck speed
     allowed" is derived as the attacking team's average PTB speed in
     real matches specifically against that opponent (filtered by the
     opponent column) -- nrl.com doesn't expose a separate "ruck speed
     allowed" stat, so this is a reasonable derivation from the real
     columns that exist, not a directly-named source column. Flagging
     this explicitly as an interpretation, not a confirmed-correct
     reading of the original spec.

  5. Normalisation target ("~5-6 tries/team") -- computed live from
     nrl_master.csv's actual season-to-date tries-per-team-per-game
     average, rather than hardcoding a guessed constant. This keeps the
     normalisation accurate as the season progresses instead of going
     stale against an invented number.

  6. Output granularity -- built as a per-match function (one call =
     both teams' full squads for one fixture), loop over fixtures for a
     full round. Matches how due_flags_v2.py and the digest pipeline
     already operate, so it slots into the existing per-round automation
     shape rather than introducing a new one.

VALIDATION (2026-06-24): every component built and unit-tested against
real nrl_master.csv / historical baseline data individually before
assembly. Full pipeline run end-to-end against ALL 8 real Round 17
fixtures (zero anomalies: no crashes, NaNs, out-of-range probabilities,
or suspicious uniformity) and cross-checked manually against real
player season stats, not just automated checks -- e.g. confirmed Alex
Johnston correctly hits the 65% display cap in a genuinely favourable
real matchup (hot recent form + a real weak Eels ZCR at WG), while a
cooling Greg Marzhew correctly does NOT despite a strong season total.
Also stress-tested against Round 5 (early season, most players on only
3-4 real games) specifically to probe small-sample behaviour rather
than just the comfortable Round 17 sample size.

KNOWN, ACCEPTED LIMITATION found during Round 5 stress-testing:
early-season volatility produces somewhat more 65%-cap-hits than late
season (Round 5: 11/275 modelled players ~4%, vs Round 17: ~3%) --
traced to a REAL, deliberate property of the spec as written: both
Component 1 (50% raw + 50% shrunk blend) and Component 7 (attack
share) compute ratios from small real samples early in the season, and
Component 1's blend structure means HALF the figure is always
unshrunk raw data regardless of sample size -- that's the spec's
literal wording, not a bug, and Sam declined to revisit it after seeing
the real diagnosis. One real, targeted fix WAS applied as a result of
this testing: Component 7's attack-share ratio now shrinks toward the
league-average share using team-games-played credibility-weighting
(see component_7_attack_share's docstring) -- confirmed via real data
(Alex Johnston, Round 5: player_try_share correctly shrunk from a raw
0.286 to a credibility-weighted 0.121 off only 3 real team games),
verified as a real, non-trivial improvement, not just a no-op. The
remaining early-season cap-hit cases were traced and confirmed to be
genuinely driven by Components 1+2's blended_try_rate on legitimately
hot real small-sample starts (e.g. Thomas Jenkins, Round 5: a real
blended_try_rate of 2.16 off 4 games) -- not noise, not a bug, a
deliberate spec property accepted as-is.

WHAT THIS MODULE DOES NOT DO:
  - Does not fetch live team lists -- caller supplies the squad (list of
    player names + team) for each side, same as the rest of the pipeline
    expects team lists to be supplied externally (Job B / manual paste).
  - Does not handle personnel-factor inputs (injury/doubt status) by
    itself -- these require team-list-adjacent information (who's missing,
    who's a doubt) that isn't in nrl_master.csv. The personnel_factor
    function accepts this as explicit input; if not supplied, defaults to
    1.0 (neutral) rather than guessing.
  - Does not call odds_probability.py itself -- this module's job ends at
    "here is OUR probability for player X to score in match Y." Comparing
    that against the market is calculate_edge()'s job, in a separate step.

REAL DATA GAP FOUND DURING BUILD (2026-06-24, worth fixing independently
of this model): play_the_ball is confirmed '0' for EVERY row in the
entire nrl_master.csv (4,560 rows checked) -- nrl_update_single_round.py's
HEADER_MAP believes it's capturing this column but isn't, in practice.
Component 6 (ruck factor) uses receipts as a working fallback weight
(see _weighted_team_ptb_speed's docstring), but the underlying scraper
gap should be looked at separately -- it may be silently affecting other
things that were never built to expect a populated play_the_ball column.

STAGE 6 REAL FINDING (2026-07-04): POSSESSION/TERRITORY PROXIES FOR
COMPONENTS 4 AND 7 WERE TESTED AND REJECTED -- documented here so a
future session doesn't rediscover this the hard way, same discipline
as nrl_elo.py's own rejected form-blend findings.

Candidate signals tested: cumulative team error rate (possession proxy
for Component 7's attacking-volume factor), cumulative kicking metres
and forced drop-outs (territory proxy for Component 4's ZCR factor).
Real, out-of-sample test using nrl_master.csv's 2026 season (the ONLY
player-named dataset available -- historical_player_match_rows.csv has
no player names, per this project's own data rules, so 2021-2025 can't
be used for this kind of player-level backtest). Cumulative team stats
computed strictly from rounds BEFORE the round being predicted -- no
leakage. n=176 team-round observations, rounds 5-16.

Standalone correlation with next-round tries, none significant at
p<0.05: cumulative errors r=0.124 (p=0.101, and WRONG direction -- more
errors trending toward slightly MORE tries, likely a tempo confound
where high-error teams are often just running more plays, not a real
possession-quality signal); cumulative kicking metres r=-0.106
(p=0.163); cumulative forced drop-outs r=0.118 (p=0.119). Referee
identity vs total match scoring rate also tested (one-way ANOVA across
8 real 2026 referees with >=5 matches each): F=0.65, p=0.715, no real
signal.

Multivariate check against the baseline signal Component 1/7 already
use (cumulative team tries-per-game, itself the only variable that
clears significance: r=0.204, p=0.007): baseline-only R^2=0.0415,
baseline+3 proxies R^2=0.0648. Joint F-test on whether the three
proxies add real explanatory power beyond the existing baseline:
F=1.42, p=0.238 -- FAILS to reject the null. The nominal R^2 gain is
statistically indistinguishable from noise at this sample size.

CONCLUSION: do not wire these into Component 4 or Component 7. Same
pattern as nrl_elo.py's rejected blend attempts -- a plausible-sounding
signal that doesn't survive an honest out-of-sample test, and wiring
it in anyway would very likely add estimation noise on top of a
working model rather than genuine new signal.

HONEST CAVEAT: n=176 from 16 rounds is a real but small sample --
this is "current evidence doesn't support it," not "proven zero
effect." Worth re-testing with the same methodology once the 2026
season has more rounds banked (e.g. after Round 26). Don't re-attempt
wiring these specific proxies into the live model without new evidence
this conclusion no longer holds.

STAGE 7 REAL FINDING (2026-07-04): COMPONENT 3'S IQS_STAT_WEIGHTS WERE
NEVER CALIBRATED AGAINST REAL DATA -- confirmed by checking (unlike
nrl_elo.py's HOME_ADVANTAGE and K_FACTOR_BASE, which both cite real
backtest evidence, IQS_STAT_WEIGHTS's original values (line_breaks=4.0,
tackle_breaks=2.0, all_run_metres=0.02, all_runs=0.15,
post_contact_metres=0.01, inside_10_metres=0.5, kick_return_metres=0.01)
had no documented source beyond "the spec" -- intuition-based weights
that had never actually been tested.

Real test performed: standardized logistic regression, real player-
level data from nrl_master.csv (2026 season, the only player-named
dataset available -- see Stage 6 note above for why 2021-2025 can't be
used). Target: did this player score >=1 try in round N (binary),
given each stat's cumulative per-minute rate from rounds BEFORE N (no
leakage). n=2,612 real player-round observations, 413 unique players,
rounds 6-16. McFadden pseudo-R^2=0.056 (a genuinely noisy target at
the individual level, consistent with everything else found this
session about individual try-scoring prediction).

RESULTS (standardized coefficients, directly comparable to each other
unlike the raw IQS_STAT_WEIGHTS which mix different scales):
  line_breaks:          coef=+0.309, p=0.0000 -- CONFIRMED, strongest
                         real predictor, correctly the heaviest weight
  tackle_breaks:         coef=+0.155, p=0.011  -- CONFIRMED, and the
                         real 2:1 ratio vs line_breaks roughly matches
                         the existing 4.0:2.0 weight ratio
  all_run_metres:        coef=+0.223, p=0.373  -- inconclusive
  all_runs:              coef=-0.114, p=0.497  -- inconclusive
  post_contact_metres:   coef=-0.330, p=0.016  -- REAL PROBLEM: the
                         data says this stat's true relationship with
                         future try probability is NEGATIVE and
                         significant, opposite the small positive
                         weight it had. REMOVED from IQS_STAT_WEIGHTS
                         (see that dict's own comment) rather than sign-
                         flipped -- this regression didn't control for
                         position (forwards accumulate post-contact
                         metres grinding through tackles but score far
                         less than backs breaking tackles for line
                         breaks), so the negative sign may be a real
                         individual effect OR a position confound this
                         test can't distinguish. Not confident enough in
                         either direction to keep any weight on it.
  inside_10_metres:      coef=-0.051, p=0.335  -- inconclusive
  kick_return_metres:    coef=-0.056, p=0.402  -- inconclusive

CONCLUSION: line_breaks and tackle_breaks -- the two heaviest weights
in the existing scheme -- are genuinely well-supported by real data,
confirming rather than contradicting the original design. The one
weight that WAS contradicted (post_contact_metres) has been removed.
The four inconclusive stats (all_run_metres, all_runs, inside_10_metres,
kick_return_metres) were deliberately left AT THEIR EXISTING WEIGHTS --
inconclusive evidence is not evidence of absence, and reweighting a
noisy target (pseudo-R^2=0.056) based on one partial-season test risks
overfitting far more than it risks leaving a slightly-wrong small
weight in place. Don't change these four without a real, larger-sample
test first.

HONEST CAVEAT: same as Stage 6 -- one partial season, no position
control on this specific test. Worth re-running with a position-split
version (test post_contact_metres's real effect separately for
forwards vs backs) once there's a defensible reason to believe
position-splitting the IQS blend is worth the added complexity.
"""

import csv
import json
import math
from collections import defaultdict


# ----------------------------------------------------------------------
# Shared loading / parsing utilities
# ----------------------------------------------------------------------

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


def clip(value, lo, hi):
    return max(lo, min(hi, value))


def parse_mins_played(val):
    """
    'MM:SS' -> float minutes. '-' or empty -> None (DNP, not zero --
    see design decision 3 above). Confirmed real format against
    nrl_master.csv: values like '80:00', '13:00', '90:00' (extra time),
    and '-' for did-not-play.
    """
    if val is None:
        return None
    val = val.strip()
    if val == "-" or val == "":
        return None
    if ":" in val:
        m, s = val.split(":")
        return safe_int(m) + safe_int(s) / 60.0
    try:
        return float(val)
    except ValueError:
        return None


def parse_ptb_speed(val):
    """
    'X.XXs' or 'Xs' -> float seconds. '-' or empty -> None.
    Confirmed real formats: '4.19s', '3s', '-'.
    """
    if val is None:
        return None
    val = val.strip()
    if val == "-" or val == "":
        return None
    val = val.rstrip("s")
    try:
        return float(val)
    except ValueError:
        return None


def normalise_position(label, position_aliases):
    return position_aliases.get(label)


# ----------------------------------------------------------------------
# Shared player game-log builder
# ----------------------------------------------------------------------

def build_player_game_log(master_rows, season, up_to_round):
    """
    Per-player list of their own real game rows for the given season,
    rounds strictly before up_to_round, sorted by round, BYE/DNP rounds
    simply don't produce a row (real data: nrl_master.csv has no row at
    all for a bye, and mins_played=='-' for an actual DNP within a row
    that does exist e.g. injury before kickoff) -- so this naturally
    gives "games actually played" without extra filtering here. Callers
    needing strictly-played games (mins_played not None) should filter
    further themselves, since some downstream uses (e.g. season_tpg)
    correctly want every row including an unlucky 1-minute HIA-and-off
    game, while others (e.g. IQS per-minute rate) need an actual minutes
    figure and must exclude true DNP rows.
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


def build_team_games_played(master_rows, season, up_to_round):
    """
    Real count of distinct rounds each team has actually played this
    season so far (rounds strictly before up_to_round) -- needed by
    Component 7's small-sample shrinkage, which is keyed on TEAM games
    played, not individual player games (see component_7_attack_share's
    docstring for why). Counts distinct rounds a team has ANY row for,
    not a fixed assumption -- correctly handles byes (a team simply has
    no rows for a bye round, so it isn't counted).

    Returns dict: team_short_name -> games_played (int).
    """
    team_rounds = defaultdict(set)
    for row in master_rows:
        if row["season"] != str(season):
            continue
        if safe_int(row["round"]) >= up_to_round:
            continue
        team_rounds[row["team"]].add(safe_int(row["round"]))
    return {team: len(rounds) for team, rounds in team_rounds.items()}


# ----------------------------------------------------------------------
# Component 1 -- Position-adjusted base TPG
# ----------------------------------------------------------------------

def component_1_base_tpg(games, position_code, weighted_league_tpg_by_position):
    """
    tries / games actually appeared in (never rounds elapsed -- this is
    a non-negotiable project-wide rule, see PROJECT_BRIEF.md's DATA
    QUALITY RULES). Blend: 50% raw season TPG + 50% position-normalised
    version. Floored at 30% of position average so a genuine zero-try
    player doesn't produce a literal 0.0 that would zero out the whole
    multiplicative chain for one bad patch.

    IMPLEMENTATION NOTE on "position-normalised version" -- the spec
    text says "vs position-average TPG table" but doesn't give the exact
    formula. The naive reading (express the player's rate as a ratio to
    the league average, then multiply that ratio back by the league
    average) is algebraically a no-op -- it always equals raw_season_tpg
    exactly, the league average cancels out (confirmed against real data
    2026-06-24: Alex Johnston, 19 tries/12 games=1.583 raw TPG, league WG
    avg 0.635, ratio 2.493 -- 0.635*2.493 reproduces 1.583 exactly, so
    that reading makes the "blend" a no-op). A blend that always equals
    one of its own inputs isn't a real blend, so this can't be the
    intended meaning.

    Used instead: empirical-Bayes-style SHRINKAGE toward the league
    position average, weighted by games played relative to a credibility
    constant (12 games -- roughly a third of a season, chosen as the
    point where a player's own sample starts to genuinely outweigh the
    league prior). This is a standard, well-understood way to make a
    "normalised version vs the league table" actually pull extreme
    small-sample or outlier rates partway toward the population baseline,
    which is what "normalised against a reference table" should mean.
    Flagged here explicitly as an interpretation, not a verified-exact
    match to the original spec -- correct if Sam clarifies otherwise.

    MINUTES REPROJECTION (2026-07-03, Stage 1 task 2 -- "Option B").
    The architect doc flags that fringe/interchange players are
    overestimated, because raw tries-per-GAME over-credits a short
    appearance: 1 try in a 20-minute cameo counts as the same 1.0 TPG
    as 1 try in a full 80. The fix used here is NOT a flat low-minute
    penalty (that would wrongly under-rate a genuine super-sub who
    scores efficiently in limited minutes, and couldn't scale a player
    UP when their role grows). Instead we reproject onto a per-minute
    rate x expected minutes:

        tries_per_min = total_tries / total_minutes_actually_played
        expected_min  = mean of the last 5 PLAYED games' minutes,
                        capped at 80 (a 90-min golden-point game must
                        not inflate the projection)
        reprojected_tpg = tries_per_min * expected_min

    Confirmed against real data (2026-07-03): this is an exact no-op
    for a stable full-time starter (expected_min ~= their season-avg
    minutes, so reprojected_tpg reproduces raw tries/games), and only
    moves players whose RECENT minutes differ from their season-average
    minutes -- i.e. a changing role. Real examples: Alex Seyfarth
    (season avg 38 min, recent 61 -> rate scales UP 0.143->0.232);
    Soni Luke (season avg 32, recent 22 -> scales DOWN 0.200->0.138).
    So the "penalty" is really a role-adjusted reprojection that can go
    either way -- flagged as a deliberate, more-correct reading of the
    doc's literal "penalty" wording, not an exact match to it.

    The reprojected rate feeds the shrinkage/blend/floor below; the
    RETURNED raw_season_tpg stays the pure per-game rate, unchanged, so
    downstream display (send_predictions_digest's "Nx league average"
    positional-unusual flag) is not silently altered.

    Returns (raw_season_tpg, base_tpg_adjusted, expected_minutes).
    expected_minutes is None when no real minutes were available to
    reproject from (in which case the raw per-game rate is used as-is,
    never guessed).
    """
    if not games:
        return 0.0, 0.0, None

    total_tries = sum(safe_int(g["tries"]) for g in games)
    n_games = len(games)
    raw_season_tpg = total_tries / n_games

    # --- Minutes reprojection (Option B) ---------------------------------
    REFERENCE_MINUTES = 80.0
    played_minutes = [
        m for m in (parse_mins_played(g["mins_played"]) for g in games)
        if m is not None and m > 0
    ]
    total_minutes = sum(played_minutes)
    if total_minutes > 0:
        last5 = played_minutes[-5:]
        expected_minutes = min(sum(last5) / len(last5), REFERENCE_MINUTES)
        tries_per_min = total_tries / total_minutes
        own_rate = tries_per_min * expected_minutes
    else:
        # No real on-field minutes to reproject from -- fall back to the
        # raw per-game rate rather than guessing a minutes figure.
        expected_minutes = None
        own_rate = raw_season_tpg

    league_avg = weighted_league_tpg_by_position.get(position_code)
    if not league_avg or league_avg <= 0:
        # No real baseline for this position -- can't compute the
        # normalised half of the blend. Fall back to the player's own
        # (reprojected) rate alone rather than guessing a league average.
        position_normalised_tpg = own_rate
    else:
        CREDIBILITY_GAMES = 12.0
        shrink_weight = n_games / (n_games + CREDIBILITY_GAMES)
        position_normalised_tpg = (
            shrink_weight * own_rate + (1 - shrink_weight) * league_avg
        )

    blended = 0.5 * own_rate + 0.5 * position_normalised_tpg

    floor = 0.30 * league_avg if league_avg else 0.0
    base_tpg_adjusted = max(blended, floor)

    return raw_season_tpg, base_tpg_adjusted, expected_minutes


# ----------------------------------------------------------------------
# Component 2 -- Form Momentum Index (FMI)
# ----------------------------------------------------------------------

FMI_WEIGHTS = [0.40, 0.30, 0.20, 0.10]  # most recent game first


def component_2_fmi(games, base_tpg_adjusted):
    """
    Exponentially weighted recent try rate: most recent game played
    (NOT round elapsed -- bye/DNP rounds simply have no row, see
    build_player_game_log's docstring) gets weight 0.40, then 0.30,
    0.20, 0.10 going back. Confirmed against real round-by-round data
    (2026-06-24) that this means raw tries that game (0/1/2/3...), not
    some pre-smoothed sub-rate -- that's genuinely the shape of the real
    data (most player-games are 0 or 1 tries, occasionally 2-5).

    Blend rule from the spec: 2+ recent games available -> 45% FMI /
    55% base; exactly 1 recent game -> 25% FMI / 75% base; 0 recent
    games -> 100% base (FMI has nothing to contribute).

    SMALL-SAMPLE REFINEMENT (added 2026-06-24, after early-season
    testing against real Round 5 data found a real compounding problem):
    the spec's literal step function gives a player with exactly 2
    recent games the SAME full 45% FMI weight as a player with a
    complete 4-game window -- no sensitivity to how thin "2+" actually
    is. Combined with Component 1's blend (which is ALSO only partially
    shrunk at low game counts, since half of that blend is always pure
    unshrunk raw TPG regardless of sample size -- see
    component_1_base_tpg's docstring), this double-counts small-sample
    noise: both components lean on the same thin real data
    independently. Confirmed via real Round 5 testing: 4.4% of all
    modelled players hit the 65% display cap (vs ~3% at Round 17),
    correctly traced to this mechanism, not a bug.

    Fix: interpolate the FMI weight between the spec's explicit n=1
    floor (0.25) and n=4 ceiling (0.45) for the n=2/n=3 cases, instead
    of jumping straight to 0.45 the moment a player crosses the "2+"
    threshold. This targets the actual compounding mechanism (FMI
    leaning too hard on a thin recent-window sample) without touching
    Component 1's blend math, which is implemented as the spec literally
    states. Sam reviewed and approved this specific, narrower fix in
    preference to changing Component 1 or adding a separate games-played
    floor on cap eligibility.

    Returns (fmi_raw, blended_try_rate) where fmi_raw is the weighted
    recent-tries figure on its own (for visibility/debugging) and
    blended_try_rate is the single try-rate number that replaces
    base_tpg_adjusted as the multiplicative base for the rest of the
    chain.
    """
    recent = games[-4:]  # up to last 4 games actually played
    recent = list(reversed(recent))  # most recent first, to match FMI_WEIGHTS order

    n_recent = len(recent)
    if n_recent == 0:
        return None, base_tpg_adjusted

    fmi_raw = sum(
        FMI_WEIGHTS[i] * safe_int(g["tries"]) for i, g in enumerate(recent)
    )
    # Re-normalise weights if fewer than 4 games are available, so the
    # figure isn't artificially deflated just because a player is early
    # in the season -- e.g. with only 2 games, use 0.40/0.30 rescaled to
    # sum to 1, not left summing to 0.70.
    weight_sum_used = sum(FMI_WEIGHTS[:n_recent])
    fmi_raw = fmi_raw / weight_sum_used if weight_sum_used > 0 else 0.0

    fmi_blend_weight = _fmi_blend_weight(n_recent)
    blended_try_rate = fmi_blend_weight * fmi_raw + (1 - fmi_blend_weight) * base_tpg_adjusted

    return fmi_raw, blended_try_rate


def _fmi_blend_weight(n_recent):
    """
    FMI's share of the blend, as a function of how many real recent
    games are actually available. Spec-given anchors: n=1 -> 0.25,
    n>=4 -> 0.45. n=2 and n=3 (not explicitly given by the spec) are
    linearly interpolated between those two anchors, rather than
    jumping straight to 0.45 -- see component_2_fmi's docstring for why
    this was added. n=0 -> 0.0 (FMI has nothing to contribute).
    """
    if n_recent <= 0:
        return 0.0
    if n_recent == 1:
        return 0.25
    if n_recent >= 4:
        return 0.45
    return 0.25 + (0.45 - 0.25) * (n_recent - 1) / 3


# ----------------------------------------------------------------------
# Component 3 -- IQS (Involvement Quality Score) multiplier
# ----------------------------------------------------------------------

IQS_STAT_WEIGHTS = {
    "line_breaks": 4.0,
    "tackle_breaks": 2.0,
    "all_run_metres": 0.02,
    "all_runs": 0.15,
    # post_contact_metres removed 2026-07-04 (Stage 7 finding) -- see the
    # module docstring's "STAGE 7 REAL FINDING" note. A real, standardized
    # logistic regression against 2,612 real player-round observations
    # showed this stat's true relationship with future try probability is
    # NEGATIVE and statistically significant (coef=-0.330, p=0.016) --
    # the opposite direction from its small positive weight here. Removed
    # rather than flipped: the regression didn't control for position
    # (forwards accumulate post-contact metres grinding through tackles
    # but score far less than backs), so the negative sign may be a
    # position confound rather than the stat's real individual effect --
    # not confident enough in EITHER sign to keep it weighted. Revisit
    # with a position-controlled test before re-adding in any direction.
    "inside_10_metres": 0.5,
    "kick_return_metres": 0.01,
}


def _iqs_per_minute(game_row):
    """
    Single game's IQS-per-minute, or None if the player didn't actually
    take the field (mins_played == '-'). A DNP has no rate, not a
    zero rate -- see design decision 3 in the module docstring.
    """
    mins = parse_mins_played(game_row["mins_played"])
    if mins is None or mins <= 0:
        return None
    raw_iqs = sum(
        weight * safe_float(game_row[stat]) for stat, weight in IQS_STAT_WEIGHTS.items()
    )
    return raw_iqs / mins


def component_3_iqs(games, recent_n=4):
    """
    Per-minute weighted blend of involvement stats (confirmed real
    columns and values in nrl_master.csv). IQS multiplier = recent
    IQS/min over the last recent_n games ACTUALLY PLAYED (DNP games
    excluded entirely from both season and recent averages, not
    included as zero) divided by season IQS/min, capped to [0.6, 1.5].

    Returns (season_iqs_per_min, recent_iqs_per_min, iqs_multiplier).
    If there's no usable season IQS/min (e.g. every game was a DNP, or
    the player has zero minutes throughout -- shouldn't happen for
    anyone in by_player but guarded anyway), returns a neutral 1.0
    multiplier rather than dividing by zero.
    """
    played_rates = [
        r for r in (_iqs_per_minute(g) for g in games) if r is not None
    ]
    if not played_rates:
        return None, None, 1.0

    season_iqs_per_min = sum(played_rates) / len(played_rates)

    recent_rates = played_rates[-recent_n:]
    recent_iqs_per_min = sum(recent_rates) / len(recent_rates)

    if season_iqs_per_min <= 0:
        return season_iqs_per_min, recent_iqs_per_min, 1.0

    raw_multiplier = recent_iqs_per_min / season_iqs_per_min
    iqs_multiplier = clip(raw_multiplier, 0.6, 1.5)

    return season_iqs_per_min, recent_iqs_per_min, iqs_multiplier


# ----------------------------------------------------------------------
# Component 4 -- Zone Concede Rate (ZCR)
# ----------------------------------------------------------------------

def component_4_zcr(position_code, opponent_team_full, weighted_zcr_lookup,
                     league_avg_zcr_by_position, weighted_team_overall_zcr=None,
                     league_avg_overall_zcr=None):
    """
    Opponent's tries conceded per game at that position, divided by the
    league average for that position. Blend: 70% position-specific +
    30% overall team defensive rate.

    Uses Phase 7's recency+confidence-weighted ZCR (same source
    due_flags_v2.py already consumes via recency_weighted_baselines.py)
    in preference to the flat baseline, for the same reason as
    Component 1 -- Phase 7 exists specifically to replace flat
    baselines with a better-evidenced version.

    The "overall team defensive rate" (30% piece) isn't a separate
    column anywhere -- derived here as the team's average ZCR across
    ALL positions (weighted by games faced at each position), vs the
    league-wide average ZCR across all positions. If the caller doesn't
    supply weighted_team_overall_zcr/league_avg_overall_zcr (e.g. not
    yet computed), falls back to 100% position-specific rather than
    guessing the overall-rate piece -- flagged via the returned
    used_full_blend flag so callers can see when this happened.

    Returns (position_zcr_ratio, overall_zcr_ratio_or_None, zcr_factor,
    used_full_blend).
    """
    position_rate = weighted_zcr_lookup.get((opponent_team_full, position_code))
    league_avg_position = league_avg_zcr_by_position.get(position_code)

    if position_rate is None or not league_avg_position or league_avg_position <= 0:
        # No real data for this (team, position) -- never guess. Neutral
        # factor, flagged via None values so callers know it's missing.
        return None, None, 1.0, False

    position_zcr_ratio = position_rate / league_avg_position

    if weighted_team_overall_zcr is not None and league_avg_overall_zcr:
        overall_rate = weighted_team_overall_zcr.get(opponent_team_full)
        if overall_rate is not None and league_avg_overall_zcr > 0:
            overall_zcr_ratio = overall_rate / league_avg_overall_zcr
            zcr_factor = 0.70 * position_zcr_ratio + 0.30 * overall_zcr_ratio
            return position_zcr_ratio, overall_zcr_ratio, zcr_factor, True

    # Overall-rate piece unavailable -- use position-specific alone.
    return position_zcr_ratio, None, position_zcr_ratio, False


def build_team_overall_zcr(weighted_zcr_lookup, position_games_by_team):
    """
    Team's average ZCR across all positions, weighted by real games
    faced at each position (a team that's faced 400 WG-games and only
    50 PR-games this baseline period should have its overall rate
    dominated by the WG figure, not averaged flat across positions).

    position_games_by_team: dict of team_full -> {position_code: games}
    -- the real games-faced denominator, needed so this is a genuine
    weighted average and not a flat mean across positions of wildly
    different sample sizes.

    Returns dict: team_full -> weighted_overall_zcr, plus the
    league-wide equivalent for use as league_avg_overall_zcr.
    """
    team_overall = {}
    all_weighted_sum = 0.0
    all_weight_total = 0.0

    for team, pos_games in position_games_by_team.items():
        weighted_sum = 0.0
        weight_total = 0.0
        for position_code, games in pos_games.items():
            rate = weighted_zcr_lookup.get((team, position_code))
            if rate is None or games <= 0:
                continue
            weighted_sum += rate * games
            weight_total += games
            all_weighted_sum += rate * games
            all_weight_total += games
        if weight_total > 0:
            team_overall[team] = weighted_sum / weight_total

    league_avg_overall = all_weighted_sum / all_weight_total if all_weight_total > 0 else None
    return team_overall, league_avg_overall


# ----------------------------------------------------------------------
# Component 5 -- Personnel factor
# ----------------------------------------------------------------------

def component_5_personnel(defender_missing=False, defender_game_day_doubt=False,
                           defender_returning=False):
    """
    Adjusts the ATTACKING player's chance based on the OPPONENT's
    defensive personnel changes at the relevant position. This genuinely
    can't be derived from nrl_master.csv alone -- it needs team-list /
    injury-news information that only firms up close to kickoff (Job
    B's team-list polling, or a manual update). Caller supplies these
    as explicit booleans; if none are supplied (the common case most of
    the week, before team lists are confirmed), this returns a neutral
    1.0 -- never guesses personnel status.

    Spec values: defender missing -> +10-15% to that position's ZCR
    (read here as a 1.10-1.15x boost to the attacker's chance, using the
    midpoint 1.125x as a single deterministic value rather than a range
    -- if Sam wants the range to vary by something specific, e.g. the
    quality of the replacement, that's a refinement for later). Game-day
    doubt -> +5-8% (midpoint 1.065x). Returning defender -> "slight
    uplift to attacker" -- the spec doesn't give a number for this one,
    so a conservative 1.02x is used and explicitly flagged as a
    guessed placeholder, distinct from the other two which use real
    spec-given ranges.
    """
    factor = 1.0
    notes = []

    if defender_missing:
        factor *= 1.125
        notes.append("defender_missing: x1.125 (spec range 1.10-1.15, midpoint used)")
    if defender_game_day_doubt:
        factor *= 1.065
        notes.append("defender_game_day_doubt: x1.065 (spec range 1.05-1.08, midpoint used)")
    if defender_returning:
        factor *= 1.02
        notes.append("defender_returning: x1.02 (PLACEHOLDER -- spec gives no number for this one)")

    return factor, notes


# ----------------------------------------------------------------------
# Component 6 -- Ruck factor
# ----------------------------------------------------------------------

def _weighted_team_ptb_speed(rows):
    """
    Team-level average play-the-ball speed across the given rows,
    weighted by each player's involvement in that game -- NOT a flat
    mean of per-player averages. average_play_the_ball_speed is
    confirmed (2026-06-24) to be a per-player average already; flat-
    averaging averages across players with very different involvement
    would silently misweight them equally.

    REAL DATA PROBLEM FOUND 2026-06-24: the spec's natural weighting
    column, play_the_ball (a per-player count), is confirmed to be
    '0' for EVERY single row in the entire nrl_master.csv file (4,560
    rows checked) -- not a sampling artifact, a genuine total gap. The
    scraper's HEADER_MAP believes it's capturing this column but
    isn't, in practice. This needs fixing in the scraper itself
    (nrl_update_single_round.py) at some point -- flagging here rather
    than silently routing around it forever.

    Until that's fixed: receipts is used as the weighting proxy instead
    (confirmed real and populated -- 89.2% of rows non-zero/non-dash,
    vs play_the_ball's 0%). Receipts isn't a perfect stand-in for ruck
    involvement specifically, but it's the closest real, populated
    column for "how much this player actually handled the ball this
    game," which is the same underlying thing play_the_ball was meant
    to capture. Rows with no parsed speed or zero receipts are skipped,
    not treated as zero.
    """
    weighted_sum = 0.0
    weight_total = 0.0
    for row in rows:
        speed = parse_ptb_speed(row["average_play_the_ball_speed"])
        weight = safe_int(row["receipts"])  # proxy for play_the_ball, see docstring
        if speed is None or weight <= 0:
            continue
        weighted_sum += speed * weight
        weight_total += weight
    if weight_total == 0:
        return None
    return weighted_sum / weight_total


def build_team_ruck_speeds(master_rows, season, up_to_round):
    """
    For every team, two figures derived from real nrl_master.csv rows
    (season-to-date, rounds before up_to_round):
      - attacking_speed[team]: that team's own average PTB speed when
        attacking (their own players' rows).
      - speed_allowed[team]: the average PTB speed achieved by teams
        THAT TEAM HAS DEFENDED AGAINST, i.e. for each opponent's row
        where row['opponent'] == team, that's a measure of how fast
        opponents have been able to play the ball against this team's
        defence. nrl.com doesn't expose a separate "ruck speed allowed"
        column -- this is derived from the real opponent column, a
        reasonable reading of the spec but not a verified-exact match
        to original intent (flagged in the module docstring's decision
        4 as well).

    Returns (attacking_speed, speed_allowed), both dict: team -> seconds.
    """
    rows_by_team = defaultdict(list)
    rows_against_team = defaultdict(list)

    for row in master_rows:
        if row["season"] != str(season):
            continue
        if safe_int(row["round"]) >= up_to_round:
            continue
        rows_by_team[row["team"]].append(row)
        rows_against_team[row["opponent"]].append(row)

    attacking_speed = {
        team: _weighted_team_ptb_speed(rows) for team, rows in rows_by_team.items()
    }
    speed_allowed = {
        team: _weighted_team_ptb_speed(rows) for team, rows in rows_against_team.items()
    }
    return attacking_speed, speed_allowed


def component_6_ruck_factor(attacking_team, opponent_team, attacking_speed, speed_allowed):
    """
    (opponent's avg ruck speed allowed) - (attacking team's avg ruck
    speed). Each 0.1s difference = ~3% adjustment, capped +/-15%.

    Lower PTB speed in seconds = faster play-the-ball (less time per
    play-the-ball is faster ruck speed) -- so if the opponent ALLOWS a
    slower (higher-seconds) ruck speed than the attacking team normally
    plays at, that's a SLOWER ruck for the attacking team in this match
    (negative for them -- slow ruck = less attacking opportunity), and
    vice versa. Sign convention here: positive raw_diff_seconds means
    the attacking team should get to play FASTER than the opponent
    typically allows -- i.e. opponent_speed_allowed > attacking_team's
    own_speed (opponent allows a slower/higher-seconds speed than this
    team normally achieves) gives a POSITIVE adjustment for the
    attacker. Implemented as:
        raw_diff = speed_allowed[opponent] - attacking_speed[attacking_team]
    Returns None (neutral 1.0) if either figure is unavailable for real
    data reasons (e.g. team hasn't played yet this season) -- never
    guesses a ruck speed.
    """
    opp_speed_allowed = speed_allowed.get(opponent_team)
    own_speed = attacking_speed.get(attacking_team)

    if opp_speed_allowed is None or own_speed is None:
        return None, 1.0

    raw_diff_seconds = opp_speed_allowed - own_speed
    pct_adjustment = (raw_diff_seconds / 0.1) * 0.03
    pct_adjustment = clip(pct_adjustment, -0.15, 0.15)
    ruck_factor = 1.0 + pct_adjustment

    return raw_diff_seconds, ruck_factor


# ----------------------------------------------------------------------
# Component 7 -- Attack share
# ----------------------------------------------------------------------

def component_7_attack_share(games, team, team_season_tries, team_games_played=None):
    """
    Player's share of team's season tries, divided by league-average
    share (1/17 ~ 5.9%, since there are 17 NRL teams -- confirmed real
    count via team_aliases.json's canonical_teams list). share_factor
    capped to [0.5, 3.0], then attack_share = 1.0 + log(share_factor)*0.3.

    Using log() means a player at EXACTLY league-average share
    (share_factor=1.0) gives attack_share=1.0 (neutral, log(1)=0) --
    confirms the formula is well-behaved at its centre point, not an
    arbitrary asymmetric curve.

    SMALL-SAMPLE SHRINKAGE (added 2026-06-24, after early-season testing
    against real Round 5 data traced the actual root cause of excess
    65%-cap-hitting to THIS component, not FMI -- see commit history /
    session notes). player_try_share is a ratio of two small integers
    early in the season (e.g. Alex Johnston: 4 tries / 14 team-tries
    after just 4 real rounds), and confirmed against his own real
    round-by-round data that this ratio swings wildly early (0.143 ->
    0.300 -> 0.286 in the first 3 rounds alone) before settling down
    around round 7-8 once team_season_tries reaches roughly 30-35 (the
    real point his share visibly stabilises, confirmed by inspection of
    his actual round-by-round numbers, not assumed).

    Fix: shrink player_try_share toward the league-average share
    (1/17) using the same credibility-weighting style as Component 1,
    keyed on TEAM games played (not the player's own games -- the
    denominator's reliability depends on how many team-tries have
    accumulated, which tracks team games, not individual appearances).
    CREDIBILITY_TEAM_GAMES=8 chosen from the real observed settling
    point above (~30-35 team tries / ~4.25 real avg tries-per-game =~
    7-8 team games).

    team_games_played: real count of team games played so far this
    season (NOT the player's own games_played) -- if not supplied,
    falls back to NO shrinkage (shrink_weight=1.0, i.e. original
    unshrunk behaviour), since the caller may not always have this
    figure handy and an unsupplied value shouldn't silently apply a
    guessed amount of shrinkage.

    Returns (player_try_share, share_factor, attack_share_multiplier).
    Returns neutral 1.0 if team_season_tries is 0 (team hasn't scored
    yet, e.g. round 1 before any tries logged) rather than dividing by
    zero.
    """
    if team_season_tries <= 0:
        return 0.0, 1.0, 1.0

    player_tries = sum(safe_int(g["tries"]) for g in games)
    raw_player_try_share = player_tries / team_season_tries

    LEAGUE_AVG_SHARE = 1.0 / 17.0  # 17 real NRL teams, confirmed via team_aliases.json
    # Taken literally from the spec text, which itself wrote "1/17 ~
    # 5.9%" -- this is the stated comparator, not independently derived.
    # The conceptual reasoning behind using "1 / (number of NRL teams)"
    # as a player's expected share of their OWN team's tries isn't
    # spelled out in the spec (it doesn't obviously follow from team
    # squad size, which is ~17 active players, a coincidentally
    # identical number to the league's team count) -- implemented as
    # written since the spec is explicit about the value, not the
    # reasoning.

    if team_games_played is not None and team_games_played > 0:
        CREDIBILITY_TEAM_GAMES = 8.0
        shrink_weight = team_games_played / (team_games_played + CREDIBILITY_TEAM_GAMES)
        player_try_share = (
            shrink_weight * raw_player_try_share + (1 - shrink_weight) * LEAGUE_AVG_SHARE
        )
    else:
        player_try_share = raw_player_try_share

    raw_share_factor = player_try_share / LEAGUE_AVG_SHARE
    share_factor = clip(raw_share_factor, 0.5, 3.0)

    attack_share_multiplier = 1.0 + math.log(share_factor) * 0.3

    return player_try_share, share_factor, attack_share_multiplier


# ----------------------------------------------------------------------
# Component 8 -- Context
# ----------------------------------------------------------------------

OUTSIDE_BACKS = {"FB", "WG", "CE"}
FORWARDS_AND_PLAYMAKERS = {"FE", "HB", "HK", "PR", "2RF", "LK"}
# IC (interchange) deliberately not bucketed into either group -- the
# spec's home-ground split is framed around playing-position archetype
# (outside backs vs forwards/playmakers), and "interchange" describes a
# bench role rather than an on-field archetype. Defaults to no home/away
# adjustment for IC rather than guessing which bucket they'd fall into
# once on the field.


def component_8_context(position_code, is_home, games_since_return_from_injury=None,
                         games_since_rep_return=None, was_dropped_and_recalled=False,
                         scored_last_game=False, due_flag_severity=None):
    """
    Combines several independent situational multipliers (spec doesn't
    say these stack multiplicatively vs additively -- multiplicative is
    used here, consistent with every other component in the chain being
    multiplicative against a base rate, and because each represents a
    genuinely distinct, mostly-independent situational factor rather
    than overlapping variants of the same thing).

    - Home ground advantage: outside backs (FB/WG/CE) x1.06, forwards/
      playmakers (FE/HB/HK/PR/2RF/LK) x1.03. No adjustment for IC or
      away games.
    - Return from injury: game 1 back x0.82, games 2-3 back x1.05.
      games_since_return_from_injury: 0 = this is their return game,
      1 or 2 = their 2nd/3rd game back, None = not a return situation.
    - Representative (rep) return: game 1 back x0.92.
      games_since_rep_return: 0 = this is their first game back from
      rep duty, None = not applicable.
    - Dropped-and-recalled: x1.10 if was_dropped_and_recalled.
    - Scored last game: x0.95 (mild regression-to-mean discount) if
      scored_last_game.
    - DUE flag: severity-based boost, capped at 1.30x. due_flag_severity
      expected as a 0-1 float (e.g. straight from due_flags_v2.py's
      composite_score after rescaling -1..1 to 0..1, or None if not
      flagged) -- linearly mapped to 1.0-1.30x. The spec says
      "severity-based, capped 1.30x" without an exact mapping function;
      linear is used as the simplest faithful reading, flagged as an
      interpretation rather than a confirmed-exact match.

    All inputs default to "not applicable" (None/False) -- a context
    factor with no real situational information supplied returns a
    neutral 1.0, never guesses that a situation applies.

    Returns (context_multiplier, notes) where notes lists which
    sub-factors actually fired, for visibility in output.
    """
    factor = 1.0
    notes = []

    if is_home:
        if position_code in OUTSIDE_BACKS:
            factor *= 1.06
            notes.append("home_outside_back: x1.06")
        elif position_code in FORWARDS_AND_PLAYMAKERS:
            factor *= 1.03
            notes.append("home_forward_playmaker: x1.03")

    if games_since_return_from_injury == 0:
        factor *= 0.82
        notes.append("injury_return_game1: x0.82")
    elif games_since_return_from_injury in (1, 2):
        factor *= 1.05
        notes.append(f"injury_return_game{games_since_return_from_injury + 1}: x1.05")

    if games_since_rep_return == 0:
        factor *= 0.92
        notes.append("rep_return_game1: x0.92")

    if was_dropped_and_recalled:
        factor *= 1.10
        notes.append("dropped_and_recalled: x1.10")

    if scored_last_game:
        factor *= 0.95
        notes.append("scored_last_game: x0.95")

    if due_flag_severity is not None:
        severity = clip(due_flag_severity, 0.0, 1.0)
        due_multiplier = 1.0 + severity * 0.30
        factor *= due_multiplier
        notes.append(f"due_flag(severity={severity:.2f}): x{due_multiplier:.3f}")

    return factor, notes


# ----------------------------------------------------------------------
# Top-level assembly: one player's raw xTry score for one match
# ----------------------------------------------------------------------

def calculate_player_xtry_raw(
    player_name, games, position_code, team, opponent_team_full, is_home,
    weighted_league_tpg_by_position, weighted_zcr_lookup, league_avg_zcr_by_position,
    team_season_tries, attacking_speed, speed_allowed,
    weighted_team_overall_zcr=None, league_avg_overall_zcr=None,
    team_games_played=None,
    defender_missing=False, defender_game_day_doubt=False, defender_returning=False,
    games_since_return_from_injury=None, games_since_rep_return=None,
    was_dropped_and_recalled=False, scored_last_game=False, due_flag_severity=None,
):
    """
    Assembles all 8 components into one player's raw (pre-normalisation)
    xTry score for a single upcoming match. Returns a dict with the raw
    score plus every component's contributing value, so the digest/
    output layer can show WHY a player scored what they did (same
    transparency principle due_flags_v2.py already follows -- never a
    black-box number).

    NOTE on chain structure: components 1 and 2 collapse into a single
    blended try-rate (see component_2_fmi's docstring for why -- units
    consistency), which then gets multiplied by the six genuine
    ratio-multipliers (3, 4, 5, 6, 7, 8) in sequence.
    """
    raw_season_tpg, base_tpg_adjusted, expected_minutes = component_1_base_tpg(
        games, position_code, weighted_league_tpg_by_position
    )
    fmi_raw, blended_try_rate = component_2_fmi(games, base_tpg_adjusted)

    season_iqs, recent_iqs, iqs_mult = component_3_iqs(games)

    zcr_pos_ratio, zcr_overall_ratio, zcr_factor, zcr_used_full_blend = component_4_zcr(
        position_code, opponent_team_full, weighted_zcr_lookup,
        league_avg_zcr_by_position, weighted_team_overall_zcr, league_avg_overall_zcr
    )
    if zcr_factor is None:
        zcr_factor = 1.0

    personnel_factor, personnel_notes = component_5_personnel(
        defender_missing, defender_game_day_doubt, defender_returning
    )

    ruck_diff, ruck_factor = component_6_ruck_factor(
        team, opponent_team_full, attacking_speed, speed_allowed
    )

    player_try_share, share_factor, attack_share_mult = component_7_attack_share(
        games, team, team_season_tries, team_games_played
    )

    context_mult, context_notes = component_8_context(
        position_code, is_home, games_since_return_from_injury, games_since_rep_return,
        was_dropped_and_recalled, scored_last_game, due_flag_severity
    )

    raw_xtry = (
        blended_try_rate * iqs_mult * zcr_factor * personnel_factor
        * ruck_factor * attack_share_mult * context_mult
    )

    return {
        "player_name": player_name,
        "team": team,
        "position_code": position_code,
        "opponent": opponent_team_full,
        "is_home": is_home,
        "raw_xtry": raw_xtry,
        "components": {
            "n_games": len(games),  # exposed for decision_engine's uncertainty penalty (1/sqrt(n))
            "raw_season_tpg": round(raw_season_tpg, 4),
            "base_tpg_adjusted": round(base_tpg_adjusted, 4),
            "expected_minutes": round(expected_minutes, 1) if expected_minutes is not None else None,
            "fmi_raw": round(fmi_raw, 4) if fmi_raw is not None else None,
            "blended_try_rate": round(blended_try_rate, 4),
            "season_iqs_per_min": round(season_iqs, 4) if season_iqs is not None else None,
            "recent_iqs_per_min": round(recent_iqs, 4) if recent_iqs is not None else None,
            "iqs_multiplier": round(iqs_mult, 4),
            "zcr_position_ratio": round(zcr_pos_ratio, 4) if zcr_pos_ratio is not None else None,
            "zcr_overall_ratio": round(zcr_overall_ratio, 4) if zcr_overall_ratio is not None else None,
            "zcr_factor": round(zcr_factor, 4),
            "zcr_used_full_blend": zcr_used_full_blend,
            "personnel_factor": round(personnel_factor, 4),
            "personnel_notes": personnel_notes,
            "ruck_diff_seconds": round(ruck_diff, 4) if ruck_diff is not None else None,
            "ruck_factor": round(ruck_factor, 4),
            "player_try_share": round(player_try_share, 4),
            "attack_share_factor": round(share_factor, 4),
            "attack_share_multiplier": round(attack_share_mult, 4),
            "context_multiplier": round(context_mult, 4),
            "context_notes": context_notes,
        },
    }


# ----------------------------------------------------------------------
# Normalisation across a match
# ----------------------------------------------------------------------

def compute_real_avg_tries_per_team_per_game(master_rows, season, up_to_round):
    """
    The real season-to-date average tries scored per team per game,
    computed live from nrl_master.csv rather than hardcoding the spec's
    "~5-6" guess. Kept accurate as the season progresses instead of
    going stale against an invented constant.
    """
    team_round_tries = defaultdict(lambda: defaultdict(int))
    for row in master_rows:
        if row["season"] != str(season):
            continue
        if safe_int(row["round"]) >= up_to_round:
            continue
        team_round_tries[row["team"]][safe_int(row["round"])] += safe_int(row["tries"])

    all_team_game_tries = [
        tries for rounds in team_round_tries.values() for tries in rounds.values()
    ]
    if not all_team_game_tries:
        return None
    return sum(all_team_game_tries) / len(all_team_game_tries)


def normalise_match_xtry(home_team_raw_scores, away_team_raw_scores, real_avg_tries_per_team):
    """
    Scales BOTH teams' raw xTry scores so each team's total matches the
    real season-to-date average tries/team/game (NOT a fixed "5-6"
    guess -- see compute_real_avg_tries_per_team_per_game). Each team is
    scaled independently against the SAME real average, since the spec
    doesn't suggest the two teams in a match should share one combined
    pool -- each team's own players compete for that team's expected
    tries, not a cross-team pool.

    Then caps each player's final probability-like display value to
    60-65% max (65% used as the single cap, since the spec gives a
    range without saying which end is the hard ceiling -- flagged as an
    interpretation), with "smokies" (low raw score players) landing in
    the 16-20% band naturally from the scaling rather than a separate
    rule -- the spec doesn't define "smokies" as anything other than an
    expected OUTCOME of correct scaling, not an additional adjustment
    step, so no extra code enforces that band specifically; it's a
    real-data check to run once results are in, not a constraint to
    code against blindly.

    Returns: dict of player_name -> {raw_xtry, scaled_xtry, display_pct}
    for each of the two team's player lists combined.
    """
    results = {}

    for team_scores in (home_team_raw_scores, away_team_raw_scores):
        if not team_scores:
            continue
        raw_total = sum(p["raw_xtry"] for p in team_scores)
        if raw_total <= 0:
            scale = 0.0
        else:
            scale = real_avg_tries_per_team / raw_total

        for p in team_scores:
            scaled_xtry = p["raw_xtry"] * scale
            # scaled_xtry is now in "expected tries this match" units.
            # Convert to a try-scoring PROBABILITY via Poisson:
            # P(>=1 try) = 1 - e^(-expected_tries).
            display_prob = 1 - math.exp(-scaled_xtry)
            display_prob_capped = clip(display_prob, 0.0, 0.65)

            results[p["player_name"]] = {
                "raw_xtry": round(p["raw_xtry"], 4),
                "scaled_xtry_expected_tries": round(scaled_xtry, 4),
                "display_probability": round(display_prob_capped, 4),
                "components": p["components"],
                "team": p["team"],
                "position_code": p["position_code"],
            }

    return results
