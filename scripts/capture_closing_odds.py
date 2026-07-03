"""
capture_closing_odds.py

Stage 4 closing odds capture (added 2026-07-04).

Fired by team-list-polling.yml's near-kickoff cron-job.org trigger,
approximately 1 hour before each match starts. Re-fetches the real
bookmaker odds for ONE specific fixture and writes the closing
market_probability into the EV log entries for that fixture's
try-scorer edges in predictions_history/{season}_round_{N}.json.

WHY THIS EXISTS:
  score_predictions.py already logs a prediction_time_ev_log per round,
  with our_probability, market_probability (at prediction time), edge,
  and outcome_scored. The closing_market_probability field in every
  entry is None until this script populates it. Once populated:

    CLV = our_probability / closing_market_probability - 1

  Positive CLV means the market moved toward our position after we
  "placed" -- our model found something the market subsequently agreed
  with. This is the gold standard for evaluating a betting model,
  because it's independent of actual outcomes (a model can have
  positive CLV and lose a round; a model with negative CLV that
  wins is just variance). Requires closing odds to be captured
  BEFORE the match starts -- once it's played, the odds are gone.

WHAT IT DOES:
  1. Reads the current round's archived predictions snapshot
     (data/predictions_history/{season}_round_{N}.json).
  2. For the specific fixture identified by --home-team/--away-team,
     re-fetches the live odds from the-odds-api.com (Sportsbet only,
     h2h + player_try_scorer_anytime markets, 2 credits).
  3. For each EV log entry matching this fixture where
     closing_market_probability is still None, looks up the current
     Sportsbet price for that player and writes the closing probability.
  4. Updates the archive in place -- the snapshot is never replaced,
     only the closing_market_probability fields are back-filled.
  5. Writes a summary to stdout so team-list-polling.yml's log shows
     how many CLV entries were populated.

CREDIT COST:
  2 markets (h2h + tryscorer) x 1 region (au) = 2 credits per call.
  Called once per match, 8 matches per round = 16 credits per round.
  Combined with the predictions run (24 credits): 40 credits/round,
  ~160 credits/month at 4 rounds -- well within the 500/month budget.

WHAT IT DOES NOT DO:
  - Does not re-generate predictions. Probabilities are locked at the
    time generate_predictions.py ran; this only adds closing_market_prob.
  - Does not score predictions. score_predictions.py handles that after
    the round is complete and results are merged.
  - Does not fail loudly if the fixture isn't found or odds aren't
    available -- CLV is best-effort. A missed closing snap is logged
    and the entry stays None rather than crashing the kickoff workflow.

Usage (called by team-list-polling.yml):
    python3 scripts/capture_closing_odds.py \\
        --season 2026 \\
        --round 18 \\
        --home-team "Melbourne Storm" \\
        --away-team "Penrith Panthers" \\
        --data-dir data
"""

import argparse
import json
import os
import sys

# Sibling scripts/ directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from odds_fetcher import (
    get_upcoming_events,
    resolve_event_for_fixture,
    fetch_h2h_and_tryscorer_odds,
    extract_try_scorer_odds,
)
from odds_probability import yes_no_market_probability

PREFERRED_BOOKMAKER = "sportsbet"


def _sportsbet_tryscorer_probs(odds_response):
    """
    Extract {player_name: closing_probability} from the raw odds response,
    using Sportsbet's prices only. If Sportsbet doesn't have the market,
    returns an empty dict rather than falling back to another bookmaker --
    CLV must be computed against the book you actually bet at, not a
    different one.
    """
    all_odds = extract_try_scorer_odds(odds_response)
    sportsbet_prices = all_odds.get(PREFERRED_BOOKMAKER, {})
    return {
        player: yes_no_market_probability(price)
        for player, price in sportsbet_prices.items()
        if price and price > 1.0
    }


