name: Schedule Kickoff Triggers (cron-job.org)

# Runs once a week to set up THIS round's precise, per-match kickoff
# triggers via cron-job.org -- replacing the old, unreliable hourly GitHub
# cron approach (confirmed imprecise by real observed gaps of 1-5 hours,
# 2026-06-22).
#
# Timing of THIS workflow itself doesn't need to be precise -- it just
# needs to run sometime after the round's team list is published and
# before the first match of the round, so there's a comfortable window.
# Team lists are typically published a few days before a round starts
# (confirmed: Round 16's list published 2026-06-16 for a round starting
# 2026-06-18). Running this on two mornings (Wednesday and Thursday AEST --
# see the cron comments below for why the day-of-week fields say 2/3) gives
# two chances to catch a freshly-published list even if one day's run is early.
#
# What it actually does (schedule_kickoff_triggers.py):
#   1. Finds the current round's team-list article and extracts every
#      match's real AEST kickoff time (reusing Job B's already-tested
#      discovery + parsing logic).
#   2. For each match, creates one cron-job.org scheduled job set to fire
#      a single workflow_dispatch call to team-list-polling.yml exactly
#      1 hour before that match's kickoff.
#
# Confirmed live-working end to end via a manual one-off test
# (2026-06-22/23): cron-job.org job creation, precise firing, and GitHub
# accepting the resulting workflow_dispatch call were all verified before
# this real weekly version was wired in.
on:
  schedule:
    - cron: '17 20 * * 2'  # Wed ~6:17am AEST -- NOTE: cron day-of-week 2 is Tuesday in UTC, but 20:17 UTC + 10h AEST rolls over to WEDNESDAY morning AEST. Comment corrected 2026-07-03 (was mislabelled "Tuesday"). Behaviour unchanged and confirmed working -- only the label was wrong. (:17 offset avoids GitHub's on-the-hour queueing pile-up.)
    - cron: '17 20 * * 3'  # Thu ~6:17am AEST -- likewise cron day 3 is Wednesday UTC, firing THURSDAY morning AEST after the +10h rollover. Second chance in case the first run was before the team list was published. Comment corrected 2026-07-03 (was mislabelled "Wednesday").
  workflow_dispatch: {}

jobs:
  schedule-triggers:
    runs-on: ubuntu-latest
    timeout-minutes: 10

    steps:
      - name: Check out repo
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install requests beautifulsoup4

      - name: Schedule this round's kickoff triggers
        env:
          CRONJOB_API_KEY: ${{ secrets.CRONJOB_API_KEY }}
          WORKFLOW_DISPATCH_TOKEN: ${{ secrets.WORKFLOW_DISPATCH_TOKEN }}
        run: python3 scripts/schedule_kickoff_triggers.py

# STATUS as of 2026-06-23: script logic (time math, payload construction)
# unit-tested against real captured data; the cron-job.org API call itself
# proven live via a separate one-off test (test_cronjob_trigger.py). This
# specific weekly wiring -- running the REAL script (not the test one)
# against a REAL upcoming round -- has not yet executed. Treat the first
# real run as a genuine test, same as everything else in this project.
