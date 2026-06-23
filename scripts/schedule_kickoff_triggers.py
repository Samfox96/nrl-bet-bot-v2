"""
schedule_kickoff_triggers.py
==============================
Replaces Job B's unreliable hourly GitHub Actions cron with precise,
per-match triggers fired by cron-job.org.

Why this exists: GitHub's native `schedule:` cron is well-documented to be
imprecise for shared-runner workflows -- confirmed both by official sources
(queueing delays, worst at the top of the hour) and by Sam's own observed
real gaps (1h, 3h, 3h, 5h between supposedly-hourly runs, 2026-06-22). For
catching late lineup changes "within 1 hour of kickoff," that imprecision
defeats the purpose.

This script runs ONCE PER WEEK (triggered by a normal, imprecise GitHub
cron is fine here -- "sometime Tuesday/Wednesday" is an acceptable window
for *creating* next week's exact triggers; only the actual trigger moment
itself needs precision). It:

  1. Reuses Job B's already-tested discovery + kickoff-extraction logic to
     find the current round's matches and their exact AEST kickoff times.
  2. For each match, creates ONE cron-job.org scheduled job via their REST
     API, set to fire exactly 1 hour before that match's kickoff.
  3. Each cron-job.org job's action is an HTTP POST to GitHub's
     workflow_dispatch endpoint for team-list-polling.yml -- so at the
     precise moment, cron-job.org (not GitHub's congested scheduler) is
     what triggers Job B.

Credentials: both CRONJOB_API_KEY and a GitHub PAT with Actions:
read-and-write (here: GH_DISPATCH_TOKEN) are read from environment
variables -- set as GitHub Actions repository secrets, never hardcoded or
passed as plain arguments. See README/PROJECT_BRIEF for the exact secret
names configured in the repo (CRONJOB_API_KEY, WORKFLOW_DISPATCH_TOKEN).

NOT YET LIVE-TESTED. Built against real, documented APIs (cron-job.org's
official REST API docs and GitHub's official REST API docs, both fetched
and read directly -- not assumed), but the actual end-to-end chain (real
API call -> real scheduled job -> real fire -> real workflow_dispatch ->
real Job B run) has not yet been exercised. Follow the same test plan used
for every other piece of this project: verify with one near-future test
job before trusting this with real match data.
"""

import os
import sys
import time
import argparse
import requests
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from find_team_list_url import find_latest_team_list_url
from parse_draw_link_text import extract_kickoffs_from_html

CRONJOB_API_BASE = "https://api.cron-job.org"
GITHUB_API_BASE = "https://api.github.com"
GITHUB_OWNER = "Samfox96"
GITHUB_REPO = "nrl-bet-bot-v2"
TARGET_WORKFLOW_FILE = "team-list-polling.yml"
HOURS_BEFORE_KICKOFF = 1

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}


def get_required_env(name):
    value = os.environ.get(name)
    if not value:
        print(f"ERROR: required environment variable {name} is not set. "
              f"This must be supplied as a GitHub Actions secret, never hardcoded.")
        sys.exit(1)
    return value


def fetch_current_round_kickoffs():
    """
    Reuses Job B's existing, already-tested discovery logic: fetch the
    team-lists topic listing page, find the latest published round's
    article, fetch that article, extract every match's kickoff time.

    Returns (round_num, list_of_kickoff_dicts) where each dict has
    'home_team', 'away_team', 'kickoff_aest' (a datetime).
    """
    listing_resp = requests.get(
        "https://www.nrl.com/news/topic/team-lists/",
        headers=REQUEST_HEADERS, timeout=30
    )
    listing_resp.raise_for_status()

    discovery = find_latest_team_list_url(listing_resp.text)
    if discovery is None:
        print("No team-list article found on the listing page.")
        return None, []

    round_num, url = discovery
    print(f"Found round {round_num} team-list article: {url}")

    page_resp = requests.get(url, headers=REQUEST_HEADERS, timeout=30)
    page_resp.raise_for_status()

    kickoffs = extract_kickoffs_from_html(page_resp.text)
    print(f"Extracted {len(kickoffs)} kickoff times for round {round_num}.")

    return round_num, kickoffs


