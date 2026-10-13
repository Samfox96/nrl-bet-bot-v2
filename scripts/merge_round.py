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


def find_pending_file(expected_round):
    """
    REAL BUG FOUND AND FIXED 2026-10-13: this used to be
    `sorted(PENDING_DIR.glob("nrl_round_*_new.csv"))[0]` -- "just take the
    first pending file alphabetically". That silently broke the moment more
    than one pending file existed at once, which is exactly what happened:
    Round 19's first attempt failed validation and was committed to
    data/pending/ "for review" (by design -- see the failure path below).
    Round 19's retry later succeeded and merged cleanly, but the retry's
    local `pending_csv.unlink()` only deletes the file on disk -- the
    workflow's own "Commit changes" step (in weekly-update.yml) only
    `git add`s data/nrl_master.csv and STATUS.md, never data/pending, so
    that deletion was never actually committed. The stale
    nrl_round_19_new.csv stayed tracked in git forever. Every week since,
    "nrl_round_19_new.csv" sorted before "nrl_round_20_new.csv"
    alphabetically, so this function kept handing the OLD round-19 file to
    validate_round.py while asking it to validate round 20 -- which always
    failed on the very first check ("Round mismatch: expected only round
    20, found rounds [19]"), every single week, while round 20's own
    genuinely-fine scrape sat right next to it, never actually tried.

    Real fix: ask for the exact filename the expected round's scrape step
    wrote this run, instead of guessing from a sorted directory listing.
    Any other pending file left over from a previous round is reported as
    a warning (so it's visible, not re-introducing a silent problem) but
    never mistaken for the one we're supposed to process.
    """
    pending_files = sorted(PENDING_DIR.glob("nrl_round_*_new.csv")) if PENDING_DIR.exists() else []
    expected_path = PENDING_DIR / f"nrl_round_{expected_round}_new.csv"

    leftovers = [p for p in pending_files if p != expected_path]
    if leftovers:
        print(f"WARNING: found {len(leftovers)} other pending file(s) that do NOT match "
              f"the expected round ({expected_round}): {[p.name for p in leftovers]}. "
              f"These are leftovers from an earlier round -- most likely a validation "
              f"failure that was later fixed and merged some other way without the pending "
              f"file itself ever being cleaned up from git. Ignoring them; they will not "
              f"be processed or deleted by this run. If one of these corresponds to a round "
              f"that is NOT yet in nrl_master.csv, investigate and merge it manually -- "
              f"this script only ever acts on the current expected round.")

    if not expected_path.exists():
        # REAL BUG FOUND AND FIXED 2026-07-03: this used to exit(0) when no
        # pending file existed at all -- "nothing to do" was treated as a
        # benign no-op. But this script exists ONLY to consume the output
        # of the scrape step that runs immediately before it in
        # weekly-update.yml -- there is no legitimate scenario where this
        # script runs and the expected round's pending file is genuinely,
        # correctly absent. A missing file here means the scrape step
        # failed to produce one (confirmed real case: Round 17, scraper
        # crashed on a missing bs4 import before writing anything).
        # Exiting 0 made that look like a clean merge to the workflow,
        # which let a stale-data digest email fire under the new round's
        # label. The absence of real content IS the failure signal here,
        # not a side effect to shrug off.
        print(f"FAILURE: no pending file found for the expected round ({expected_round}) at "
              f"{expected_path}. This script only ever runs immediately after a scrape step "
              f"that should have produced exactly this file -- its absence means that scrape "
              f"did not genuinely succeed, even if it didn't raise an exception.")
        sys.exit(1)

    return expected_path


def main():
    expected_round = get_next_round()
    pending_csv = find_pending_file(expected_round)

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
