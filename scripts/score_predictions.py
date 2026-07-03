"""
score_predictions.py

Real accuracy-scoring script, added 2026-07-03 -- closes a genuine gap
that's been on this project's own roadmap since Phase 3 ("an accuracy
ledger, logging predicted vs actual results week over week") but was
never actually built. Confirmed via a real repo audit: predictions_
current.json was overwritten every round with no history, so there was
never anywhere for a script like this to read a past round's real
predictions from.

Works together with generate_predictions.py's archive_predictions()
(added in the same pass), which writes an immutable per-round snapshot
to data/predictions_history/{season}_round_{N}.json. This script reads
one of those snapshots plus that round's real, merged results (match_
data_FINAL_fixed.csv for scores, nrl_master.csv for who actually
scored tries) and computes:

  - Correct winner %: did our predicted favourite (our_home_win_prob
    > 0.5) match who actually won?
  - Margin MAE: how far off was our predicted margin from the real
    final margin, on average?
  - DUE WATCH hit rate: of players flagged DUE that round, what
    fraction actually scored a real try?
  - Try-scorer edge hit rate: of players we rated as a positive edge
    (more likely than the market's price implies), what fraction
    actually scored a real try?

Refuses to score a round with no real results yet -- an unplayed round
isn't a failed prediction, it's just not judgeable yet, and silently
producing a zero/undefined entry would be worse than refusing.

Writes to data/accuracy_ledger.json -- a list of one entry per scored
round, keyed on (season, round). Re-running this for an already-scored
round REPLACES that round's entry (e.g. after a late results
correction) rather than duplicating it.

Usage:
    python3 scripts/score_predictions.py --season 2026 --round 17 \
        --data-dir data
"""

import argparse
import csv
import json
import os
from datetime import datetime, timezone


def load_json(path):
    with open(path) as f:
        return json.load(f)


