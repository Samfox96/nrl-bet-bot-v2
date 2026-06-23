"""
generate_round_digest.py

Phase 5: builds a plain-English "what happened this round" digest after
Job A's clean merge into nrl_master.csv. Designed to be called with the
round number that was just merged; compares that round's data against
the player's own season-to-date average, league/position norms, and the
2021-2025 ZCR baseline.

REAL DATA FINDINGS THIS WAS BUILT AGAINST (confirmed 2026-06-23, not
assumed -- see Phase 4's parser for why this matters):

  - nrl_master.csv stores SHORT team names ("Knights", "Dragons"), while
    historical_zcr_baseline.csv's `defending_team` column stores FULL
    canonical names ("Newcastle Knights", "St George Illawarra Dragons").
    Every short name in nrl_master.csv was confirmed to resolve cleanly
    via team_aliases.json's aliases dict -- direct lookup, no fallback
    logic needed (unlike Phase 4's parser, which needed a punctuation-
    stripping fallback for "St. George..." from a different source).

  - nrl_master.csv stores FULL position labels ("2nd Row", "Centre",
    "Replacement", "Reserve"), while historical_zcr_baseline.csv and
    historical_position_tpg_baseline.csv use canonical CODES ("2RF", "CE",
    "IC"). Confirmed every nrl_master.csv position value resolves via
    position_aliases.json -- including the many-to-one case where BOTH
    "Replacement" and "Reserve" map to the single code "IC". A naive
    direct-string join would silently produce zero matches for any
    interchange player, exactly as the team-name mismatch did on first
    attempt in the Phase 4 session.

  - historical_position_tpg_baseline.csv has a `season` column (2021-2025
    each present separately) and must be filtered to a specific season
    before use, per established project convention -- the 2021-2025
    AGGREGATE across all seasons is used here for the season-norm
    comparison, consistent with how historical_zcr_baseline.csv (which
    has no season column at all) is already used as an aggregate
    baseline elsewhere in this project.

  - DUE-flag eligibility, per the project's own Data Quality Rules:
    tries are divided by games actually appeared in, never by rounds
    elapsed, and a player needs >= 8 games played before a TPG multiple
    is considered meaningful. Same threshold is used here.

WHAT THIS DOES NOT DO (explicit, not an oversight):
  - No real betting-market "line movement" -- Phase 10 (odds comparison)
    isn't built yet. "Line movements" in this digest means FORM trend
    movement (a player's recent TPG/metres vs their own season average),
    not bookmaker odds movement. Do not conflate the two in the email
    copy.
  - No week-over-week "NEW due flags since last digest" diff yet -- this
    requires snapshotting each week's DUE list to compare against. First
    run has nothing to diff against; this version reports the current
    week's DUE list each time, not deltas. A snapshot file
    (data/due_flags_last_run.json) is written each run specifically so a
    future version CAN diff against it -- but the diffing logic itself
    is intentionally not built yet, to avoid guessing at a format before
    there's two real runs to compare.
"""

import csv
import json
import os
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


def normalise_team(short_name, team_aliases):
    """nrl_master.csv short name -> canonical full name. Returns None,
    never guesses, if the short name isn't a recognised alias -- callers
    should treat that as a flag, not a silent skip."""
    return team_aliases.get(short_name)


def normalise_position(label, position_aliases):
    """nrl_master.csv full position label -> canonical code. Returns
    None, never guesses, if unrecognised."""
    return position_aliases.get(label)


def build_season_averages(master_rows, season, up_to_round):
    """
    Per-player season-to-date averages (tries per game, run metres per
    game, etc), computed over games actually played (mins_played not
    blank/zero), for rounds BEFORE up_to_round -- i.e. the player's form
    going into this round, not including this round itself, so "this
    round vs season average" is a genuine before/after comparison.

    Returns dict: player_name -> {games, tries_pg, run_metres_pg,
    tackle_breaks_pg, line_breaks_pg}
    """
    by_player = defaultdict(list)
    for row in master_rows:
        if row["season"] != str(season):
            continue
        if safe_int(row["round"]) >= up_to_round:
            continue
        by_player[row["player_name"]].append(row)

    averages = {}
    for player, rows in by_player.items():
        games = len(rows)
        if games == 0:
            continue
        averages[player] = {
            "games": games,
            "tries_pg": sum(safe_int(r["tries"]) for r in rows) / games,
            "run_metres_pg": sum(safe_int(r["all_run_metres"]) for r in rows) / games,
            "tackle_breaks_pg": sum(safe_int(r["tackle_breaks"]) for r in rows) / games,
            "line_breaks_pg": sum(safe_int(r["line_breaks"]) for r in rows) / games,
        }
    return averages


