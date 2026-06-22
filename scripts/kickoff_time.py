"""
kickoff_time.py
=================
Resolves a match's actual kickoff datetime, combining:
  - the round's Thursday start date (the anchor we know from the NRL's
    Thu-Sun round cycle, confirmed for round 17: Thu Jun 25 - Sun Jun 28 2026)
  - the day-of-week and time-of-day parsed from the team-list page
    (e.g. "Friday" + "8.00pm")

This is needed so the polling job can ask "is any match in this round
kicking off within the next hour?" using real datetimes, not just day names.

Known limitation, stated plainly: this assumes a clean Thu-Sun round, which
is true for most rounds but NOT all -- bye-heavy rounds or representative
rounds (Origin weekends) can shift the pattern. The round's start date
should ideally be confirmed against the official draw each time, not just
assumed as "last round's start + 7 days" indefinitely. For now this takes
the round start date as an explicit input rather than calculating it, so
whoever runs it supplies the verified date rather than the script silently
assuming a fixed cadence.
"""

from datetime import datetime, timedelta
import re

DAY_OFFSETS = {
    "thursday": 0, "friday": 1, "saturday": 2, "sunday": 3,
    "monday": 4, "tuesday": 5, "wednesday": 6,  # rare, but draws occasionally shift
}


def parse_time_12h(time_str):
    """
    Parses '8.00pm' or '5:00pm' or '2.00pm' into (hour_24, minute).
    NRL team-list pages use a period as the separator ('8.00pm'), not a colon.
    """
    cleaned = time_str.strip().lower().replace(".", ":")
    m = re.match(r"(\d{1,2}):(\d{2})\s*(am|pm)", cleaned)
    if not m:
        raise ValueError(f"Could not parse time string: {time_str!r}")
    hour, minute, period = int(m.group(1)), int(m.group(2)), m.group(3)
    if period == "pm" and hour != 12:
        hour += 12
    if period == "am" and hour == 12:
        hour = 0
    return hour, minute


def resolve_kickoff_datetime(round_thursday_date, match_day, match_time):
    """
    round_thursday_date: a date (or datetime) object for the round's Thursday.
    match_day: e.g. "Friday", "Saturday", "Sunday" (as parsed from the page).
    match_time: e.g. "8.00pm" (as parsed from the page).

    Returns a datetime for the actual kickoff, in AEST (naive datetime --
    timezone handling kept simple/explicit rather than relying on a tz
    library not yet confirmed available in the Actions runner).
    """
    day_key = match_day.strip().lower()
    if day_key not in DAY_OFFSETS:
        raise ValueError(f"Unrecognized match day: {match_day!r}")

    offset_days = DAY_OFFSETS[day_key]
    match_date = round_thursday_date + timedelta(days=offset_days)
    hour, minute = parse_time_12h(match_time)

    return datetime(match_date.year, match_date.month, match_date.day, hour, minute)


def is_within_n_hours_before(kickoff_dt, now_dt, hours=1):
    """
    True if `now_dt` is within `hours` hours BEFORE kickoff (not after --
    once the game has started there's no more "late mail" to catch).
    """
    delta = kickoff_dt - now_dt
    return timedelta(0) <= delta <= timedelta(hours=hours)


if __name__ == "__main__":
    # Self-test using Round 16's real, known matches (confirmed against the
    # actual fetched team-list page) as ground truth.
    round16_thursday = datetime(2026, 6, 18)  # the Thursday Round 16 started

    test_cases = [
        ("Friday", "8.00pm", datetime(2026, 6, 19, 20, 0)),     # Knights v Dragons
        ("Saturday", "3.00pm", datetime(2026, 6, 20, 15, 0)),   # Wests Tigers v Dolphins
        ("Saturday", "5.30pm", datetime(2026, 6, 20, 17, 30)),  # Titans v Panthers
        ("Sunday", "6.15pm", datetime(2026, 6, 21, 18, 15)),    # Roosters v Sharks
    ]

    print("Kickoff resolution self-test:")
    all_passed = True
    for day, time_str, expected in test_cases:
        result = resolve_kickoff_datetime(round16_thursday, day, time_str)
        passed = result == expected
        all_passed &= passed
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {day} {time_str} -> {result} (expected {expected})")

    print(f"\nAll passed: {all_passed}")

    # Test the "within 1 hour before kickoff" window logic
    print("\n'Within 1 hour before kickoff' window test:")
    kickoff = datetime(2026, 6, 19, 20, 0)  # 8:00pm Friday
    checks = [
        (datetime(2026, 6, 19, 18, 30), False, "90 min before -- too early"),
        (datetime(2026, 6, 19, 19, 30), True,  "30 min before -- in window"),
        (datetime(2026, 6, 19, 20, 0),  True,  "exactly at kickoff -- in window"),
        (datetime(2026, 6, 19, 20, 30), False, "30 min after -- too late"),
    ]
    for now, expected, label in checks:
        result = is_within_n_hours_before(kickoff, now, hours=1)
        status = "PASS" if result == expected else "FAIL"
        print(f"  [{status}] {label}: got {result}, expected {expected}")
