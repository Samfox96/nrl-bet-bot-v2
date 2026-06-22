"""
scrape_team_lists.py
======================
Job B: scrapes NRL.com's "Team Lists: Round N" article for the current round,
but only does real work when at least one match in the round is within 1
hour of kickoff -- otherwise exits immediately (cheap, frequent polling).

Designed to run hourly Thursday-Sunday via GitHub Actions. Each invocation:
  1. Works out which round is "this week's" round (the one currently being played).
  2. Finds that round's actual team-list article URL (the URL embeds a publish
     date we can't predict in advance -- discovered via the team-lists topic page).
  3. Parses it into structured player rows (parse_team_list.py).
  4. Checks each match's kickoff time (kickoff_time.py) against the current time.
  5. If nothing is within the 1-hour pre-kickoff window, exits without writing
     anything -- this is the expected/normal outcome on most hourly runs.
  6. If something IS in-window, overwrites data/team_lists_current.csv with the
     latest full scrape (per the decision to keep this simple -- no history
     of intermediate versions, just the latest).

Round-start-date assumption: every NRL round starts on a Thursday. This holds
for the vast majority of the season but is NOT guaranteed for every round
(bye-heavy rounds, representative weekends, finals). round_start_date is
passed as an explicit override option specifically so a human can correct it
on the weeks it doesn't hold, rather than the script silently assuming a
cadence that's wrong that week.
"""

import sys
import argparse
import re
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from parse_team_list import parse_match_headers, parse_team_list_page
from kickoff_time import resolve_kickoff_datetime, is_within_n_hours_before


def find_team_list_url(listing_page_text, round_num=None):
    """
    Discovers the team-list article URL using nrl.com's team-lists topic
    listing page (server-rendered, no JS-gating issue -- confirmed via real
    fetch 2026-06-22). See find_team_list_url.py for the underlying parser
    and its test against real listing-page content.

    If round_num is given, returns that specific round's URL if found.
    If round_num is None, returns the latest (most recent) round's URL --
    useful as a fallback "what's the current round" signal, though the
    authoritative round number should still come from nrl_master.csv where
    possible (this listing page reflects publish timing, which could in
    rare cases lag or lead the round nrl_master.csv considers "next").
    """
    from find_team_list_url import find_latest_team_list_url, find_all_team_list_urls

    if round_num is None:
        result = find_latest_team_list_url(listing_page_text)
        return result  # (round_num, url) or None

    for r, url in find_all_team_list_urls(listing_page_text):
        if r == round_num:
            return (r, url)
    return None


def get_current_round_and_kickoffs(nrl_master_path, kickoff_sidecar_dir):
    """
    Determines which round Job B should be polling for, and that round's
    kickoff times -- using two sources already produced elsewhere in the
    project, rather than recalculating from a date pattern:

      - "Which round": (max round in nrl_master.csv) + 1, same logic as
        Job A's merge_round.py. This is the round that's currently being
        played (Job A only merges AFTER a round finishes, so the round
        after the last merged one is, by construction, the in-progress one
        during the Thu-Sun window).
      - "Kickoff times for that round": read from the
        round_{N}_kickoffs.json sidecar file that nrl_update_single_round.py
        now saves during its draw-page visit (see parse_draw_link_text.py).

    Returns (round_num, list_of_kickoff_dicts). Raises FileNotFoundError
    with a clear message if the sidecar file doesn't exist yet -- this can
    legitimately happen if Job A hasn't run yet for this round, which Job B
    should treat as "nothing to do yet," not crash on.
    """
    import pandas as pd
    import json
    from pathlib import Path
    from datetime import datetime

    df = pd.read_csv(nrl_master_path)
    current_round = int(df["round"].max()) + 1

    sidecar_path = Path(kickoff_sidecar_dir) / f"round_{current_round}_kickoffs.json"
    if not sidecar_path.exists():
        raise FileNotFoundError(
            f"No kickoff data found at {sidecar_path}. This likely means Job A "
            f"hasn't visited round {current_round}'s draw page yet this week. "
            f"Job B has nothing to do until that sidecar file exists."
        )

    with open(sidecar_path) as f:
        raw_kickoffs = json.load(f)

    kickoffs = [
        {**k, "kickoff_aest": datetime.fromisoformat(k["kickoff_aest"])}
        for k in raw_kickoffs
    ]
    return current_round, kickoffs