def create_cronjob_trigger(api_key, github_token, round_num, match, trigger_dt):
    """
    Creates one cron-job.org scheduled job that will fire a single POST to
    GitHub's workflow_dispatch endpoint at the given AEST datetime.

    Per cron-job.org's documented schedule format, each of hours/minutes/
    mdays/months/wdays is a list -- a single-element list pins it to that
    exact value, making this effectively a one-time trigger (it would only
    repeat if the same hour/minute/day/month combination ever recurred,
    which for a specific date does not happen again for a full year).
    """
    dispatch_url = (
        f"{GITHUB_API_BASE}/repos/{GITHUB_OWNER}/{GITHUB_REPO}"
        f"/actions/workflows/{TARGET_WORKFLOW_FILE}/dispatches"
    )

    job_title = (
        f"R{round_num} kickoff trigger: "
        f"{match['home_team']} v {match['away_team']} ({trigger_dt.strftime('%a %H:%M')})"
    )

    payload = {
        "job": {
            "title": job_title[:128],  # cron-job.org may cap title length; truncate defensively
            "url": dispatch_url,
            "enabled": True,
            "saveResponses": True,
            "requestMethod": 1,  # POST, per cron-job.org's RequestMethod enum
            "schedule": {
                "timezone": "Australia/Sydney",
                "expiresAt": 0,
                "hours": [trigger_dt.hour],
                "minutes": [trigger_dt.minute],
                "mdays": [trigger_dt.day],
                "months": [trigger_dt.month],
                "wdays": [-1],  # not used for date-pinning; every weekday allowed
            },
            "extendedData": {
                "headers": {
                    "Authorization": f"Bearer {github_token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                "body": '{"ref":"main"}',
            },
        }
    }

    response = requests.put(
        f"{CRONJOB_API_BASE}/jobs",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )

    # Safety net beyond the fixed inter-call delay: if we still hit the
    # rate limit (e.g. due to request latency variance), wait out a full
    # minute window and retry once rather than silently losing this
    # match's trigger. One retry is enough given the fixed delay between
    # calls already keeps us comfortably under the limit in normal cases.
    if response.status_code == 429:
        print(f"  Rate limited creating trigger for {match['home_team']} v "
              f"{match['away_team']} -- waiting 60s and retrying once.")
        time.sleep(60)
        response = requests.put(
            f"{CRONJOB_API_BASE}/jobs",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )

    if response.status_code == 200:
        job_id = response.json().get("jobId")
        print(f"  Created cron-job.org job {job_id}: {job_title}")
        return job_id
    else:
        print(f"  FAILED to create trigger for {match['home_team']} v {match['away_team']}: "
              f"HTTP {response.status_code} -- {response.text}")
        return None


def main():
    parser = argparse.ArgumentParser(
        description="Schedule precise per-match kickoff triggers via cron-job.org."
    )
    parser.add_argument("--dry-run", action="store_true",
                         help="Print what would be created without calling cron-job.org's API.")
    args = parser.parse_args()

    cronjob_api_key = get_required_env("CRONJOB_API_KEY")
    github_token = get_required_env("WORKFLOW_DISPATCH_TOKEN")

    round_num, kickoffs = fetch_current_round_kickoffs()
    if not kickoffs:
        print("No kickoffs found -- nothing to schedule this run.")
        sys.exit(0)

    now = datetime.now()
    created_count = 0

    for match in kickoffs:
        trigger_dt = match["kickoff_aest"] - timedelta(hours=HOURS_BEFORE_KICKOFF)

        if trigger_dt < now:
            print(f"Skipping {match['home_team']} v {match['away_team']}: "
                  f"trigger time {trigger_dt} is already in the past.")
            continue

        if args.dry_run:
            print(f"[DRY RUN] Would schedule trigger for "
                  f"{match['home_team']} v {match['away_team']} at {trigger_dt} AEST "
                  f"(kickoff {match['kickoff_aest']})")
            created_count += 1
            continue

        job_id = create_cronjob_trigger(
            cronjob_api_key, github_token, round_num, match, trigger_dt
        )
        if job_id:
            created_count += 1

        # cron-job.org's job-creation rate limit is TWO separate caps:
        # 1 request/second AND 5 requests/minute. A 2-second delay only
        # respects the per-second cap -- for a round with 8 matches, the
        # 6th call still lands inside the same 60-second window and gets
        # rejected with HTTP 429. CONFIRMED via a real run (2026-06-23):
        # exactly the 6th, 7th, and 8th calls failed with 429, matching
        # this exact math (5 succeeded within one minute, then 3 more
        # arrived too soon). Fixed by spacing calls 13 seconds apart,
        # comfortably under 5/minute (12s would be the exact limit; 13s
        # leaves margin for request latency).
        time.sleep(13)

    print(f"\nDone. {created_count}/{len(kickoffs)} triggers "
          f"{'would be ' if args.dry_run else ''}created for round {round_num}.")


if __name__ == "__main__":
    main()
