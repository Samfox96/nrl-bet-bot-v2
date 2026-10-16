"""
backtest_season.py
==================
How would the bot have done over a whole season, using only what it could have
known at the time? No odds and no money: prices before round 18 were never saved
and old prices would be a paid service (hard rule 1).

For every round of the season:
  - Teams: Elo ratings built only from matches BEFORE that round give a win
    chance and a predicted margin, exactly as generate_predictions.py does.
  - Try scorers: the xTry model run only on games BEFORE that round gives each
    player a chance of scoring. The players are the ones who actually took the
    field (we can't know the team lists of the past), each at his most frequent
    position so far, so this is "given who played", a little kinder than a
    real Thursday.
  - Both are compared with what really happened.

Nothing from the future is used: tests rebuild a round from data with every
later round removed and check the answer is identical.

Output: data/backtest_<season>.json. Season-long numbers (winners right, margin
error, Brier scores, the bot's best and worst rounds, the biggest upsets, the
Grand Final) plus the raw material for the "against the bot" trend cards: the
players the bot rated highest who didn't score and those it ignored who did.
Those cards follow the sample rule (build_weekly_picks.py): a player needs at
least 5 games to go on, so thin-sample players never appear.

Usage:
    python3 scripts/backtest_season.py --season 2026
"""

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from build_weekly_picks import MIN_GAMES, load_games, sample_games  # noqa: E402
from generate_predictions import build_raw_scores, get_squad, load_real_baselines  # noqa: E402
from nrl_elo import HOME_ADVANTAGE, build_elo_ratings, expected_margin, expected_win_probability  # noqa: E402
from xtry_model import (  # noqa: E402
    build_player_game_log, build_team_games_played, build_team_ruck_speeds,
    compute_real_avg_tries_per_team_per_game, normalise_match_xtry, safe_int,
)

UPSET_BELOW = 0.25        # the winner had under this chance
TOP_PER_MATCH = 3         # "the bot's top three scorers in each match"
LIST_LEN = 6
MODEL_CEILING = 0.65     # xtry_model clips every try-scoring chance at 65%


def brier(p, outcome):
    return (p - outcome) ** 2


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else None


def r4(x):
    return None if x is None else round(x, 4)


# ------------------------------------------------------------------ one round

def predict_round(season, rnd, baselines, master_rows, match_rows):
    """Everything the bot could have said about round `rnd`, from data before it only.

    -> dict(matches=[...], scorers=[...]) with the real outcomes attached.
    """
    aliases = baselines["team_aliases"]
    ratings = build_elo_ratings(match_rows, aliases, up_to_season=season, up_to_round=rnd)

    matches = []
    for m in match_rows:
        if int(m["season"]) != season or safe_int(m["round"]) != rnd:
            continue
        home, away = aliases.get(m["home_team"]), aliases.get(m["away_team"])
        if not home or not away:
            continue
        rh, ra = ratings.get(home, 1500.0), ratings.get(away, 1500.0)
        p_home = expected_win_probability(rh + HOME_ADVANTAGE, ra)
        hs, as_ = safe_int(m["home_score"]), safe_int(m["away_score"])
        matches.append({
            "home_team": home, "away_team": away, "home_score": hs, "away_score": as_,
            "our_home_win_prob": round(p_home, 4),
            "our_predicted_margin": round(expected_margin((rh + HOME_ADVANTAGE) - ra), 1),
        })

    # --- try scorers: xTry on games before this round, for the players who played ---
    by_player = build_player_game_log(master_rows, season, rnd)
    team_games = build_team_games_played(master_rows, season, rnd)
    att_speed, speed_allowed = build_team_ruck_speeds(master_rows, season, rnd)
    avg_tries = compute_real_avg_tries_per_team_per_game(master_rows, season, rnd)
    team_tries = defaultdict(int)
    for r in master_rows:
        if r["season"] == str(season) and safe_int(r["round"]) < rnd:
            team_tries[r["team"]] += safe_int(r["tries"])

    scorers = []
    if avg_tries:
        full_to_short = {}
        for short in {r["team"] for r in master_rows}:
            if aliases.get(short):
                full_to_short[aliases[short]] = short
        played = defaultdict(dict)       # team_short -> {player: tries} for this round
        for r in master_rows:
            if r["season"] == str(season) and safe_int(r["round"]) == rnd:
                played[r["team"]][r["player_name"]] = safe_int(r["tries"])
        for mt in matches:
            raws = {}
            for side, team_full, opp_full, is_home in (("home", mt["home_team"], mt["away_team"], True),
                                                       ("away", mt["away_team"], mt["home_team"], False)):
                short = full_to_short.get(team_full)
                if not short:
                    continue
                roster = get_squad(master_rows, short, season, rnd)          # most frequent position so far
                squad = {p: pos for p, pos in roster.items() if p in played.get(short, {})}
                raws[side] = build_raw_scores(baselines, by_player, team_games, team_tries, att_speed,
                                              speed_allowed, squad, short, opp_full, is_home)
            if "home" in raws and "away" in raws:
                probs = normalise_match_xtry(raws["home"], raws["away"], avg_tries)
                for name, d in probs.items():
                    short = full_to_short.get(d["team"]) or d["team"]
                    tries = played.get(d["team"], {}).get(name)
                    if tries is None:
                        continue
                    scorers.append({
                        "player_name": name, "team": d["team"], "round": rnd,
                        "fixture": f"{mt['home_team']} v {mt['away_team']}",
                        "our_probability": d["display_probability"],
                        "scored": tries > 0, "tries": tries,
                    })
    return {"matches": matches, "scorers": scorers}


