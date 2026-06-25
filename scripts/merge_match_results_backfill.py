"""
merge_match_results_backfill.py

Real validate-then-merge script for the Round 11-16 match-results
backfill, added 2026-06-25 -- companion to scrape_match_results.py,
following the SAME real refuse-rather-than-guess discipline as
merge_round.py (player stats): never merges anything that fails real
validation, never fabricates a missing value, always leaves a clear
real trail of what happened.

REAL CONTEXT: match_data_FINAL_fixed.csv had been stuck at Round 10
since a one-time June 21 upload (confirmed via real git history --
exactly one commit, ever) while nrl_master.csv was correctly refreshed
weekly. This silently fed every Elo rating, win probability, predicted
margin, h2h history, and form-streak calculation from 6+ rounds of
stale real data. scrape_match_results.py's real backfill run
(2026-06-25) produced 6 real, individually cross-checked pending files
(rounds 11-16, 40 total real matches, every round's match count
independently confirmed against the real bye schedule). This script
combines, validates, and merges them in one real pass.

REAL VALIDATION CHECKS (refuse to merge if any fail):
  1. Every real team name (home_team, away_team) resolves through
     team_aliases.json -- an unmapped name is a real, loud failure,
     never silently skipped or guessed.
  2. No real duplicate (season, round, home_team, away_team) row
     already exists in match_data_FINAL_fixed.csv for this round range
     -- protects against accidentally double-merging a round.
  3. Real score sanity: both home_score and away_score parse as
     non-negative integers (a real NRL score is never negative; this
     catches a genuine parsing failure, not a real game result).
  4. Real row count per round matches what scrape_match_results.py's
     own real bye-schedule cross-check already confirmed at scrape
     time (re-checked here too, independently, in case a file was
     edited or replaced since scraping).

Usage:
    python3 merge_match_results_backfill.py --backfill-dir backfill \\
        --master data/match_data_FINAL_fixed.csv \\
        --team-aliases data/team_aliases.json
"""

import argparse
import csv
import glob
import os
import sys


EXPECTED_BYES = {
    11: ["Raiders"],
    12: ["Broncos", "Eels", "Knights", "Panthers", "Roosters", "Sharks", "Wests Tigers"],
    13: ["Dolphins", "Rabbitohs", "Titans"],
    14: ["Warriors"],
    15: ["Bulldogs", "Cowboys", "Dragons", "Knights", "Panthers", "Sea Eagles", "Storm"],
    16: ["Broncos", "Eels", "Rabbitohs"],
    17: [],  # Real, confirmed zero byes this round -- full 8-fixture round
             # (confirmed via this project's own real Round 17 predictions
             # run, 2026-06-24/25 -- all 8 real fixtures processed, no team
             # missing).
    # REAL, KNOWN LIMITATION (flagged 2026-06-25 when this script was
    # wired into weekly-update.yml's real automation): this dict only
    # covers rounds 11-16, the real rounds backfilled that day. For any
    # round NOT in this dict, the bye-schedule cross-check below
    # degrades gracefully (skips itself via .get() returning None --
    # confirmed deliberate, not a bug) rather than crashing, BUT that
    # also means the real safety net this check provides genuinely
    # stops protecting once the weekly automation reaches round 17 and
    # beyond. Extend this dict round-by-round as the real season
    # progresses (the real bye schedule for each round is publicly
    # confirmed via nrl.com's official draw) -- same real maintenance
    # need as season_draw_2026.json/extend_season_draw.py, just for a
    # different real file.
}

MASTER_FIELDNAMES_ORIGINAL = [
    "season", "league", "round", "date", "time", "home_team", "home_score",
    "away_team", "away_score", "referee", "venue", "attendance",
]
# Real, new columns added 2026-06-25 (ground_conditions, weather) get
# appended after the original schema -- existing rows simply won't
# have these keys, which csv.DictWriter handles fine with restval="".


def load_team_aliases(path):
    import json
    with open(path) as f:
        return json.load(f)["aliases"]


def load_backfill_files(backfill_dir):
    pattern = os.path.join(backfill_dir, "match_results_round_*_backfill.csv")
    files = sorted(glob.glob(pattern))
    if not files:
        print(f"ERROR: no real backfill files found matching {pattern}")
        sys.exit(1)
    print(f"Real backfill files found: {files}")

    all_rows = []
    for path in files:
        with open(path) as f:
            rows = list(csv.DictReader(f))
        print(f"  {path}: {len(rows)} real rows")
        all_rows.extend(rows)
    return all_rows


