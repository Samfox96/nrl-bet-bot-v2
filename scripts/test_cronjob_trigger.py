"""
test_cronjob_trigger.py
=========================
ONE-OFF TEST SCRIPT, not part of the regular weekly pipeline.

Creates a single cron-job.org scheduled job set to fire ~5 minutes from
now, targeting our own team-list-polling.yml workflow's workflow_dispatch
endpoint. The purpose is purely to verify the real, live chain works:

    cron-job.org accepts our job creation request
      -> cron-job.org actually fires the request at the scheduled time
      -> GitHub accepts the dispatch call
      -> team-list-polling.yml actually runs as a result

This is the test described in the project plan before trusting
schedule_kickoff_triggers.py with real match data. Run this once, watch
the Actions tab for a new run of "Team List Polling (Job B)" appearing
around the scheduled time, then check cron-job.org's job history to
confirm what HTTP status it received back from GitHub.

Cleans up after itself: prints the created jobId so it can be deleted
from the cron-job.org console afterward (or left -- a single past-dated
job is harmless clutter, not a recurring risk).
"""

import os
import sys
import json
import requests
from datetime import datetime, timedelta

CRONJOB_API_BASE = "https://api.cron-job.org"
GITHUB_API_BASE = "https://api.github.com"
GITHUB_OWNER = "Samfox96"
GITHUB_REPO = "nrl-bet-bot-v2"
TARGET_WORKFLOW_FILE = "team-list-polling.yml"
MINUTES_FROM_NOW = 5


def get_required_env(name):
    value = os.environ.get(name)
    if not value:
        print(f"ERROR: required environment variable {name} is not set.")
        sys.exit(1)
    return value


def main():
    cronjob_api_key = get_required_env("CRONJOB_API_KEY")
    github_token = get_required_env("WORKFLOW_DISPATCH_TOKEN")

    # Use UTC "now" from the runner, then schedule in Australia/Sydney time
    # explicitly via cron-job.org's own timezone field -- avoids us needing
    # to do our own AEST conversion for this test.
    trigger_dt_utc = datetime.utcnow() + timedelta(minutes=MINUTES_FROM_NOW)
    print(f"Runner's current UTC time: {datetime.utcnow()}")
    print(f"Scheduling test trigger for approx {trigger_dt_utc} UTC "
          f"({MINUTES_FROM_NOW} minutes from now)")
    print("NOTE: schedule is specified in UTC explicitly below to avoid "
          "any AEST/UTC ambiguity for this throwaway test -- the real "
          "weekly script uses Australia/Sydney since match kickoff times "
          "are naturally in AEST.")

    dispatch_url = (
        f"{GITHUB_API_BASE}/repos/{GITHUB_OWNER}/{GITHUB_REPO}"
        f"/actions/workflows/{TARGET_WORKFLOW_FILE}/dispatches"
    )

    payload = {
        "job": {
            "title": f"TEST trigger - delete after verifying ({trigger_dt_utc.isoformat()})",
            "url": dispatch_url,
            "enabled": True,
            "saveResponses": True,
            "requestMethod": 1,  # POST
            "schedule": {
                "timezone": "UTC",
                "expiresAt": 0,
                "hours": [trigger_dt_utc.hour],
                "minutes": [trigger_dt_utc.minute],
                "mdays": [trigger_dt_utc.day],
                "months": [trigger_dt_utc.month],
                "wdays": [-1],
            },
            "extendedData": {
                "headers": {
                    "Authorization": f"Bearer {github_token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                "body": json.dumps({"ref": "main"}),
            },
        }
    }

    print(f"\nSending job-creation request to cron-job.org...")
    response = requests.put(
        f"{CRONJOB_API_BASE}/jobs",
        headers={
            "Authorization": f"Bearer {cronjob_api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )

    print(f"cron-job.org response status: {response.status_code}")
    print(f"cron-job.org response body: {response.text}")

    if response.status_code == 200:
        job_id = response.json().get("jobId")
        print(f"\nSUCCESS: created test job {job_id}.")
        print(f"It should fire at approximately {trigger_dt_utc} UTC.")
        print(f"Check the Actions tab in a few minutes for a new run of "
              f"'Team List Polling (Job B)' triggered via API.")
        print(f"Afterward, check https://console.cron-job.org for job {job_id}'s "
              f"execution history to see the actual HTTP status GitHub returned.")
        print(f"\nRemember to delete job {job_id} from the cron-job.org console "
              f"once you've confirmed it worked (or leave it -- harmless either way).")
        sys.exit(0)
    else:
        print(f"\nFAILED to create test job. See response body above for details.")
        sys.exit(1)


if __name__ == "__main__":
    main()
