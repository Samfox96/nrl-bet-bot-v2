"""
send_round_digest.py

Formats a digest dict (from generate_round_digest.build_digest) into a
plain-text + HTML email and sends it via Resend's API.

DESIGN DECISIONS (locked in 2026-06-23):
  - Resend, not SMTP/Gmail app password -- avoids the fragility of
    automated sending through a personal Gmail account, and matches the
    project's existing pattern of one small, scoped API-key secret per
    external service (same as CRONJOB_API_KEY, WORKFLOW_DISPATCH_TOKEN).
  - Sandbox sender (onboarding@resend.dev) -- this is a single personal
    notification, not a product; verifying a domain isn't worth it.
    Resend's free tier (3,000/month, 100/day as of mid-2026) comfortably
    covers one email per week.
  - Triggered as the FINAL step of Job A's successful merge, not a
    separate scheduled job -- Job A already knows which round number
    just got merged, so piggybacking avoids duplicating that "which
    round is current" logic in a second job. Only fires on a clean
    merge; validation failures already open a GitHub Issue separately
    and should NOT also trigger a "good news" digest email.

WHAT THIS DOES NOT DO (explicit, not an oversight):
  - No real betting-market line movement (Phase 10 isn't built). The
    email copy below deliberately says "form trend", never "line
    movement", to avoid implying market data that doesn't exist yet.
  - No week-over-week diffing of DUE flags yet -- see
    generate_round_digest.py's module docstring for why, and the
    due_flags_snapshot mechanism below that lays groundwork for it.
"""

import json
import os
import urllib.request
import urllib.error


RESEND_API_URL = "https://api.resend.com/emails"
SANDBOX_FROM = "NRL Bet Bot <onboarding@resend.dev>"


def _describe_due_factors(flag, max_reasons=2):
    """
    Translates the strongest 1-2 contributing factors into plain
    English, so the email shows WHY a player is flagged rather than
    just a composite number. Picks the highest-magnitude factors
    (by absolute normalised value), since those are what's actually
    driving the score for this specific player.
    """
    factor_labels = {
        "drought": lambda v: (
            f"cold lately ({flag['recent_tpg']:.2f} TPG recent vs "
            f"{flag['season_tpg']:.2f} season)" if v > 0 else
            f"actually in great form right now"
        ),
        "opponent_matchup": lambda v: (
            f"a favourable matchup vs {flag['opponent_this_round']} this week" if v > 0 else
            f"a tough matchup vs {flag['opponent_this_round']} this week"
        ),
        "team_form": lambda v: (
            f"{flag['team']} attack trending up" if v > 0 else
            f"{flag['team']} attack trending down"
        ),
        "usage_trend": lambda v: (
            "rising involvement lately" if v > 0 else "involvement dipping lately"
        ),
        "structure_share": lambda v: (
            "growing share of team's ball (approx.)" if v > 0 else
            "shrinking share of team's ball (approx.)"
        ),
    }
    factors = flag["factors"]
    available = [(k, v) for k, v in factors.items() if v is not None]
    available.sort(key=lambda kv: abs(kv[1]), reverse=True)
    reasons = [factor_labels[k](v) for k, v in available[:max_reasons]]
    return reasons


