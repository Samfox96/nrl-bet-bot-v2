"""
validate_round.py
==================
Phase 3 automation gatekeeper.

Takes a freshly-scraped nrl_round_X_new.csv and decides whether it's safe
to auto-merge into data/nrl_master.csv, or whether it needs human review.

Exit code 0  = PASSED, safe to merge (caller proceeds with merge)
Exit code 1  = FAILED, do NOT merge (caller opens an issue / flags for review)

This mirrors the validation checklist already documented in STATUS.md:
- Row count sanity (no empty/near-empty scrape)
- Zero unmapped team names
- Zero duplicate (player, team, round, season) rows
- Team coverage matches the official bye schedule exactly
- No team has a suspiciously low row count (partial scrape per team)
- Round number in the data matches the round we asked for

Never silently merges on failure. Never assumes "no news is good news."
"""

import sys
import json
import pandas as pd
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"

MIN_ROWS_PER_TEAM = 10  # a full team sheet is ~17 players; <10 suggests partial scrape
ALL_TEAMS = {
    "Brisbane Broncos", "Canberra Raiders", "Canterbury-Bankstown Bulldogs",
    "Cronulla-Sutherland Sharks", "Dolphins", "Gold Coast Titans",
    "Manly-Warringah Sea Eagles", "Melbourne Storm", "Newcastle Knights",
    "North Queensland Cowboys", "New Zealand Warriors", "Parramatta Eels",
    "Penrith Panthers", "South Sydney Rabbitohs", "St George Illawarra Dragons",
    "Sydney Roosters", "Wests Tigers",
}

LAST_REGULAR_SEASON_ROUND = 27  # last round scripts/bye_schedule.json covers

# 2026 finals: which teams play round 28-31 depends on the ladder and who
# wins each week, not a pre-published bye list, so we can't check WHICH
# teams by name the way the regular season's fixed bye_schedule.json lets
# us. What IS fixed, every finals series, is how many teams survive each
# week -- so finals rounds get a team-COUNT check instead of a team-NAME
# check. Source: nrl.com's own 2026 draw (?competition=111&season=2026&
# round=28..31), confirmed during the regular-season backfill (see
# STATUS.md, 2026-10-13 session).
FINALS_TEAM_COUNTS = {
    28: 8,  # Finals Week 1 (top 8, 4 matches)
    29: 4,  # Finals Week 2 / Semi Finals (4 teams, 2 matches)
    30: 4,  # Finals Week 3 / Preliminary Finals (4 teams, 2 matches)
    31: 2,  # Grand Final (2 teams, 1 match)
}


def load_aliases():
    with open(DATA_DIR / "team_aliases.json") as f:
        return json.load(f)["aliases"]


def load_bye_schedule():
    with open(REPO_ROOT / "scripts" / "bye_schedule.json") as f:
        raw = json.load(f)
    return {int(k): v for k, v in raw.items() if not k.startswith("_")}


def normalize_team(name, aliases):
    return aliases.get(name, None)


