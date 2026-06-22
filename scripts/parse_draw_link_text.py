"""
parse_draw_link_text.py
=========================
Parses the aria-label/link-text pattern found on NRL.com's draw pages, e.g.:

    "Round 16 - Round 16 - Friday 19 Jun 10:00 am Knightshome TeamKnights
     Dragonsaway TeamDragons"

IMPORTANT, confirmed by cross-referencing this exact text against the same
match's kickoff time on the team-list page: the time embedded in this link
text is UTC, not AEST. "Friday 19 Jun 10:00 am" (this link text) is the same
match as "Friday 8.00pm AEST" (team-list page) -- a 10-hour offset, which is
exactly the AEST UTC+10 offset. Every parsed time here gets shifted +10h to
match local AEST throughout the rest of the project.

This was NOT obvious from the text alone and would have silently produced
kickoff times 10 hours wrong if unverified. Always cross-check a new data
source's timezone against a second, independently-sourced data point before
trusting it -- single-source timestamps are a common, easy-to-miss bug.
"""

import re
from datetime import datetime, timedelta

AEST_OFFSET_HOURS = 10

LINK_TEXT_PATTERN = re.compile(
    r"Round (?P<round>\d+) - Round \d+ - "
    r"(?P<day>\w+) (?P<date>\d{1,2}) (?P<month>\w+) "
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2}) (?P<ampm>am|pm) "
    r"(?P<home>.+?)home Team(?P=home) "
    r"(?P<away>.+?)away Team(?P=away)"
)

MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def parse_draw_link(text, year=2026):
    """
    Parses one draw-page link's text into structured match info, with the
    kickoff time converted from UTC (as embedded in the source) to AEST.

    Returns None if the text doesn't match the expected pattern (callers
    should treat that as "skip this link," not crash the whole scrape --
    the draw page may contain other links that don't describe matches).
    """
    m = LINK_TEXT_PATTERN.search(text)
    if not m:
        return None

    d = m.groupdict()
    month_num = MONTH_MAP.get(d["month"].strip().lower()[:3])
    if month_num is None:
        return None

    hour, minute = int(d["hour"]), int(d["minute"])
    if d["ampm"] == "pm" and hour != 12:
        hour += 12
    if d["ampm"] == "am" and hour == 12:
        hour = 0

    utc_dt = datetime(year, month_num, int(d["date"]), hour, minute)
    aest_dt = utc_dt + timedelta(hours=AEST_OFFSET_HOURS)

    return {
        "round": int(d["round"]),
        "home_team": d["home"].strip(),
        "away_team": d["away"].strip(),
        "kickoff_aest": aest_dt,
    }


if __name__ == "__main__":
    # Self-test against real link text captured from yesterday's actual
    # successful scrape of the Round 16 draw page, cross-checked against
    # the independently-confirmed kickoff times from the team-list page.
    test_lines = [
        ("Round 16 - Round 16 - Friday 19 Jun 10:00 am Knightshome TeamKnights Dragonsaway TeamDragons",
         datetime(2026, 6, 19, 20, 0)),  # expected: Fri 8:00pm AEST (confirmed via team-list page)
        ("Round 16 - Round 16 - Saturday 20 Jun 5:00 am Wests Tigershome TeamWests Tigers Dolphinsaway TeamDolphins",
         datetime(2026, 6, 20, 15, 0)),  # expected: Sat 3:00pm AEST
        ("Round 16 - Round 16 - Sunday 21 Jun 8:15 am Roostershome TeamRoosters Sharksaway TeamSharks",
         datetime(2026, 6, 21, 18, 15)),  # expected: Sun 6:15pm AEST
    ]

    print("Draw link text parsing self-test (UTC -> AEST conversion):")
    all_passed = True
    for text, expected_aest in test_lines:
        result = parse_draw_link(text)
        passed = result is not None and result["kickoff_aest"] == expected_aest
        all_passed &= passed
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {result['home_team'] if result else '?'} v "
              f"{result['away_team'] if result else '?'} -> "
              f"{result['kickoff_aest'] if result else None} (expected {expected_aest})")

    print(f"\nAll passed: {all_passed}")