# ------------------------------------------------------------------ summaries

def summarise_matches(matches):
    decided = [m for m in matches if m["home_score"] != m["away_score"]]
    correct = [(m["our_home_win_prob"] > 0.5) == (m["home_score"] > m["away_score"]) for m in decided]
    return {
        "matches": len(matches),
        "winners_correct": sum(correct),
        "winners_scored": len(decided),
        "correct_pct": round(100 * sum(correct) / len(correct), 1) if correct else None,
        "margin_mae": r4(mean(abs(m["our_predicted_margin"] - (m["home_score"] - m["away_score"])) for m in matches)),
        "brier": r4(mean(brier(m["our_home_win_prob"], 1.0 if m["home_score"] > m["away_score"] else 0.0) for m in decided)),
    }


def summarise_scorers(scorers):
    if not scorers:
        return {"players": 0, "brier": None, "base_rate": None, "brier_if_everyone_at_base_rate": None, "top3_hit_pct": None}
    base = mean(1.0 if s["scored"] else 0.0 for s in scorers)
    by_match = defaultdict(list)
    for s in scorers:
        by_match[s["fixture"]].append(s)
    top_hits, top_total = 0, 0
    for group in by_match.values():
        for s in sorted(group, key=lambda s: s["our_probability"], reverse=True)[:TOP_PER_MATCH]:
            top_total += 1
            top_hits += 1 if s["scored"] else 0
    return {
        "players": len(scorers),
        "brier": r4(mean(brier(s["our_probability"], 1.0 if s["scored"] else 0.0) for s in scorers)),
        "base_rate": r4(base),
        "brier_if_everyone_at_base_rate": r4(mean(brier(base, 1.0 if s["scored"] else 0.0) for s in scorers)),
        "top3_hit_pct": round(100 * top_hits / top_total, 1) if top_total else None,
    }


def calibration(scorers):
    bands = [(0.0, 0.10), (0.10, 0.20), (0.20, 0.30), (0.30, 0.45), (0.45, 1.01)]
    out = []
    for lo, hi in bands:
        grp = [s for s in scorers if lo <= s["our_probability"] < hi]
        if grp:
            out.append({"from": lo, "to": min(hi, 1.0), "players": len(grp),
                        "bot_says_pct": round(100 * mean(s["our_probability"] for s in grp), 1),
                        "really_scored_pct": round(100 * mean(1.0 if s["scored"] else 0.0 for s in grp), 1)})
    return out


def upsets(matches_with_round):
    out = []
    for rnd, m in matches_with_round:
        if m["home_score"] == m["away_score"]:
            continue
        home_won = m["home_score"] > m["away_score"]
        winner_p = m["our_home_win_prob"] if home_won else 1.0 - m["our_home_win_prob"]
        if winner_p < UPSET_BELOW:
            out.append({"round": rnd, "winner": m["home_team"] if home_won else m["away_team"],
                        "loser": m["away_team"] if home_won else m["home_team"],
                        "score": f"{m['home_score']}-{m['away_score']}", "home_team": m["home_team"],
                        "bot_gave_winner_pct": round(100 * winner_p, 1)})
    return sorted(out, key=lambda u: u["bot_gave_winner_pct"])[:LIST_LEN]


