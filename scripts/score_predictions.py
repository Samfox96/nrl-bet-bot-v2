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

  STAGE 2 ADDITIONS (2026-07-04):

  - Brier score (winner market): mean squared error between our win
    probability and the binary outcome (1=home won, 0=away won).
    Lower is better; a coin-flip model scores 0.25; a perfect model
    scores 0.0. Also computed for the market's own implied probability
    so the two are directly comparable in the ledger.

  - Brier score (try-scorer market): same MSE calculation per
    player-edge entry -- our_probability vs binary scored-or-not.
    Market Brier uses market_probability from the same entry.
    Only computed for entries where both probabilities are present
    and the player's real result is in nrl_master.csv for that round.

  - Prediction-time EV log: for every positive-edge try-scorer entry,
    logs (our_probability, market_probability, edge, outcome). This is
    the foundation for CLV (closing line value) once a second,
    near-kickoff odds capture is wired into the pipeline (a future
    cron-job.org step). Without closing odds, this is not true CLV --
    it is the prediction-time comparison, labelled honestly as such.
    True CLV = (our_probability / closing_market_probability - 1),
    which requires closing_market_probability to exist in the archive.
    The structure is here; the data source is not yet built.

  - Cumulative ledger summary: after updating the ledger, prints a
    rolling summary across all scored rounds (total fixtures, running
    winner %, running margin MAE, running Brier scores) so the digest
    comment in STATUS.md can reflect actual season-to-date accuracy
    rather than single-round snapshots.

Refuses to score a round with no real results yet -- an unplayed round
isn't a failed prediction, it's just not judgeable yet, and silently
producing a zero/undefined entry would be worse than refusing.

Writes to data/accuracy_ledger.json -- a list of one entry per scored
round, keyed on (season, round). Re-running this for an already-scored
round REPLACES that round's entry (e.g. after a late results
correction) rather than duplicating it.

Usage:
    python3 scripts/score_predictions.py --season 2026 --round 17 \\
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