def load_csv_rows(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def score_round(season, round_num, data_dir="data"):
    archive_path = os.path.join(data_dir, "predictions_history", f"{season}_round_{round_num}.json")
    if not os.path.exists(archive_path):
        raise FileNotFoundError(
            f"No archived predictions found at {archive_path}. This script can only "
            f"score a round that was actually predicted and archived by "
            f"generate_predictions.py's archive_predictions() -- nothing to compare "
            f"against. Note: archiving was only added 2026-07-03, so rounds predicted "
            f"before that date were never archived and can't be scored retroactively."
        )
    archive = load_json(archive_path)
    results = archive["results"]

    team_aliases = load_json(os.path.join(data_dir, "team_aliases.json"))["aliases"]
    match_rows = load_csv_rows(os.path.join(data_dir, "match_data_FINAL_fixed.csv"))
    master_rows = load_csv_rows(os.path.join(data_dir, "nrl_master.csv"))

    # Real final results for this exact season+round, team names resolved
    # to canonical form (match_data_FINAL_fixed.csv uses short names;
    # predictions use canonical, same as everywhere else in this project).
    real_results_by_pair = {}
    for r in match_rows:
        if int(r["season"]) != season or int(r["round"]) != round_num:
            continue
        home_canonical = team_aliases.get(r["home_team"])
        away_canonical = team_aliases.get(r["away_team"])
        if not home_canonical or not away_canonical:
            continue
        try:
            home_score = int(r["home_score"])
            away_score = int(r["away_score"])
        except (ValueError, TypeError):
            continue
        real_results_by_pair[(home_canonical, away_canonical)] = (home_score, away_score)

    if not real_results_by_pair:
        raise ValueError(
            f"No real, final match results found for season {season} round {round_num} "
            f"in match_data_FINAL_fixed.csv -- this round hasn't been played yet, or its "
            f"results haven't been merged yet, so there's nothing real to score "
            f"predictions against. Try again once the round has finished and Job A has "
            f"merged results (check STATUS.md)."
        )

    # Real tries scored this round, per (player_name, team) -- nrl_master.csv's
    # team column is already canonical (normalized at merge time), matching
    # predictions' team names directly, no alias resolution needed here.
    tries_by_player_team = {}
    for r in master_rows:
        if int(r["season"]) != season or int(r["round"]) != round_num:
            continue
        try:
            tries = int(r["tries"])
        except (ValueError, TypeError):
            tries = 0
        tries_by_player_team[(r["player_name"], r["team"])] = tries

    winner_correct = 0
    winner_total = 0
    margin_errors = []
    due_hits = 0
    due_total = 0
    edge_hits = 0
    edge_total = 0
    fixtures_scored = []

    for fixture in results:
        home = fixture.get("home_team")
        away = fixture.get("away_team")
        real = real_results_by_pair.get((home, away))
        if real is None:
            # This fixture's prediction was itself skipped, or (less
            # likely) a genuine name mismatch -- either way, nothing
            # real to score it against. Skip rather than guess.
            continue
        real_home_score, real_away_score = real
        real_home_won = real_home_score > real_away_score
        real_margin = real_home_score - real_away_score

        fixture_record = {
            "home_team": home, "away_team": away,
            "real_score": f"{real_home_score}-{real_away_score}",
        }

        h2h = fixture.get("h2h", {})
        if h2h.get("status") == "ok" and h2h.get("our_home_win_prob") is not None:
            predicted_home_win = h2h["our_home_win_prob"] > 0.5
            correct = predicted_home_win == real_home_won
            winner_correct += int(correct)
            winner_total += 1
            fixture_record["winner_correct"] = correct

            if h2h.get("our_predicted_margin") is not None:
                error = abs(h2h["our_predicted_margin"] - real_margin)
                margin_errors.append(error)
                fixture_record["margin_error"] = round(error, 1)

        # DUE WATCH hit rate: did each flagged player actually score a real try?
        for side in ("home", "away"):
            side_team = home if side == "home" else away
            for entry in fixture.get("due_watch", {}).get(side, []):
                player = entry.get("player_name")
                if player is None:
                    continue
                due_total += 1
                if tries_by_player_team.get((player, side_team), 0) > 0:
                    due_hits += 1

        # Try-scorer edge hit rate: only positive edges count (we rated
        # them more likely than the market) -- a negative edge "hitting"
        # isn't a model success, it's the model being right to be
        # cautious, which this metric isn't designed to capture.
        for edge in fixture.get("try_scorer_edges", []):
            if edge.get("edge") is None or edge["edge"] <= 0:
                continue
            player = edge.get("player_name")
            team = edge.get("team")
            edge_total += 1
            if tries_by_player_team.get((player, team), 0) > 0:
                edge_hits += 1

        fixtures_scored.append(fixture_record)

    return {
        "season": season,
        "round": round_num,
        "scored_at": datetime.now(timezone.utc).isoformat(),
        "fixtures_with_real_results": len(real_results_by_pair),
        "fixtures_scored_for_winner": winner_total,
        "correct_winner_pct": round(100 * winner_correct / winner_total, 1) if winner_total else None,
        "margin_mae": round(sum(margin_errors) / len(margin_errors), 1) if margin_errors else None,
        "due_watch_flagged": due_total,
        "due_watch_hit_rate_pct": round(100 * due_hits / due_total, 1) if due_total else None,
        "try_scorer_edges_flagged": edge_total,
        "try_scorer_edge_hit_rate_pct": round(100 * edge_hits / edge_total, 1) if edge_total else None,
        "fixture_detail": fixtures_scored,
    }


def update_ledger(entry, ledger_path="data/accuracy_ledger.json"):
    """
    Appends this round's scored entry to the real, persistent ledger.
    Replaces any existing entry for the same (season, round) rather
    than duplicating it -- re-running after a late results correction
    updates the record instead of accumulating stale duplicates.
    """
    if os.path.exists(ledger_path):
        with open(ledger_path) as f:
            ledger = json.load(f)
    else:
        ledger = []

    ledger = [
        e for e in ledger
        if not (e["season"] == entry["season"] and e["round"] == entry["round"])
    ]
    ledger.append(entry)
    ledger.sort(key=lambda e: (e["season"], e["round"]))

    dirname = os.path.dirname(ledger_path)
    if dirname:
        os.makedirs(dirname, exist_ok=True)
    with open(ledger_path, "w") as f:
        json.dump(ledger, f, indent=2)
    return ledger_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Score a round's archived predictions against real results")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--round", type=int, required=True, dest="round_num")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--ledger-path", default="data/accuracy_ledger.json")
    args = parser.parse_args()

    entry = score_round(args.season, args.round_num, args.data_dir)
    path = update_ledger(entry, args.ledger_path)

    print(f"Round {args.round_num} ({args.season}) scored:")
    print(f"  Correct winner: {entry['correct_winner_pct']}% ({entry['fixtures_scored_for_winner']} fixtures)")
    print(f"  Margin MAE: {entry['margin_mae']}")
    print(f"  DUE WATCH hit rate: {entry['due_watch_hit_rate_pct']}% ({entry['due_watch_flagged']} flagged)")
    print(f"  Try-scorer edge hit rate: {entry['try_scorer_edge_hit_rate_pct']}% ({entry['try_scorer_edges_flagged']} flagged)")
    print(f"Ledger updated: {path}")