def validate(new_csv_path, expected_round):
    failures = []
    warnings = []

    if not Path(new_csv_path).exists():
        return False, [f"File not found: {new_csv_path}"], []

    df = pd.read_csv(new_csv_path)

    # --- 1. Basic emptiness check ---
    if len(df) == 0:
        return False, ["Scrape produced zero rows. Aborting — nothing to validate."], []

    # --- 2. Round number consistency ---
    rounds_present = set(df["round"].unique())
    if rounds_present != {expected_round}:
        failures.append(
            f"Round mismatch: expected only round {expected_round}, "
            f"found rounds {sorted(rounds_present)} in the data."
        )

    # --- 3. Team name normalization check ---
    aliases = load_aliases()
    raw_teams = set(df["team"].unique())
    unmapped = [t for t in raw_teams if normalize_team(t, aliases) is None]
    if unmapped:
        failures.append(f"Unmapped team names found (not in team_aliases.json): {unmapped}")

    canonical_teams_present = {normalize_team(t, aliases) for t in raw_teams if normalize_team(t, aliases)}

    # --- 4. Duplicate check ---
    dup_subset = ["player_name", "team", "round", "season"]
    dupes = df[df.duplicated(subset=dup_subset, keep=False)]
    if len(dupes) > 0:
        failures.append(
            f"Found {len(dupes)} duplicate rows on {dup_subset}. "
            f"Example: {dupes[dup_subset].iloc[0].to_dict()}"
        )

    # --- 5. Team coverage check (regular season: bye schedule; finals: team count) ---
    if expected_round <= LAST_REGULAR_SEASON_ROUND:
        bye_schedule = load_bye_schedule()
        expected_byes = set(bye_schedule.get(expected_round, []))
        expected_playing = ALL_TEAMS - expected_byes
        missing_teams = expected_playing - canonical_teams_present
        unexpected_teams = canonical_teams_present - expected_playing

        if missing_teams:
            failures.append(
                f"Missing data for teams expected to play in round {expected_round} "
                f"(not on the bye list): {sorted(missing_teams)}"
            )
        if unexpected_teams:
            failures.append(
                f"Data present for teams expected to be on bye in round {expected_round}: "
                f"{sorted(unexpected_teams)}. Either the bye schedule is wrong or the scrape "
                f"pulled in the wrong round."
            )
    elif expected_round in FINALS_TEAM_COUNTS:
        # Finals: which teams survive is ladder-dependent, so we can only
        # check how MANY teams played, not which ones by name. The
        # unmapped-name check (#3) above already catches a genuinely bogus
        # team value; this catches a partial or wrong-round finals scrape.
        expected_count = FINALS_TEAM_COUNTS[expected_round]
        if len(canonical_teams_present) != expected_count:
            failures.append(
                f"Round {expected_round} is a finals round expected to have "
                f"{expected_count} teams playing, but {len(canonical_teams_present)} "
                f"teams were found in the data: {sorted(canonical_teams_present)}."
            )
    else:
        failures.append(
            f"No validation rule exists for round {expected_round} -- it is neither a "
            f"regular-season round (1-{LAST_REGULAR_SEASON_ROUND}, checked against "
            f"bye_schedule.json) nor a recognised 2026 finals round "
            f"({sorted(FINALS_TEAM_COUNTS)}). Refusing to guess at validity."
        )

    # --- 6. Per-team row count sanity (partial scrape detection) ---
    for raw_team in raw_teams:
        canon = normalize_team(raw_team, aliases)
        team_rows = len(df[df["team"] == raw_team])
        if team_rows < MIN_ROWS_PER_TEAM:
            warnings.append(
                f"Team '{canon or raw_team}' has only {team_rows} rows "
                f"(expected ~13-20 for a full squad sheet) — possible partial scrape."
            )

    # Row-count warnings are downgraded to failures if there are multiple,
    # since one short-staffed bench is plausible but several is a scrape problem.
    if len(warnings) >= 2:
        failures.append(
            f"{len(warnings)} teams have suspiciously low row counts — "
            f"this pattern suggests a systemic scrape failure, not individual short benches."
        )

    passed = len(failures) == 0
    return passed, failures, warnings


def main():
    if len(sys.argv) != 3:
        print("Usage: validate_round.py <path_to_new_csv> <expected_round_number>")
        sys.exit(2)

    csv_path = sys.argv[1]
    expected_round = int(sys.argv[2])

    passed, failures, warnings = validate(csv_path, expected_round)

    print(f"\n{'='*60}")
    print(f"VALIDATION REPORT — Round {expected_round}")
    print(f"{'='*60}\n")

    if warnings:
        print("WARNINGS (did not block merge, but worth a look):")
        for w in warnings:
            print(f"  - {w}")
        print()

    if passed:
        print("RESULT: PASSED — safe to auto-merge.\n")
        sys.exit(0)
    else:
        print("RESULT: FAILED — merge blocked. Human review required.\n")
        print("Failures:")
        for f in failures:
            print(f"  - {f}")
        print()
        sys.exit(1)


if __name__ == "__main__":
    main()