def _brier(prob, outcome):
    """Single squared error term. outcome is 1.0 or 0.0."""
    return (prob - outcome) ** 2


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

    # Stage 2: Brier score accumulators
    # Winner market: our model vs market vs actual outcome
    our_winner_brier_terms = []
    mkt_winner_brier_terms = []

    # Try-scorer market: per-edge, our model vs market vs actual outcome
    our_tryscorer_brier_terms = []
    mkt_tryscorer_brier_terms = []

    # Prediction-time EV log (foundation for future CLV once closing
    # odds are captured near kickoff -- NOT true CLV yet, see docstring)
    prediction_time_ev_log = []

    fixtures_scored = []

    for fixture in results:
        home = fixture.get("home_team")
        away = fixture.get("away_team")
        real = real_results_by_pair.get((home, away))
        if real is None:
            continue
        real_home_score, real_away_score = real
        real_home_won = real_home_score > real_away_score
        outcome_home = 1.0 if real_home_won else 0.0
        real_margin = real_home_score - real_away_score

        fixture_record = {
            "home_team": home, "away_team": away,
            "real_score": f"{real_home_score}-{real_away_score}",
        }

        h2h = fixture.get("h2h", {})
        if h2h.get("status") == "ok" and h2h.get("our_home_win_prob") is not None:
            our_prob = h2h["our_home_win_prob"]
            predicted_home_win = our_prob > 0.5
            correct = predicted_home_win == real_home_won
            winner_correct += int(correct)
            winner_total += 1
            fixture_record["winner_correct"] = correct

            # Brier: our model
            our_winner_brier_terms.append(_brier(our_prob, outcome_home))

            # Brier: market (only if available)
            mkt_prob = h2h.get("market_home_win_prob")
            if mkt_prob is not None:
                mkt_winner_brier_terms.append(_brier(mkt_prob, outcome_home))

            if h2h.get("our_predicted_margin") is not None:
                error = abs(h2h["our_predicted_margin"] - real_margin)
                margin_errors.append(error)
                fixture_record["margin_error"] = round(error, 1)

        # DUE WATCH hit rate
        for side in ("home", "away"):
            side_team = home if side == "home" else away
            for entry in fixture.get("due_watch", {}).get(side, []):
                player = entry.get("player_name")
                if player is None:
                    continue
                due_total += 1
                if tries_by_player_team.get((player, side_team), 0) > 0:
                    due_hits += 1

        # Try-scorer edge hit rate + Brier + prediction-time EV log
        for edge in fixture.get("try_scorer_edges", []):
            our_p = edge.get("our_probability")
            mkt_p = edge.get("market_probability")
            edge_val = edge.get("edge")
            player = edge.get("player_name")
            team = edge.get("team")

            if our_p is None or edge_val is None:
                continue

            # Only positive edges count for hit rate and EV log
            if edge_val > 0:
                edge_total += 1
                actual_scored = tries_by_player_team.get((player, team), 0) > 0
                if actual_scored:
                    edge_hits += 1

                # Prediction-time EV log entry (not CLV -- see docstring)
                ev_entry = {
                    "player_name": player,
                    "team": team,
                    "our_probability": round(our_p, 4),
                    "market_probability": round(mkt_p, 4) if mkt_p is not None else None,
                    "edge": round(edge_val, 4),
                    "outcome_scored": actual_scored,
                    # closing_market_probability: not yet captured -- future
                    # cron-job.org near-kickoff odds step will populate this,
                    # enabling true CLV = (our_p / closing_p - 1).
                    "closing_market_probability": None,
                }
                prediction_time_ev_log.append(ev_entry)

            # Brier for ALL edges (positive and negative) -- a complete
            # calibration picture requires the full probability range,
            # not just the edges we bet on. Requires player result to
            # actually be in nrl_master.csv for that round.
            if player and team and our_p is not None:
                actual_scored = tries_by_player_team.get((player, team), 0) > 0
                outcome_scored = 1.0 if actual_scored else 0.0
                our_tryscorer_brier_terms.append(_brier(our_p, outcome_scored))
                if mkt_p is not None:
                    mkt_tryscorer_brier_terms.append(_brier(mkt_p, outcome_scored))

        fixtures_scored.append(fixture_record)

    # Brier score summaries (None if no terms available)
    our_winner_brier = round(sum(our_winner_brier_terms) / len(our_winner_brier_terms), 4) if our_winner_brier_terms else None
    mkt_winner_brier = round(sum(mkt_winner_brier_terms) / len(mkt_winner_brier_terms), 4) if mkt_winner_brier_terms else None
    our_tryscorer_brier = round(sum(our_tryscorer_brier_terms) / len(our_tryscorer_brier_terms), 4) if our_tryscorer_brier_terms else None
    mkt_tryscorer_brier = round(sum(mkt_tryscorer_brier_terms) / len(mkt_tryscorer_brier_terms), 4) if mkt_tryscorer_brier_terms else None

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
        # Stage 2 additions
        "brier_winner_ours": our_winner_brier,
        "brier_winner_market": mkt_winner_brier,
        "brier_tryscorer_ours": our_tryscorer_brier,
        "brier_tryscorer_market": mkt_tryscorer_brier,
        "prediction_time_ev_log": prediction_time_ev_log,
        # CLV note: closing_market_probability is None in all ev_log entries
        # until a near-kickoff odds capture step is added to the pipeline.
        # Once populated, true CLV per entry = our_probability /
        # closing_market_probability - 1. Do not compute CLV from
        # market_probability (prediction-time) -- that's EV, not CLV.
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