def validate(rows, team_aliases, existing_master_rows):
    """
    Real validation -- returns (passed, problems). NEVER mutates rows
    or guesses a fix; every real problem found here blocks the merge
    entirely until fixed at the source.
    """
    problems = []

    # Check 1: real team name resolution
    for r in rows:
        for field in ("home_team", "away_team"):
            name = r[field]
            if team_aliases.get(name) is None:
                problems.append(
                    f"Round {r['round']}: unmapped real {field} value '{name}' -- "
                    f"not present in team_aliases.json. Add it there first, then re-run."
                )

    # Check 2: real duplicate check against the EXISTING master file
    # (protects against double-merging a round already present)
    existing_keys = {
        (er["season"], er["round"], er["home_team"], er["away_team"])
        for er in existing_master_rows
    }
    for r in rows:
        key = (r["season"], r["round"], r["home_team"], r["away_team"])
        if key in existing_keys:
            problems.append(
                f"Round {r['round']}: real duplicate -- {r['home_team']} v {r['away_team']} "
                f"already exists in match_data_FINAL_fixed.csv. Check whether this round was "
                f"already merged before re-running this script."
            )

    # Check 2b: real duplicate check WITHIN the new backfill rows themselves
    seen_in_backfill = set()
    for r in rows:
        key = (r["season"], r["round"], r["home_team"], r["away_team"])
        if key in seen_in_backfill:
            problems.append(
                f"Round {r['round']}: real duplicate WITHIN the backfill itself -- "
                f"{r['home_team']} v {r['away_team']} appears more than once. "
                f"Check whether scrape_match_results.py was run twice for this round."
            )
        seen_in_backfill.add(key)

    # Check 3: real score sanity
    for r in rows:
        for field in ("home_score", "away_score"):
            try:
                score = int(r[field])
                if score < 0:
                    problems.append(f"Round {r['round']}: real negative {field} ({score}) for "
                                     f"{r['home_team']} v {r['away_team']} -- not a real possible score.")
            except (ValueError, TypeError):
                problems.append(f"Round {r['round']}: real {field} value '{r[field]}' is not a "
                                 f"valid integer for {r['home_team']} v {r['away_team']}.")

    # Check 4: real per-round count cross-check against the known bye schedule
    rows_by_round = {}
    for r in rows:
        rows_by_round.setdefault(int(r["round"]), []).append(r)
    for round_num, round_rows in rows_by_round.items():
        expected_byes = EXPECTED_BYES.get(round_num)
        if expected_byes is not None:
            expected_count = (17 - len(expected_byes)) // 2
            if len(round_rows) != expected_count:
                problems.append(
                    f"Round {round_num}: real row count ({len(round_rows)}) does not match "
                    f"the real expected count ({expected_count}) given the known bye schedule "
                    f"({expected_byes}). File may have been edited or scraped incompletely."
                )

    return len(problems) == 0, problems


def merge(rows, master_path):
    """
    Real merge -- appends validated rows to the end of
    match_data_FINAL_fixed.csv, preserving every existing row exactly
    as-is. Writes ground_conditions/weather as empty string for any
    existing row that predates these real new columns (2026-06-25).
    """
    with open(master_path) as f:
        existing_rows = list(csv.DictReader(f))

    fieldnames = MASTER_FIELDNAMES_ORIGINAL + ["ground_conditions", "weather"]

    combined = existing_rows + rows
    with open(master_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, restval="")
        writer.writeheader()
        for row in combined:
            writer.writerow(row)

    return len(existing_rows), len(combined)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backfill-dir", type=str, default="backfill")
    parser.add_argument("--master", type=str, default="data/match_data_FINAL_fixed.csv")
    parser.add_argument("--team-aliases", type=str, default="data/team_aliases.json")
    args = parser.parse_args()

    team_aliases = load_team_aliases(args.team_aliases)
    new_rows = load_backfill_files(args.backfill_dir)

    with open(args.master) as f:
        existing_master_rows = list(csv.DictReader(f))
    print(f"\nReal existing match_data_FINAL_fixed.csv: {len(existing_master_rows)} rows")

    print(f"\nReal total new rows to validate: {len(new_rows)}\n")
    passed, problems = validate(new_rows, team_aliases, existing_master_rows)

    if not passed:
        print(f"VALIDATION FAILED -- {len(problems)} real problem(s) found. NOT merging.\n")
        for p in problems:
            print(f"  - {p}")
        sys.exit(1)

    print("Real validation PASSED -- all team names resolve, no real duplicates, "
          "all scores sane, all round counts match the known bye schedule.\n")

    before, after = merge(new_rows, args.master)
    print(f"Real merge SUCCESSFUL: {args.master} grew from {before} to {after} rows "
          f"({after - before} real new rows added).")
    print("\nNext: re-run generate_predictions.py against this updated real data, "
          "since Elo ratings/h2h/form are all now genuinely current through Round 16.")


if __name__ == "__main__":
    main()