def capture_closing_odds(season, round_num, home_team, away_team,
                          data_dir="data", api_key=None):
    """
    Main entry point. Returns a summary dict with how many EV log
    entries were updated (for logging in the workflow step).
    """
    archive_path = os.path.join(
        data_dir, "predictions_history", f"{season}_round_{round_num}.json"
    )
    if not os.path.exists(archive_path):
        print(f"No archive found at {archive_path} -- skipping closing odds capture.")
        return {"status": "no_archive", "updated": 0}

    with open(archive_path) as f:
        archive = json.load(f)

    team_aliases = json.load(
        open(os.path.join(data_dir, "team_aliases.json"))
    )["aliases"]

    # Resolve the fixture label used in the EV log
    # (matches how score_predictions.py builds it: "Home v Away" with
    # full canonical names as stored in the predictions archive)
    fixture_label = f"{home_team} v {away_team}"

    # Find EV log entries for this specific fixture that still need closing odds
    ev_log = archive.get("ev_log", [])
    if not ev_log:
        # Try nested structure (score_predictions writes it; archived predictions
        # don't have it directly -- it gets added by score_predictions.py)
        # In that case, nothing to update yet.
        print(f"No ev_log in archive for round {round_num} yet -- "
              f"score_predictions.py populates this after the round completes. "
              f"Closing odds will be captured on the next near-kickoff trigger "
              f"if the ev_log is populated by then.")
        return {"status": "no_ev_log", "updated": 0}

    entries_for_fixture = [
        e for e in ev_log
        if e.get("fixture") == fixture_label
        and e.get("closing_market_probability") is None
    ]

    if not entries_for_fixture:
        print(f"No open CLV entries for {fixture_label} -- already captured or fixture not in log.")
        return {"status": "already_done", "updated": 0}

    # Fetch closing odds from the-odds-api
    if not api_key:
        api_key = os.environ.get("ODDS_API_KEY")
    if not api_key:
        print("ODDS_API_KEY not set -- cannot fetch closing odds.")
        return {"status": "no_api_key", "updated": 0}

    try:
        events = get_upcoming_events(api_key)
        event = resolve_event_for_fixture(events, home_team, away_team, team_aliases)
        if event is None:
            print(f"No upcoming odds-api event found for {fixture_label} -- "
                  f"match may have already started or API doesn't have it. "
                  f"Closing odds not captured (best-effort, non-fatal).")
            return {"status": "event_not_found", "updated": 0}

        odds_response = fetch_h2h_and_tryscorer_odds(api_key, event["id"])
        closing_probs = _sportsbet_tryscorer_probs(odds_response)
    except Exception as e:
        print(f"Closing odds fetch failed for {fixture_label}: {e} "
              f"(best-effort, non-fatal -- CLV entries stay None).")
        return {"status": "fetch_failed", "updated": 0, "error": str(e)}

    # Back-fill closing_market_probability into the matching EV log entries
    updated = 0
    for entry in entries_for_fixture:
        player = entry.get("player_name")
        closing_p = closing_probs.get(player)
        if closing_p is not None:
            entry["closing_market_probability"] = round(closing_p, 4)
            # CLV = our_probability / closing_market_probability - 1
            # Written here so score_predictions.py can use it directly
            our_p = entry.get("our_probability")
            if our_p and closing_p > 0:
                entry["clv"] = round(our_p / closing_p - 1, 4)
            updated += 1

    if updated > 0:
        # Write back -- only the ev_log entries changed, nothing else
        with open(archive_path, "w") as f:
            json.dump(archive, f, indent=2)
        print(f"Closing odds captured for {fixture_label}: "
              f"{updated}/{len(entries_for_fixture)} EV log entries updated "
              f"with Sportsbet closing probabilities.")
    else:
        print(f"Closing odds fetched for {fixture_label} but no player names matched "
              f"EV log entries ({len(closing_probs)} Sportsbet prices, "
              f"{len(entries_for_fixture)} open entries). "
              f"Possible name-format mismatch -- check unmatched_in_model in predictions.")

    return {"status": "ok", "updated": updated, "fixture": fixture_label}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Capture closing Sportsbet odds for one fixture into the round archive"
    )
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--round", type=int, required=True, dest="round_num")
    parser.add_argument("--home-team", required=True)
    parser.add_argument("--away-team", required=True)
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args()

    result = capture_closing_odds(
        season=args.season,
        round_num=args.round_num,
        home_team=args.home_team,
        away_team=args.away_team,
        data_dir=args.data_dir,
    )
    sys.exit(0 if result["status"] in ("ok", "already_done", "no_archive",
                                        "no_ev_log", "event_not_found") else 1)
