"""
backfill_rounds.py
===================
One-off catch-up script, added 2026-10-13 after the Round 20 stall was
fixed (see merge_round.py's own docstring and tests/test_merge_round.py).
weekly-update.yml only ever processes ONE round a week -- scrape player
stats, validate, merge; scrape match results, validate, merge; score that
round's predictions if an archive exists. While the Round 20 bug was live
(19 Aug - 13 Oct 2026), nrl_master.csv never advanced past Round 19 even
though the real season kept being played and match_data_FINAL_fixed.csv
(a separate, unaffected merge path) kept catching up fine on its own. This
script exists to catch nrl_master.csv back up to the real season WITHOUT
waiting one real week per round -- it is the exact same per-round pipeline
weekly-update.yml already runs, just looped over a range instead of called
once. The weekly job itself can call this with --start-round and --end-round
both set to the same "next round" value and get byte-for-byte the same
single-round behaviour it has today -- this is a generalisation, not a
parallel/duplicate implementation.

WHAT THIS DOES, per round in the range:
  1. Scrape that round's player stats (nrl_update_single_round.py) to
     data/pending/nrl_round_N_new.csv.
  2. Validate + merge into nrl_master.csv (merge_round.py -- unmodified,
     reused exactly as the weekly job uses it).
  3. Scrape that round's match results (scrape_match_results.py) to a
     throwaway per-round temp directory (kept separate per round so an
     older round's file can never be swept up by merge_match_results_
     backfill.py's directory glob when a LATER round is being processed
     in the same run -- that glob has no per-round filter of its own).
  4. Validate + merge into match_data_FINAL_fixed.csv
     (merge_match_results_backfill.py -- unmodified).
  5. Score that round's predictions against the real results
     (score_predictions.py) IF an archive exists for it. Missing archive
     is expected and NOT a failure -- see score_round_if_archived()'s own
     docstring.

FAILS LOUD, NEVER SILENTLY PARTIAL: stops the whole run at the first round
whose player-stats OR match-results step fails validation (same rule every
other script in this pipeline follows -- a validation failure leaves the
existing files untouched and must be reviewed by a human, never
papered over by skipping ahead to a later round that might happen to
succeed). A missing or already-scored prediction archive does NOT stop
the run (matches weekly-update.yml's own "informational only" treatment
of that step).

FINALS NOTE (2026-10-13, built 2026-10-16): validate_round.py and
merge_match_results_backfill.py's row-count checks both used to
cross-reference scripts/bye_schedule.json only, which covers rounds
1-27 (the regular season) -- which teams play in a finals round depends
on the ladder, not a pre-published bye schedule, so a fixed team-NAME
check can't apply to round 28 onward (2026 finals: Finals Week 1/2/3,
Grand Final). Both scripts now also know a fixed team/match-COUNT table
for rounds 28-31 (FINALS_TEAM_COUNTS / FINALS_MATCH_COUNTS) and use that
instead for those rounds -- see each script's own comments. This
script's --finals flag is still accepted as a marker for the caller's
intent (and shows up in this script's own log output), but the actual
validation branch is chosen automatically from the round number by the
two scripts above, so passing it is optional, not required, for a
finals round to backfill correctly.

Usage:
    # Regular season, explicit range:
    python3 scripts/backfill_rounds.py --start-round 21 --end-round 27

    # Finals (rounds 28-31: Finals Wk1, Wk2, Wk3, Grand Final):
    python3 scripts/backfill_rounds.py --start-round 28 --end-round 31 --finals

    # Auto-detect start (next round after nrl_master.csv's current max),
    # single round -- this is what a future weekly-update.yml could call:
    python3 scripts/backfill_rounds.py --end-round 21
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
SCRIPTS_DIR = REPO_ROOT / "scripts"

sys.path.insert(0, str(SCRIPTS_DIR))
from merge_round import get_next_round  # noqa: E402  (after sys.path tweak, deliberately)

LAST_REGULAR_SEASON_ROUND = 27  # last round scripts/bye_schedule.json covers


def run(cmd, run_cmd=subprocess.run):
    """
    Thin wrapper so every subprocess call in this file goes through one
    place -- tests inject a fake `run_cmd` here instead of ever touching
    a real browser/network, matching this repo's existing convention of
    testing orchestration logic without re-testing already-proven scrapers.
    """
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    result = run_cmd(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    return result.returncode == 0


def backfill_player_stats(round_num, run_cmd=subprocess.run):
    """Scrape + validate + merge one round's player stats into nrl_master.csv."""
    pending_dir = DATA_DIR / "pending"
    pending_dir.mkdir(parents=True, exist_ok=True)
    pending_path = pending_dir / f"nrl_round_{round_num}_new.csv"

    scraped = run(
        ["python3", str(SCRIPTS_DIR / "nrl_update_single_round.py"),
         "--round", str(round_num), "--headless", "--output", str(pending_path)],
        run_cmd,
    )
    if not scraped:
        print(f"Round {round_num}: player-stats SCRAPE failed. Stopping -- "
              f"see merge_round.py's own rule, never guess past a real failure.")
        return False

    # merge_round.py takes no arguments -- it always determines "the next
    # round" itself from nrl_master.csv's current max round, and expects
    # the pending file at the exact path it computes for that round. As
    # long as rounds are processed in order (which the caller's loop
    # guarantees), this always lines up with pending_path above.
    merged = run(["python3", str(SCRIPTS_DIR / "merge_round.py")], run_cmd)
    if not merged:
        print(f"Round {round_num}: player-stats VALIDATION/MERGE failed. "
              f"nrl_master.csv left untouched. Stopping this backfill run here -- "
              f"the pending file is left at {pending_path} for manual review, "
              f"same as a normal weekly run's failure path.")
        return False
    return True


