"""
merge_round.py
===============
Phase 3 automation — the orchestrator that ties scrape -> validate -> merge together.

Workflow:
1. Determine the next round to scrape (max round in nrl_master.csv + 1).
2. Expect a freshly-scraped file at data/pending/nrl_round_X_new.csv
   (produced by the scraper step in the Actions workflow, run earlier in the job).
3. Run validate_round.py against it.
4. If PASSED: merge into data/nrl_master.csv, update STATUS.md, clean up the pending file.
5. If FAILED: leave the pending file in place under data/pending/, write a
   failure report, and exit nonzero so the Actions workflow opens an Issue
   instead of committing anything to nrl_master.csv.

This script NEVER merges on failure. There is no override flag, by design —
per the project's failsafe rule, partial or unverified data is never silently
treated as final.
"""

import sys
import subprocess
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
PENDING_DIR = DATA_DIR / "pending"
MASTER_CSV = DATA_DIR / "nrl_master.csv"
STATUS_MD = REPO_ROOT / "STATUS.md"
VALIDATE_SCRIPT = REPO_ROOT / "scripts" / "validate_round.py"


def get_next_round():
    if not MASTER_CSV.exists():
        raise FileNotFoundError(f"{MASTER_CSV} not found — cannot determine current round.")
    df = pd.read_csv(MASTER_CSV)
    current_max = int(df["round"].max())
    return current_max + 1


def run_validation(pending_csv, round_num):
    result = subprocess.run(
        ["python3", str(VALIDATE_SCRIPT), str(pending_csv), str(round_num)],
        capture_output=True, text=True
    )
    print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    return result.returncode == 0, result.stdout


def merge_into_master(pending_csv, round_num):
    """
    NOTE: this function intentionally only touches the stats CSV
    (nrl_round_{N}_new.csv), never any round_{N}_kickoffs.json sidecar file
    that may exist alongside it in the same directory. The kickoff sidecar
    is for the round CURRENTLY being played (used by Job B's polling), while
    this merge function only ever processes a round that has ALREADY
    finished (the round immediately after the last one in nrl_master.csv).
    At any point during a Thu-Sun window these are two different round
    numbers -- conflating their cleanup would delete data Job B still needs.
    """
    new_df = pd.read_csv(pending_csv)
    master_df = pd.read_csv(MASTER_CSV)

    before = len(master_df)
    combined = pd.concat([master_df, new_df], ignore_index=True)
    combined = combined.drop_duplicates(
        subset=["player_name", "team", "round", "season"], keep="last"
    ).reset_index(drop=True)
    after = len(combined)

    combined.to_csv(MASTER_CSV, index=False)

    pending_csv.unlink()  # remove ONLY the stats pending file, never the kickoff sidecar

    return before, after, len(new_df)


def update_status_md(round_num, rows_added, before, after, validation_output):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    entry = (
        f"\n## Round {round_num} Auto-Merge Summary ({today})\n"
        f"- Scraped and validated automatically via GitHub Actions (Phase 3)\n"
        f"- {rows_added} rows added, {before} -> {after} total rows in nrl_master.csv\n"
        f"- Validation: PASSED (see workflow log for full report)\n"
    )
    with open(STATUS_MD, "a") as f:
        f.write(entry)


def main():
    pending_files = sorted(PENDING_DIR.glob("nrl_round_*_new.csv")) if PENDING_DIR.exists() else []

    if not pending_files:
        print("No pending scrape file found in data/pending/. Nothing to merge.")
        sys.exit(0)

    if len(pending_files) > 1:
        print(f"WARNING: multiple pending files found: {pending_files}. "
              f"Processing only the first; investigate the rest manually.")

    pending_csv = pending_files[0]
    expected_round = get_next_round()

    print(f"Next expected round: {expected_round}")
    print(f"Pending file: {pending_csv}")

    passed, validation_output = run_validation(pending_csv, expected_round)

    if not passed:
        print(f"\nValidation FAILED for round {expected_round}.")
        print(f"File left in place at {pending_csv} for manual review.")
        print("No changes made to nrl_master.csv.")
        sys.exit(1)

    before, after, rows_added = merge_into_master(pending_csv, expected_round)
    update_status_md(expected_round, rows_added, before, after, validation_output)

    print(f"\nMerge SUCCESSFUL: round {expected_round}, "
          f"{rows_added} rows added, nrl_master.csv now {before} -> {after} rows.")
    sys.exit(0)


if __name__ == "__main__":
    main()