def print_cumulative_summary(ledger_path="data/accuracy_ledger.json"):
    """
    Rolling season-to-date summary across all scored rounds in the
    ledger. Printed after each scoring run so STATUS.md comments can
    reflect actual accumulated accuracy rather than single-round noise.

    Honest about sample size: a single-round Brier score is nearly
    meaningless (5-8 fixtures, n=5-275 try-scorer edges). Accumulating
    across the season is when these numbers start to say anything real.
    """
    if not os.path.exists(ledger_path):
        print("  No ledger yet.")
        return

    with open(ledger_path) as f:
        ledger = json.load(f)

    if not ledger:
        print("  Ledger is empty.")
        return

    total_fixtures = sum(e.get("fixtures_scored_for_winner", 0) or 0 for e in ledger)
    total_correct = sum(
        round((e.get("correct_winner_pct") or 0) / 100 * (e.get("fixtures_scored_for_winner") or 0))
        for e in ledger
    )
    all_margin_mae = [e["margin_mae"] for e in ledger if e.get("margin_mae") is not None]
    all_due_flagged = sum(e.get("due_watch_flagged", 0) or 0 for e in ledger)
    all_due_hits = sum(
        round((e.get("due_watch_hit_rate_pct") or 0) / 100 * (e.get("due_watch_flagged") or 0))
        for e in ledger
    )
    all_edge_flagged = sum(e.get("try_scorer_edges_flagged", 0) or 0 for e in ledger)
    all_edge_hits = sum(
        round((e.get("try_scorer_edge_hit_rate_pct") or 0) / 100 * (e.get("try_scorer_edges_flagged") or 0))
        for e in ledger
    )

    # Brier: weighted mean across rounds (weight by n terms per round)
    # We don't store n terms per round, so we use fixture count as proxy
    # for winner Brier and note it's approximate for try-scorer Brier.
    our_brier_w = [(e["brier_winner_ours"], e.get("fixtures_scored_for_winner", 1) or 1)
                   for e in ledger if e.get("brier_winner_ours") is not None]
    mkt_brier_w = [(e["brier_winner_market"], e.get("fixtures_scored_for_winner", 1) or 1)
                   for e in ledger if e.get("brier_winner_market") is not None]
    our_brier_ts = [(e["brier_tryscorer_ours"], e.get("try_scorer_edges_flagged", 1) or 1)
                    for e in ledger if e.get("brier_tryscorer_ours") is not None]
    mkt_brier_ts = [(e["brier_tryscorer_market"], e.get("try_scorer_edges_flagged", 1) or 1)
                    for e in ledger if e.get("brier_tryscorer_market") is not None]

    def wmean(pairs):
        if not pairs: return None
        total_w = sum(w for _, w in pairs)
        return round(sum(v * w for v, w in pairs) / total_w, 4) if total_w else None

    rounds_scored = len(ledger)
    print(f"\n{'='*55}")
    print(f"SEASON-TO-DATE ACCURACY ({rounds_scored} round(s) scored)")
    print(f"{'='*55}")
    if total_fixtures:
        print(f"  Winner:        {total_correct}/{total_fixtures} correct ({100*total_correct/total_fixtures:.1f}%)")
    if all_margin_mae:
        print(f"  Margin MAE:    {sum(all_margin_mae)/len(all_margin_mae):.1f} pts (avg across rounds)")
    if all_due_flagged:
        print(f"  DUE hit rate:  {all_due_hits}/{all_due_flagged} ({100*all_due_hits/all_due_flagged:.1f}%)")
    if all_edge_flagged:
        print(f"  Edge hit rate: {all_edge_hits}/{all_edge_flagged} ({100*all_edge_hits/all_edge_flagged:.1f}%)")
    wb_ours = wmean(our_brier_w)
    wb_mkt = wmean(mkt_brier_w)
    if wb_ours is not None:
        print(f"  Brier (winner):    ours={wb_ours:.4f}  market={wb_mkt:.4f if wb_mkt is not None else 'n/a'}"
              f"  (lower=better; coin-flip=0.2500)")
    ts_ours = wmean(our_brier_ts)
    ts_mkt = wmean(mkt_brier_ts)
    if ts_ours is not None:
        print(f"  Brier (try-scorer): ours={ts_ours:.4f}  market={ts_mkt:.4f if ts_mkt is not None else 'n/a'}")
    print(f"  NOTE: CLV not yet computable -- closing_market_probability")
    print(f"        is None in all ev_log entries until a near-kickoff")
    print(f"        odds capture step is added to the pipeline.")
    print(f"{'='*55}\n")


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
    print(f"  Correct winner:    {entry['correct_winner_pct']}% ({entry['fixtures_scored_for_winner']} fixtures)")
    print(f"  Margin MAE:        {entry['margin_mae']}")
    print(f"  DUE WATCH hit rate: {entry['due_watch_hit_rate_pct']}% ({entry['due_watch_flagged']} flagged)")
    print(f"  Edge hit rate:     {entry['try_scorer_edge_hit_rate_pct']}% ({entry['try_scorer_edges_flagged']} flagged)")
    print(f"  Brier (winner):    ours={entry['brier_winner_ours']}  market={entry['brier_winner_market']}")
    print(f"  Brier (try-scorer): ours={entry['brier_tryscorer_ours']}  market={entry['brier_tryscorer_market']}")
    print(f"  EV log entries:    {len(entry['prediction_time_ev_log'])} positive edges logged")
    print(f"Ledger updated: {path}")

    print_cumulative_summary(args.ledger_path)