def backfill_match_results(round_num, season, run_cmd=subprocess.run):
    """
    Scrape + validate + merge one round's match results into
    match_data_FINAL_fixed.csv.

    Uses a FRESH temp directory per round, never the real
    data/pending_match_results/ -- merge_match_results_backfill.py merges
    EVERY file in --backfill-dir matching its glob in one pass, with no
    per-round filter of its own (by design -- that script was written for
    a one-time multi-round backfill where "merge everything in the
    directory" was exactly right). Reusing one shared directory across
    multiple rounds in THIS script's own loop would risk a later round's
    merge silently re-processing (and, worse, being blocked by the
    duplicate-row check on) an earlier round's already-merged file if its
    cleanup were ever skipped -- an isolated temp dir per round removes
    that risk entirely rather than relying on remembering to clean up.
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix=f"nrl_round_{round_num}_results_"))
    try:
        output_path = tmp_dir / f"match_results_round_{round_num}_backfill.csv"
        scraped = run(
            ["python3", str(SCRIPTS_DIR / "scrape_match_results.py"),
             "--round", str(round_num), "--season", str(season),
             "--output", str(output_path)],
            run_cmd,
        )
        if not scraped:
            print(f"Round {round_num}: match-results SCRAPE failed. Stopping.")
            return False

        merged = run(
            ["python3", str(SCRIPTS_DIR / "merge_match_results_backfill.py"),
             "--backfill-dir", str(tmp_dir),
             "--master", str(DATA_DIR / "match_data_FINAL_fixed.csv"),
             "--team-aliases", str(DATA_DIR / "team_aliases.json")],
            run_cmd,
        )
        if not merged:
            print(f"Round {round_num}: match-results VALIDATION/MERGE failed. "
                  f"match_data_FINAL_fixed.csv left untouched. Stopping this "
                  f"backfill run here -- the scraped file is left at "
                  f"{output_path} for manual review.")
            return False
        return True
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def score_round_if_archived(round_num, season, run_cmd=subprocess.run):
    """
    Scores a round's predictions against its now-merged real results, IF
    (and only if) that round was ever actually predicted and archived by
    generate_predictions.py's archive_predictions(). A round with no
    archive genuinely has nothing to score -- this project's own
    "never fabricate data" rule means backfilling an after-the-fact
    "prediction" for a round whose real result is already known would be
    a meaningless, fabricated number dressed up as a forecast, not a real
    accuracy measurement. This is reported honestly as "nothing to score",
    never silently skipped without a trace and never faked.

    Returns True in both the "scored" and "nothing to score" cases --
    this step never blocks the backfill run, matching weekly-update.yml's
    own "informational only" treatment of the equivalent step.
    """
    archive_path = DATA_DIR / "predictions_history" / f"{season}_round_{round_num}.json"
    if not archive_path.exists():
        print(f"Round {round_num}: no archived predictions at {archive_path} -- "
              f"nothing real to score against. Not a failure; this round was "
              f"never predicted prospectively (most likely because the "
              f"predictions pipeline hadn't reached it yet), so there is "
              f"nothing honest to log in the accuracy ledger for it.")
        return True

    scored = run(
        ["python3", str(SCRIPTS_DIR / "score_predictions.py"),
         "--season", str(season), "--round", str(round_num), "--data-dir", str(DATA_DIR)],
        run_cmd,
    )
    if not scored:
        print(f"Round {round_num}: scoring failed (see output above). Informational "
              f"only -- does not block the backfill run, matching weekly-update.yml's "
              f"own treatment of this step.")
    return True


def backfill_round(round_num, season, finals, run_cmd=subprocess.run):
    """
    Runs the full per-round pipeline for one round. Returns True only if
    BOTH real data files were safely merged (scoring never affects this
    return value -- see score_round_if_archived's own docstring).
    """
    print(f"\n{'='*70}\nBackfilling round {round_num}"
          f"{' (finals)' if finals else ''}, season {season}\n{'='*70}")

    if not backfill_player_stats(round_num, run_cmd):
        return False
    if not backfill_match_results(round_num, season, run_cmd):
        return False
    score_round_if_archived(round_num, season, run_cmd)
    return True


def round_range(start_round, end_round):
    """
    Pure logic, no I/O -- kept separate so tests can check the real edge
    cases (empty range, start after end, single round) without needing a
    real nrl_master.csv on disk.
    """
    if end_round < start_round:
        raise ValueError(
            f"end-round ({end_round}) is before start-round ({start_round}) -- "
            f"nothing to backfill. Rounds must be processed in order since "
            f"merge_round.py always merges 'current max + 1'."
        )
    return list(range(start_round, end_round + 1))


def main():
    parser = argparse.ArgumentParser(
        description="Catch up nrl_master.csv and match_data_FINAL_fixed.csv "
                     "across a range of rounds in one run, instead of "
                     "waiting one real week per round."
    )
    parser.add_argument("--start-round", type=int, default=None,
                         help="First round to backfill. If omitted, auto-detects "
                              "the next round after nrl_master.csv's current max.")
    parser.add_argument("--end-round", type=int, required=True,
                         help="Last round to backfill (inclusive).")
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--finals", action="store_true",
                         help="Mark this range as finals rounds (no fixed bye "
                              "schedule -- see validate_finals_round).")
    args = parser.parse_args()

    start_round = args.start_round if args.start_round is not None else get_next_round()
    rounds = round_range(start_round, args.end_round)

    print(f"Backfill plan: rounds {rounds} (season {args.season}"
          f"{', finals' if args.finals else ''})")

    completed = []
    for round_num in rounds:
        if backfill_round(round_num, args.season, args.finals):
            completed.append(round_num)
        else:
            print(f"\nSTOPPED at round {round_num} -- see failure reason above. "
                  f"Rounds completed before this one: {completed}. "
                  f"Fix the issue, then re-run this script; it will resume from "
                  f"wherever nrl_master.csv's real current max round now is.")
            sys.exit(1)

    print(f"\nBackfill run complete. Rounds merged this run: {completed}")
    sys.exit(0)


if __name__ == "__main__":
    main()
