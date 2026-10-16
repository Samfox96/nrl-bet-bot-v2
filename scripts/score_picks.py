"""
score_picks.py
==============
Once a round's results are in, marks every saved pick won, lost, push or void
and works out what the week's pretend money would have returned.

Reads data/picks_history/<season>_round_<n>.json (written by
build_weekly_picks.py with the prices seen at pick time), the real scores in
data/match_data_FINAL_fixed.csv and the real tries in data/nrl_master.csv, and
writes the results back into the same file. The existing accuracy ledger
(score_predictions.py) is not touched.

Results:
  try_scorer  won if the player scored a try; lost if he played and didn't;
              void if he has no row for the round (did not play: bookies refund)
  winner      won / lost on the final score; push on a draw (stake back)
  margin      the home team on its points line: won if (home - away + line) > 0,
              lost if < 0, push on exactly 0

The pretend money (the Studio OS Money tab): the top 8 picks split the weekly
amount in proportion to their stake_weight (the bot's own stake rule), with no
single pick taking more than 40%. The file keeps each pick's share of the week,
so the app can scale it to any weekly amount. Per pick the return multiplier is
its price if it won, 1 if push or void (stake back), 0 if lost.

Also kept for the "bot vs bookies" lines, per $1 staked across the week:
  expected_return_bot     what the bot thinks the picks are worth (price x its chance)
  expected_return_market  what the bookies' own chances say they are worth (about 1.00)

Usage:
    python3 scripts/score_picks.py --season 2026 --round 19
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone

TOP_N = 8
MAX_SHARE = 0.40


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ------------------------------------------------------------------ shares

def stake_shares(weights, cap=MAX_SHARE):
    """Shares of the weekly amount: proportional to weight, nobody over `cap`, summing to 1.

    With too few picks for the cap to be possible (fewer than 1/cap), the amount is split equally.
    """
    n = len(weights)
    if n == 0:
        return []
    if n * cap < 1.0 - 1e-9 or sum(weights) <= 0:
        return [1.0 / n] * n
    shares = [None] * n
    free = set(range(n))
    remaining = 1.0
    while True:
        total = sum(weights[i] for i in free)
        over = [i for i in free if remaining * weights[i] / total > cap + 1e-12]
        if not over:
            for i in free:
                shares[i] = remaining * weights[i] / total
            return shares
        for i in over:
            shares[i] = cap
            free.discard(i)
            remaining -= cap
        if not free:   # everyone capped (only possible when n * cap == 1)
            return shares


# ------------------------------------------------------------------ results

def real_scores(match_rows, aliases, season, rnd):
    out = {}
    for r in match_rows:
        try:
            if int(r["season"]) != season or int(r["round"]) != rnd:
                continue
            home, away = aliases.get(r["home_team"]), aliases.get(r["away_team"])
            if home and away:
                out[(home, away)] = (int(r["home_score"]), int(r["away_score"]))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def real_tries(master_rows, season, rnd):
    out = {}
    for r in master_rows:
        try:
            if int(r["season"]) != season or int(r["round"]) != rnd:
                continue
            out[(r["player_name"], r["team"])] = int(r["tries"] or 0)
        except (KeyError, TypeError, ValueError):
            continue
    return out


def pick_result(pick, scores, tries):
    """-> 'won' | 'lost' | 'push' | 'void' | None (the match isn't in the results)."""
    market = pick["market"]
    if market == "try_scorer":
        key = (pick.get("player_name"), pick.get("team"))
        if (pick["home_team"], pick["away_team"]) not in scores:
            return None
        if key not in tries:
            return "void"
        return "won" if tries[key] > 0 else "lost"
    score = scores.get((pick["home_team"], pick["away_team"]))
    if score is None:
        return None
    home, away = score
    if market == "winner":
        mine, theirs = (home, away) if pick.get("team") == pick["home_team"] else (away, home)
        return "push" if mine == theirs else ("won" if mine > theirs else "lost")
    if market == "margin":
        cover = (home - away) + pick["line"]
        return "push" if cover == 0 else ("won" if cover > 0 else "lost")
    return None


def multiplier(result, price):
    return {"won": price, "push": 1.0, "void": 1.0, "lost": 0.0}[result]


def score(season, rnd, data_dir="data", now=None):
    path = os.path.join(data_dir, "picks_history", f"{season}_round_{rnd}.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"No saved picks at {path}: that round's picks were never built, so there is nothing to score.")
    week = load_json(path)
    aliases = load_json(os.path.join(data_dir, "team_aliases.json"))["aliases"]
    scores = real_scores(load_csv(os.path.join(data_dir, "match_data_FINAL_fixed.csv")), aliases, season, rnd)
    if not scores:
        raise ValueError(f"No final results for season {season} round {rnd} yet, so the picks can't be scored.")
    tries = real_tries(load_csv(os.path.join(data_dir, "nrl_master.csv")), season, rnd)

    picks = week["picks"]
    for p in picks:
        r = pick_result(p, scores, tries)
        p["result"] = r
        p["return_multiplier"] = None if r is None else round(multiplier(r, p["price"]), 4)

    top = [p for p in picks[:TOP_N] if p["result"] is not None]
    shares = stake_shares([p["stake_weight"] for p in top])
    for p in picks:
        p["share"] = None
    for p, s in zip(top, shares):
        p["share"] = round(s, 4)
    returned = sum(s * p["return_multiplier"] for p, s in zip(top, shares))
    week["scoring"] = {
        "scored_at": (now or datetime.now(timezone.utc)).isoformat(),
        "results_in": True,
        "picks_counted": len(top),
        "won": sum(1 for p in top if p["result"] == "won"),
        "lost": sum(1 for p in top if p["result"] == "lost"),
        "push_or_void": sum(1 for p in top if p["result"] in ("push", "void")),
        "return_multiplier": round(returned, 4) if top else None,
        "expected_return_bot": round(sum(s * p["price"] * p["our_probability"] for p, s in zip(top, shares)), 4) if top else None,
        "expected_return_market": round(sum(s * p["price"] * p["market_probability"] for p, s in zip(top, shares)), 4) if top else None,
        "max_share": MAX_SHARE,
        "note": "Per $1 staked across the week. Multiply by the weekly amount for dollars.",
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(week, f, indent=2)
    return week


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--season", type=int, required=True)
    p.add_argument("--round", type=int, required=True, dest="rnd")
    p.add_argument("--data-dir", default="data")
    a = p.parse_args(argv)
    try:
        week = score(a.season, a.rnd, a.data_dir)
    except (FileNotFoundError, ValueError) as e:
        print(f"Not scored: {e}")
        return 1
    s = week["scoring"]
    print(f"Round {a.rnd} ({a.season}) picks: {s['won']} won, {s['lost']} lost, {s['push_or_void']} push/void "
          f"of the top {s['picks_counted']}. Per $1: returned {s['return_multiplier']}, "
          f"bot expected {s['expected_return_bot']}, market expected {s['expected_return_market']}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
