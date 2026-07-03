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
import json
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
TEAM_ALIASES_JSON = DATA_DIR / "team_aliases.json"
POSITION_ALIASES_JSON = DATA_DIR / "position_aliases.json"


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


def normalize_to_canonical(df):
    """
    Added 2026-06-23 after a full system audit found nrl_master.csv had
    stored raw, unnormalized team/position values since the scraper was
    first built -- normalization only ever happened at point-of-use in
    each consumer script, never at the source. A one-time migration
    (migrate_nrl_master_to_canonical.py) fixed all EXISTING rows; this
    function is the companion piece that keeps every FUTURE merged round
    consistent, by normalizing team/opponent/position to canonical form
    (via team_aliases.json/position_aliases.json) right before each new
    round's rows join nrl_master.csv. Without this, the very next merge
    after the migration would silently reintroduce the old raw format
    and the inconsistency would return within a week.

    Raises (does not silently skip) if any value fails to resolve --
    matching migrate_nrl_master_to_canonical.py's own refuse-rather-than-
    guess behaviour, since a silently-unconverted row is worse than a
    loud failure that gets investigated.
    """
    with open(TEAM_ALIASES_JSON) as f:
        team_aliases = json.load(f)["aliases"]
    with open(POSITION_ALIASES_JSON) as f:
        position_aliases = json.load(f)["aliases"]

    def normalize_or_raise(value, aliases, field_name):
        canonical = aliases.get(value)
        if canonical is None:
            raise ValueError(
                f"Cannot merge: unmapped {field_name} value '{value}' found in "
                f"the freshly-scraped round data -- not present in the relevant "
                f"aliases.json file. Add it there first (this is exactly the "
                f"kind of new/renamed team or position variant the alias files "
                f"exist to catch), then re-run the merge."
            )
        return canonical

    df["team"] = df["team"].apply(lambda v: normalize_or_raise(v, team_aliases, "team"))
    df["opponent"] = df["opponent"].apply(lambda v: normalize_or_raise(v, team_aliases, "opponent"))
    df["position"] = df["position"].apply(lambda v: normalize_or_raise(v, position_aliases, "position"))
    return df


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
    new_df = normalize_to_canonical(new_df)
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
        # REAL BUG FOUND AND FIXED 2026-07-03: this used to exit(0) --
        # "nothing to do" was treated as a benign no-op, which is a
        # reasonable default for a script that might run when nothing
        # changed. But in this specific pipeline, merge_round.py exists
        # ONLY to consume the output of the scrape step that runs
        # immediately before it in weekly-update.yml -- there is no
        # legitimate scenario where this script runs and a pending file
        # is genuinely, correctly absent. A missing file here means the
        # scrape step failed to produce one (confirmed real case:
        # Round 17, scraper crashed on a missing bs4 import before
        # writing anything). Exiting 0 made that look like a clean
        # merge to the workflow, which let a stale-data digest email
        # fire under the new round's label. This is exactly the
        # "content-based, not exception-based" checkpoint principle --
        # the absence of real content IS the failure signal here, not
        # a side effect to shrug off. Exiting 1 now ensures the
        # workflow's failure-issue path fires and the digest/commit
        # steps (gated on this step's success) correctly skip.
        print("FAILURE: No pending scrape file found in data/pending/. "
              "This script only ever runs immediately after a scrape step "
              "that should have produced one -- a missing file means that "
              "scrape did not genuinely succeed, even if it didn't raise "
              "an exception. Treating this as a real failure, not a "
              "no-op, so nothing downstream (commit, digest) proceeds "
              "on the strength of a merge that never actually happened.")
        sys.exit(1)

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