def top_performances(round_rows, n=5):
    """Standout individual stat-lines this round -- simple superlatives,
    no baseline needed. These are facts, not model outputs."""
    facts = []

    by_tries = sorted(round_rows, key=lambda r: safe_int(r["tries"]), reverse=True)
    if by_tries and safe_int(by_tries[0]["tries"]) >= 2:
        top = by_tries[0]
        facts.append(
            f"{top['player_name']} ({top['team']}) bagged {top['tries']} tries"
        )

    by_metres = sorted(round_rows, key=lambda r: safe_int(r["all_run_metres"]), reverse=True)
    if by_metres:
        top = by_metres[0]
        facts.append(
            f"{top['player_name']} ({top['team']}) led all running with "
            f"{top['all_run_metres']}m from {top['all_runs']} runs"
        )

    by_breaks = sorted(round_rows, key=lambda r: safe_int(r["tackle_breaks"]), reverse=True)
    if by_breaks:
        top = by_breaks[0]
        facts.append(
            f"{top['player_name']} ({top['team']}) broke the line {top['tackle_breaks']} times"
        )

    # Tackle efficiency among players with a genuine workload (avoid a
    # small-sample 100% from a player who made 2 tackles).
    workhorses = [r for r in round_rows if safe_int(r["tackles_made"]) >= 20]
    by_eff = sorted(workhorses, key=lambda r: safe_float(r["tackle_efficiency"]), reverse=True)
    if by_eff:
        top = by_eff[0]
        facts.append(
            f"{top['player_name']} ({top['team']}) was the defensive standout: "
            f"{top['tackle_efficiency']}% efficiency from {top['tackles_made']} tackles"
        )

    return facts


def form_trend_facts(round_rows, season_averages, min_games=4):
    """
    Compares this round's individual performances against each player's
    own season-to-date average -- genuine form movement, not betting
    odds. Flags the most significant positive and negative swings in
    tries and run metres. min_games guards against a single early-season
    game looking like a huge "swing" against a tiny sample average.
    """
    facts = []
    swings = []

    for row in round_rows:
        player = row["player_name"]
        avg = season_averages.get(player)
        if not avg or avg["games"] < min_games:
            continue

        this_round_metres = safe_int(row["all_run_metres"])
        metres_diff = this_round_metres - avg["run_metres_pg"]
        swings.append((player, row["team"], metres_diff, this_round_metres, avg["run_metres_pg"]))

    swings.sort(key=lambda x: x[2], reverse=True)
    if swings:
        player, team, diff, this_round, avg_val = swings[0]
        if diff > 40:  # meaningful breakout, not noise
            facts.append(
                f"{player} ({team}) ran for {this_round}m, well above his "
                f"season average of {avg_val:.0f}m — a real breakout game"
            )

    if swings:
        player, team, diff, this_round, avg_val = swings[-1]
        if diff < -40 and avg_val > 60:  # quiet game for someone who's normally productive
            facts.append(
                f"{player} ({team}) managed just {this_round}m, down from a "
                f"season average of {avg_val:.0f}m — a quiet one"
            )

    return facts


def due_flags(master_rows, season, up_to_round, position_aliases, position_tpg_baseline, min_games=8, top_n=None):
    """
    Players whose season TPG sits well below the league baseline for
    their position, per the project's DUE-flag principle: season TPG,
    not recent-drought-period TPG, and a minimum of 8 games played.

    Returns a list of dicts: {player_name, team, position_code,
    season_tpg, league_tpg, ratio}, sorted by how far below baseline
    they are (most "due" first). A player is flagged only if their
    season TPG is at least 40% below the league baseline for their
    position AND they've played enough games for that to mean something
    (>= min_games) AND the position itself has a meaningful scoring rate
    (skips e.g. props/hookers where a low TPG is just normal for the
    position, not a drought).
    """
    # Aggregate 2021-2025 league TPG by position code (consistent with
    # how historical_zcr_baseline.csv is already used as an all-season
    # aggregate elsewhere in this project).
    league_tpg_by_position = defaultdict(lambda: [0, 0])  # code -> [tries, games]
    for row in position_tpg_baseline:
        code = row["position"]  # baseline file already uses canonical codes
        league_tpg_by_position[code][0] += safe_int(row["total_tries"])
        league_tpg_by_position[code][1] += safe_int(row["total_player_games"])

    league_tpg = {
        code: (tries / games if games else 0)
        for code, (tries, games) in league_tpg_by_position.items()
    }

    by_player = defaultdict(list)
    for row in master_rows:
        if row["season"] != str(season):
            continue
        if safe_int(row["round"]) >= up_to_round:
            continue
        by_player[row["player_name"]].append(row)

    flags = []
    for player, rows in by_player.items():
        games = len(rows)
        if games < min_games:
            continue

        total_tries = sum(safe_int(r["tries"]) for r in rows)
        season_tpg = total_tries / games

        # A real DUE flag requires evidence the player is a credible
        # scoring threat in the first place -- a prop with 0 tries in 12
        # games isn't "due", that's just normal for the role. Without
        # this check, every non-try-scoring forward in the league would
        # be flagged, which is exactly what happened on first attempt
        # against real Round 16 data and is NOT a useful digest fact.
        if total_tries == 0:
            continue

        # Use this player's most recent position entry (positions can
        # shift -- interchange players especially -- so "most recent"
        # is more meaningful than "most frequent" for a DUE read).
        most_recent = sorted(rows, key=lambda r: safe_int(r["round"]))[-1]
        position_code = normalise_position(most_recent["position"], position_aliases)
        if position_code is None:
            continue  # flag via omission rather than guess a position

        baseline = league_tpg.get(position_code)
        if not baseline or baseline < 0.05:
            continue  # position doesn't score enough for "DUE" to be meaningful

        if season_tpg < baseline * 0.6:  # at least 40% below the league norm
            flags.append({
                "player_name": player,
                "team": rows[-1]["team"],
                "position_code": position_code,
                "season_tpg": round(season_tpg, 3),
                "league_tpg": round(baseline, 3),
                "ratio": round(season_tpg / baseline, 2) if baseline else None,
                "games": games,
                "total_tries": total_tries,
            })

    flags.sort(key=lambda f: f["ratio"])
    if top_n is not None:
        flags = flags[:top_n]
    return flags