def format_plain_text(digest):
    lines = []
    lines.append(f"NRL Bet Bot — Round {digest['round']} Digest")
    lines.append(f"({digest['row_count']} player-rows merged)")
    lines.append("")

    if digest["top_performances"]:
        lines.append("TOP PERFORMANCES")
        for fact in digest["top_performances"]:
            lines.append(f"  - {fact}")
        lines.append("")

    if digest["form_trends"]:
        lines.append("FORM TRENDS")
        for fact in digest["form_trends"]:
            lines.append(f"  - {fact}")
        lines.append("")

    if digest["due_flags"]:
        lines.append("DUE WATCH (composite of drought, opponent matchup, team form, usage trend, attacking share)")
        for flag in digest["due_flags"]:
            reasons = _describe_due_factors(flag)
            reason_str = "; ".join(reasons)
            lines.append(
                f"  - {flag['player_name']} ({flag['team']}, {flag['position_code']}), "
                f"score {flag['composite_score']:.2f}: {reason_str}"
            )
        lines.append("")

    if digest["zcr_shifts"]:
        lines.append("DEFENSE WATCH (tries conceded by position vs 2021-2025 historical rate)")
        for fact in digest["zcr_shifts"]:
            lines.append(f"  - {fact}")
        lines.append("")

    if not any([digest["top_performances"], digest["form_trends"], digest["due_flags"], digest["zcr_shifts"]]):
        lines.append("No notable trends surfaced this round — data merged cleanly, nothing stood out.")

    return "\n".join(lines)


def format_html(digest):
    def section(title, items, render_item):
        if not items:
            return ""
        rendered = "".join(f"<li>{render_item(i)}</li>" for i in items)
        return f"<h3>{title}</h3><ul>{rendered}</ul>"

    body = f"<h2>NRL Bet Bot — Round {digest['round']} Digest</h2>"
    body += f"<p>{digest['row_count']} player-rows merged.</p>"

    body += section("Top Performances", digest["top_performances"], lambda f: f)
    body += section("Form Trends", digest["form_trends"], lambda f: f)
    body += section(
        "Due Watch",
        digest["due_flags"],
        lambda f: (
            f"<b>{f['player_name']}</b> ({f['team']}, {f['position_code']}), "
            f"score {f['composite_score']:.2f}: {'; '.join(_describe_due_factors(f))}"
        ),
    )
    body += section("Defense Watch", digest["zcr_shifts"], lambda f: f)

    if not any([digest["top_performances"], digest["form_trends"], digest["due_flags"], digest["zcr_shifts"]]):
        body += "<p>No notable trends surfaced this round — data merged cleanly, nothing stood out.</p>"

    return body


def send_digest_email(digest, to_email, api_key=None):
    """
    Sends the digest via Resend's API. api_key defaults to the
    RESEND_API_KEY environment variable (set as a GitHub Actions secret
    in the live workflow -- never pass a literal key in code).

    Returns the parsed JSON response on success. Raises on any non-2xx
    response rather than silently swallowing a failed send -- a failed
    notification should be visible in the workflow logs, not hidden.
    """
    if api_key is None:
        api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        raise RuntimeError(
            "No Resend API key provided. Set RESEND_API_KEY as a GitHub "
            "Actions secret, or pass api_key explicitly for local testing."
        )

    payload = {
        "from": SANDBOX_FROM,
        "to": [to_email],
        "subject": f"NRL Bet Bot — Round {digest['round']} Digest",
        "text": format_plain_text(digest),
        "html": format_html(digest),
    }

    req = urllib.request.Request(
        RESEND_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        raise RuntimeError(f"Resend API error {e.code}: {error_body}") from e


def write_due_flags_snapshot(digest, path="due_flags_last_run.json"):
    """
    Persists this run's DUE list keyed by round number, so a FUTURE
    session has two real data points to diff against when building
    actual week-over-week "new DUE flags" comparison logic. This
    function deliberately does NOT diff anything itself -- see
    generate_round_digest.py's module docstring for why that's left
    for later rather than guessed at now with only one real run's data.
    """
    snapshot = {
        "round": digest["round"],
        "season": digest["season"],
        "due_flags": digest["due_flags"],
    }
    with open(path, "w") as f:
        json.dump(snapshot, f, indent=2)
    return path


if __name__ == "__main__":
    # Dry-run: prints the formatted email content without sending,
    # so the content can be reviewed before wiring in a real API key.
    from generate_round_digest import build_digest

    digest = build_digest("nrl_master.csv", round_num=16, season=2026)
    print("=== PLAIN TEXT VERSION ===")
    print(format_plain_text(digest))
    print()
    print("=== (HTML version also available via format_html(), not printed here) ===")