def run(round_num, kickoffs, page_text, output_path, now=None, hours_before=1):
    """
    kickoffs: list of dicts with 'home_team', 'away_team', 'kickoff_aest'
    (a datetime) -- as produced by get_current_round_and_kickoffs(), sourced
    from Job A's sidecar file. This is more precise than recomputing from
    day-name + round-start-date (the original approach), since it uses the
    same UTC-to-AEST-converted timestamps already extracted from the live
    draw page for this specific round.
    """
    now = now or datetime.now()

    if not kickoffs:
        print(f"No kickoff data available for round {round_num}. Nothing to do.")
        return False

    in_window_matches = [
        k for k in kickoffs
        if is_within_n_hours_before(k["kickoff_aest"], now, hours=hours_before)
    ]

    if not in_window_matches:
        next_up = min(kickoffs, key=lambda k: abs((k["kickoff_aest"] - now).total_seconds()))
        print(f"No matches within {hours_before}h of kickoff right now ({now}). "
              f"Nearest match: {next_up['home_team']} v {next_up['away_team']} "
              f"at {next_up['kickoff_aest']}. Nothing to do this run.")
        return False

    print(f"{len(in_window_matches)} match(es) within {hours_before}h of kickoff:")
    for k in in_window_matches:
        print(f"  {k['home_team']} v {k['away_team']} -- kickoff {k['kickoff_aest']}")

    rows = parse_team_list_page(page_text, round_num=round_num)
    if not rows:
        print("Team-list page found but zero player rows parsed -- "
              "page structure may have changed. Not writing output.")
        return False

    import csv
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} player rows to {output_path}")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Job B: poll and scrape team lists near kickoff.")
    parser.add_argument("--nrl-master", type=str, default="data/nrl_master.csv")
    parser.add_argument("--kickoff-sidecar-dir", type=str, default="data/pending",
                         help="Directory where Job A saves round_{N}_kickoffs.json")
    parser.add_argument("--output", type=str, default="data/team_lists_current.csv")
    parser.add_argument("--hours-before", type=int, default=1)
    args = parser.parse_args()

    try:
        round_num, kickoffs = get_current_round_and_kickoffs(
            args.nrl_master, args.kickoff_sidecar_dir
        )
    except FileNotFoundError as e:
        print(str(e))
        sys.exit(0)  # not an error -- just nothing to do yet this week

    print(f"Polling for round {round_num}, {len(kickoffs)} matches tracked.")

    # NOTE: live fetch of the listing page + team-list page is the one piece
    # not yet exercised end-to-end against a live connection from this
    # script (the parsers themselves ARE tested against real fetched
    # content -- see find_team_list_url.py and parse_team_list.py self-tests).
    #
    # IMPORTANT, NOT YET VERIFIED: this uses plain `requests` rather than
    # Selenium, on the theory that both target pages render server-side
    # (no "couldn't load" JS-gating was observed when fetched). That's true
    # for what was actually fetched and inspected -- but nrl.com may still
    # serve different content to a plain HTTP client vs a real browser
    # (e.g. requiring a User-Agent header, or some anti-bot check that only
    # triggers on non-browser requests). This has NOT been tested from
    # within GitHub Actions. If this fails in practice, the fallback is
    # switching these two fetches to the same Selenium pattern
    # nrl_update_single_round.py already uses successfully.
    import requests

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }

    listing_resp = requests.get("https://www.nrl.com/news/topic/team-lists/",
                                  headers=headers, timeout=30)
    listing_resp.raise_for_status()
    discovery = find_team_list_url(listing_resp.text, round_num=round_num)
    if discovery is None:
        print(f"No published team-list article found yet for round {round_num}. "
              f"Nothing to do this run.")
        sys.exit(0)

    found_round, url = discovery
    print(f"Found team-list URL for round {found_round}: {url}")

    page_resp = requests.get(url, headers=headers, timeout=30)
    page_resp.raise_for_status()

    did_write = run(round_num, kickoffs, page_resp.text, args.output,
                     hours_before=args.hours_before)
    sys.exit(0)  # always exit 0 -- "nothing to do this hour" is not a failure