def zcr_shift_facts(round_rows, round_num, team_aliases, zcr_baseline, n=3):
    """
    Compares each team's tries CONCEDED this round, by position, against
    their 2021-2025 ZCR baseline rate for that position. Surfaces teams
    whose defense at a given position let in more (or fewer) tries than
    their historical norm would suggest -- this is the real "ZCR shift"
    the project brief describes, using actual historical baseline data
    rather than a synthetic placeholder.

    Tries conceded this round, by (team, position), is derived from the
    OPPONENT's tries in nrl_master.csv -- e.g. if a Knights player scored
    a try as a Winger, that's one try CONCEDED by the Dragons (the
    Knights' opponent that round) at the WG position.
    """
    # Build canonical ZCR lookup: (team_full, position_code) -> concede_rate
    zcr_lookup = {}
    for row in zcr_baseline:
        zcr_lookup[(row["defending_team"], row["position"])] = safe_float(row["concede_rate"])

    # Tries conceded this round by (defending_team_short, position_code)
    conceded = defaultdict(int)
    position_aliases_path = "position_aliases.json"
    position_aliases = load_json(position_aliases_path)["aliases"]

    for row in round_rows:
        tries = safe_int(row["tries"])
        if tries == 0:
            continue
        position_code = normalise_position(row["position"], position_aliases)
        if position_code is None:
            continue
        # This try was scored AGAINST the opponent -- they conceded it.
        conceded[(row["opponent"], position_code)] += tries

    facts = []
    for (defending_team_short, position_code), tries_conceded in conceded.items():
        team_full = team_aliases.get(defending_team_short)
        if team_full is None:
            continue
        baseline_rate = zcr_lookup.get((team_full, position_code))
        if baseline_rate is None:
            continue
        # A single round conceding 2+ tries at a position with a low
        # historical concede rate for that position is a real signal,
        # not noise -- e.g. conceding 2 tries to props when the
        # historical rate suggests that's rare for this team.
        if tries_conceded >= 2 and baseline_rate < 0.3:
            facts.append(
                f"{defending_team_short} conceded {tries_conceded} tries to "
                f"{position_code}s this round — well above their historical "
                f"rate for that position ({baseline_rate:.0%} per game historically)"
            )

    return facts[:n]


def build_digest(master_csv_path, round_num, season,
                  team_aliases_path="team_aliases.json",
                  position_aliases_path="position_aliases.json",
                  zcr_baseline_path="historical_zcr_baseline.csv",
                  position_tpg_baseline_path="historical_position_tpg_baseline.csv"):
    """
    Top-level entry point. Returns a dict with all digest sections, ready
    to be handed to the email-formatting layer. Does NOT send anything --
    this function's only job is producing the content.
    """
    master_rows = load_csv(master_csv_path)
    team_aliases = load_json(team_aliases_path)["aliases"]
    position_aliases = load_json(position_aliases_path)["aliases"]
    zcr_baseline = load_csv(zcr_baseline_path)
    position_tpg_baseline = load_csv(position_tpg_baseline_path)

    round_rows = [r for r in master_rows if r["round"] == str(round_num) and r["season"] == str(season)]

    season_averages = build_season_averages(master_rows, season, up_to_round=round_num)

    digest = {
        "round": round_num,
        "season": season,
        "row_count": len(round_rows),
        "top_performances": top_performances(round_rows),
        "form_trends": form_trend_facts(round_rows, season_averages),
        "due_flags": due_flags(master_rows, season, round_num, position_aliases, position_tpg_baseline, top_n=5),
        "zcr_shifts": zcr_shift_facts(round_rows, round_num, team_aliases, zcr_baseline),
    }
    return digest


if __name__ == "__main__":
    # Self-test against real, live-pulled data (Round 16, the latest
    # complete round in nrl_master.csv as of 2026-06-23).
    digest = build_digest("nrl_master.csv", round_num=16, season=2026)
    print(json.dumps(digest, indent=2))
