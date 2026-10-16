"""
check_round_not_repeated.py
============================
Stops the predictions job when it comes back to a round it already did in an
earlier week.

Why this exists: the predictions job works out its round as "the highest
round in nrl_master.csv, plus one". When the player-stats update stalls (as it
did for Round 20, 19 Aug - 13 Oct 2026), that number stops moving, so the job
keeps generating predictions for the same round week after week and looks
perfectly healthy while doing it.

Every predictions run archives its output as data/predictions_history/
<season>_round_<round>.json with an "archived_at" time. Running a round again
within a few days is normal (a refresh before kickoff). Running it again
after more than --max-age-days means the pipeline did not move forward.
This script exits 1 in that case, which turns the workflow run red (and
Studio OS flags a failed run on a repo's main branch to Sam). If there is no
archive, or it can't be read, it exits 0: this is a safety net, never a
blocker.

Usage:
    python3 scripts/check_round_not_repeated.py --round 21 --season 2026
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


def archive_age(history_dir, season, rnd, now):
    """Returns how old the round's archive is, or None if there is none or it can't be read."""
    path = Path(history_dir) / f"{season}_round_{rnd}.json"
    try:
        stamp = json.loads(path.read_text(encoding="utf-8")).get("archived_at")
        when = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (OSError, ValueError, TypeError, AttributeError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return now - when


def main(argv=None, now=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--round", type=int, required=True)
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--history-dir", default="data/predictions_history")
    parser.add_argument("--max-age-days", type=float, default=5.0)
    args = parser.parse_args(argv)

    now = now or datetime.now(timezone.utc)
    age = archive_age(args.history_dir, args.season, args.round, now)
    if age is None:
        print(f"No earlier predictions for round {args.round}, so this is a new round. OK.")
        return 0
    if age > timedelta(days=args.max_age_days):
        print(
            f"STOP: predictions for round {args.round} of {args.season} were already made {age.days} days ago "
            f"(see {args.history_dir}), and this job is about to make them again. The pipeline did not move to a new "
            f"round, which usually means nrl_master.csv is stuck. Fix the player-stats update first (see STATUS.md "
            f"and the open 'needs manual review' issue). To refresh this round on purpose, run the workflow by hand "
            f"with a round_override."
        )
        return 1
    print(f"Round {args.round} was last predicted {age.days} days ago: a same-week refresh. OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