def against_the_bot(scorers, games, season):
    """Misses (rated high, didn't score) and surprises (rated low, scored). Players need enough games."""
    def enough(s):
        return sample_games(games, s["player_name"], season, s["round"]) >= MIN_GAMES
    ok = [s for s in scorers if enough(s)]
    misses = sorted((s for s in ok if not s["scored"]), key=lambda s: s["our_probability"], reverse=True)[:LIST_LEN]
    surprises = sorted((s for s in ok if s["scored"]), key=lambda s: (s["our_probability"], -s["tries"]))[:LIST_LEN]
    pick = lambda s: {"player_name": s["player_name"], "team": s["team"], "round": s["round"], "fixture": s["fixture"],
                      "bot_said_pct": round(100 * s["our_probability"], 1), "tries": s["tries"],
                      "at_model_ceiling": s["our_probability"] >= MODEL_CEILING}
    return {"biggest_misses": [pick(s) for s in misses], "biggest_surprises": [pick(s) for s in surprises],
            "rule": f"A player needs at least {MIN_GAMES} games to go on (the sample rule)."}


# ------------------------------------------------------------------ build

def build(season, data_dir="data", now=None, first_round=1, last_round=None):
    baselines = load_real_baselines(data_dir)
    master_rows, match_rows = baselines["master_rows"], baselines["match_rows"]
    games = load_games(os.path.join(data_dir, "nrl_master.csv"))
    rounds_present = sorted({safe_int(m["round"]) for m in match_rows if int(m["season"]) == season})
    if last_round is None and rounds_present:
        last_round = rounds_present[-1]

    per_round, all_scorers, all_matches = [], [], []
    for rnd in rounds_present:
        if rnd < first_round or rnd > last_round:
            continue
        pr = predict_round(season, rnd, baselines, master_rows, match_rows)
        ms, ss = summarise_matches(pr["matches"]), summarise_scorers(pr["scorers"])
        per_round.append({"round": rnd, "teams": ms, "try_scorers": ss})
        all_matches += [(rnd, m) for m in pr["matches"]]
        all_scorers += pr["scorers"]

    only_matches = [m for _, m in all_matches]
    ranked = [r for r in per_round if r["teams"]["winners_scored"] >= 4]
    best = sorted(ranked, key=lambda r: (-r["teams"]["correct_pct"], r["teams"]["margin_mae"] or 0))[:3]
    worst = sorted(ranked, key=lambda r: (r["teams"]["correct_pct"], -(r["teams"]["margin_mae"] or 0)))[:3]
    final_round = max((r for r, _ in all_matches), default=None)
    final = [m for r, m in all_matches if r == final_round]
    gf = None
    if len(final) == 1:
        m = final[0]
        gf = {"round": final_round, **{k: m[k] for k in ("home_team", "away_team", "home_score", "away_score", "our_home_win_prob")},
              "bot_picked": m["home_team"] if m["our_home_win_prob"] > 0.5 else m["away_team"],
              "bot_was_right": (m["our_home_win_prob"] > 0.5) == (m["home_score"] > m["away_score"])}

    return {
        "season": season,
        "generated_at": (now or datetime.now(timezone.utc)).isoformat(),
        "method": ("For each round, ratings and try-scorer chances are rebuilt from data before that round only. "
                   "Try scorers are the players who took the field (past team lists are unknown), each at his most "
                   "frequent position so far. No odds and no money."),
        "rounds_covered": len(per_round),
        "teams": summarise_matches(only_matches),
        "try_scorers": summarise_scorers(all_scorers),
        "try_scorer_calibration": calibration(all_scorers),
        "best_rounds": [{"round": r["round"], **r["teams"]} for r in best],
        "worst_rounds": [{"round": r["round"], **r["teams"]} for r in worst],
        "biggest_upsets": upsets(all_matches),
        "grand_final": gf,
        "against_the_bot": against_the_bot(all_scorers, games, season),
        "per_round": per_round,
    }


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--season", type=int, required=True)
    p.add_argument("--data-dir", default="data")
    p.add_argument("--out", default=None)
    a = p.parse_args(argv)
    result = build(a.season, a.data_dir)
    out = a.out or os.path.join(a.data_dir, f"backtest_{a.season}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    t, s = result["teams"], result["try_scorers"]
    print(f"{a.season}: {result['rounds_covered']} rounds. Winners right {t['winners_correct']}/{t['winners_scored']} "
          f"({t['correct_pct']}%), margin error {t['margin_mae']} points, Brier {t['brier']} (a coin flip is 0.25).")
    print(f"Try scorers: Brier {s['brier']} vs {s['brier_if_everyone_at_base_rate']} if everyone had the average; "
          f"top {TOP_PER_MATCH} per match scored {s['top3_hit_pct']}% (average player {round(100 * (s['base_rate'] or 0), 1)}%).")
    print(f"Saved {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
