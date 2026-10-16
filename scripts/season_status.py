"""
season_status.py
================
Tells the scheduled jobs whether the NRL season is on, over, or over for too long.

Why this exists: the weekly jobs work out their round as "the highest round in
nrl_master.csv, plus one". When the Grand Final is in, that is round 32, which
does not exist, so every Wednesday of the summer would fail. They should stay
quiet instead, but never silently: if the next season is close and the bot still
isn't set up for it, that must go red.

States printed (key=value lines, ready for $GITHUB_OUTPUT):
    in_season           run normally
    off_season          the Grand Final of the latest season is in: skip quietly
    off_season_overdue  still off-season from 1 February of the next year: go red,
                        the new season's setup (the "pick up each new season's
                        draw" job) isn't done

The Grand Final is spotted from the data, not a hard-coded round: the latest
round of the latest season has exactly one match (a regular round never does).
If anything can't be read, the answer is in_season, so real work is never skipped
by a bug here.

Next round is worked out per season: the highest round of the latest season,
plus one.

Usage:
    python3 scripts/season_status.py            # prints state=...
    python3 scripts/season_status.py --next-round
"""

import argparse
import csv
import sys
from collections import Counter
from datetime import date
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
MIN_GRAND_FINAL_ROUND = 27  # a one-match round before this can't be a Grand Final
OVERDUE_MONTH, OVERDUE_DAY = 2, 1  # 1 Feb of the next year


def read_rounds(path):
    """(season, round) for every row, skipping rows that aren't whole numbers."""
    out = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                out.append((int(row["season"]), int(row["round"])))
            except (KeyError, TypeError, ValueError):
                continue
    return out


def latest_season_and_round(master_rows):
    if not master_rows:
        return None, None
    season = max(s for s, _ in master_rows)
    return season, max(r for s, r in master_rows if s == season)


def matches_in_round(match_rows, season, rnd):
    return sum(1 for s, r in match_rows if s == season and r == rnd)


def status(master_rows, match_rows, today):
    """-> dict(state, season, last_round, next_round, reason)."""
    season, last = latest_season_and_round(master_rows)
    if season is None:
        return {"state": "in_season", "season": None, "last_round": None, "next_round": 1, "reason": "no data yet"}
    nxt = last + 1
    grand_final_in = last >= MIN_GRAND_FINAL_ROUND and matches_in_round(match_rows, season, last) == 1
    if not grand_final_in:
        return {"state": "in_season", "season": season, "last_round": last, "next_round": nxt, "reason": "season in progress"}
    overdue_from = date(season + 1, OVERDUE_MONTH, OVERDUE_DAY)
    if today >= overdue_from:
        return {"state": "off_season_overdue", "season": season, "last_round": last, "next_round": nxt,
                "reason": f"the {season} season ended at round {last} and the next one is close ({overdue_from} or later), "
                          f"but the bot has no {season + 1} data and isn't set up for the new season"}
    return {"state": "off_season", "season": season, "last_round": last, "next_round": nxt,
            "reason": f"season over: the {season} Grand Final (round {last}) is in; next season starts around March"}


def load(path):
    try:
        return read_rounds(path)
    except OSError:
        return []


def main(argv=None, today=None):
    p = argparse.ArgumentParser()
    p.add_argument("--next-round", action="store_true", help="print only the next round number")
    p.add_argument("--data-dir", default=str(DATA))
    args = p.parse_args(argv)
    today = today or date.today()
    try:
        d = Path(args.data_dir)
        result = status(load(d / "nrl_master.csv"), load(d / "match_data_FINAL_fixed.csv"), today)
    except Exception as e:  # never let a bug here skip real work
        result = {"state": "in_season", "season": None, "last_round": None, "next_round": None,
                  "reason": f"could not work out the season state ({e}); running normally"}
    if args.next_round:
        if result["next_round"] is None:
            return 1
        print(result["next_round"])
        return 0
    for k in ("state", "season", "last_round", "next_round", "reason"):
        print(f"{k}={'' if result[k] is None else result[k]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
