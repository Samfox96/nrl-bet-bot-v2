"""
send_predictions_digest.py

Formats generate_predictions.py's real CSV output into a plain-text +
HTML email and sends it via Resend's API. Built 2026-06-24 specifically
because generate-predictions.yml's email step was written referencing
this module before it existed -- caught immediately rather than shipped
as a phantom dependency (see this session's own real lesson about citing
things by name that turn out not to be committed anywhere; doing that
again, even with an honest comment explaining the gap, would repeat the
exact mistake rather than learn from it).

DESIGN: deliberately reuses send_round_digest.py's real, already-proven
mechanics rather than reimplementing them --
  - Same Resend sandbox sender, same RESEND_API_KEY/DIGEST_TO_EMAIL
    secrets already wired into weekly-update.yml (no new secrets).
  - Same User-Agent header fix (confirmed real and necessary against
    Resend's Cloudflare edge, 2026-06-23) -- copied here rather than
    importing send_round_digest.send_digest_email() directly, since
    that function hardcodes a "Round X Digest" subject line specific
    to the player-stats digest; this module needs its own subject/
    content shape for predictions specifically. The actual Resend
    POST mechanics (URL, headers, error handling) are identical and
    kept identical on purpose -- if Resend's API or the User-Agent
    requirement ever changes, both modules need the same fix applied.

WHAT THIS DOES NOT DO (explicit, not an oversight):
  - Does not re-run any model -- reads ONLY from
    data/predictions_current.csv, the file generate_predictions.py
    already wrote. This module's job is formatting and sending, same
    separation of concerns as generate_round_digest.py (builds content)
    vs send_round_digest.py (sends it).
  - Does not include spreads/totals (not in the CSV -- see
    generate_predictions.py's own docstring for why those markets
    aren't generated yet).
"""

import csv
import json
import os
import urllib.request
import urllib.error
from collections import defaultdict


RESEND_API_URL = "https://api.resend.com/emails"
SANDBOX_FROM = "NRL Bet Bot <onboarding@resend.dev>"


def build_predictions_digest(predictions_csv_path, round_num, top_n_edges=10):
    """
    Reads generate_predictions.py's real CSV output and builds a plain
    dict digest, mirroring generate_round_digest.py's build_digest()
    shape/spirit (a plain dict of named sections, no formatting logic
    mixed in here -- that's format_plain_text()/format_html()'s job
    below, same separation as the existing digest module).

    Returns:
      {
        "round": ...,
        "fixtures_ok": [...],       # real fixtures that processed cleanly
        "fixtures_skipped": [...],  # real fixtures skipped, with reasons
        "top_h2h_edges": [...],     # fixtures where our Elo model and
                                     # the real market disagree most
        "top_try_scorer_edges": [...],  # biggest real player-prop edges
                                          # across ALL fixtures combined
      }
    """
    with open(predictions_csv_path) as f:
        rows = list(csv.DictReader(f))

    fixtures = defaultdict(lambda: {"rows": [], "status": None})
    for r in rows:
        key = (r["home_team"], r["away_team"])
        fixtures[key]["rows"].append(r)
        fixtures[key]["status"] = r["status"]

    fixtures_ok = []
    fixtures_skipped = []
    h2h_edges = []
    try_scorer_edges = []

    for (home, away), data in fixtures.items():
        status = data["status"]
        if "skipped" in status:
            fixtures_skipped.append({"home_team": home, "away_team": away, "reason": status})
            continue

        fixtures_ok.append({"home_team": home, "away_team": away})

        first_row = data["rows"][0]
        if first_row.get("h2h_edge"):
            try:
                h2h_edges.append({
                    "home_team": home,
                    "away_team": away,
                    "our_home_win_prob": float(first_row["our_home_win_prob"]),
                    "market_home_win_prob": float(first_row["market_home_win_prob"]),
                    "edge": float(first_row["h2h_edge"]),
                })
            except (ValueError, TypeError):
                pass

        for r in data["rows"]:
            if r.get("player_name") and r.get("try_scorer_edge"):
                try:
                    try_scorer_edges.append({
                        "player_name": r["player_name"],
                        "team": r["player_team"],
                        "bookmaker": r["bookmaker"],
                        "our_probability": float(r["our_try_probability"]),
                        "market_probability": float(r["market_try_probability"]),
                        "edge": float(r["try_scorer_edge"]),
                        "fair_odds": r.get("fair_odds"),
                    })
                except (ValueError, TypeError):
                    continue

    h2h_edges.sort(key=lambda e: abs(e["edge"]), reverse=True)
    try_scorer_edges.sort(key=lambda e: e["edge"], reverse=True)

    return {
        "round": round_num,
        "fixtures_ok": fixtures_ok,
        "fixtures_skipped": fixtures_skipped,
        "top_h2h_edges": h2h_edges,
        "top_try_scorer_edges": try_scorer_edges[:top_n_edges],
    }


def format_plain_text(digest):
    lines = []
    lines.append(f"NRL Bet Bot — Round {digest['round']} Predictions")
    lines.append(f"({len(digest['fixtures_ok'])} fixtures processed, "
                 f"{len(digest['fixtures_skipped'])} skipped)")
    lines.append("")

    if digest["top_h2h_edges"]:
        lines.append("MATCH WIN PROBABILITY (our model vs real market consensus)")
        for e in digest["top_h2h_edges"]:
            direction = "favours" if e["edge"] > 0 else "against"
            lines.append(
                f"  - {e['home_team']} v {e['away_team']}: our model {e['our_home_win_prob']*100:.0f}% "
                f"home win vs market {e['market_home_win_prob']*100:.0f}% "
                f"({direction} the home side by {abs(e['edge'])*100:.1f}pp)"
            )
        lines.append("")

    if digest["top_try_scorer_edges"]:
        lines.append(f"TOP TRY-SCORER EDGES (our model vs real bookmaker odds, biggest disagreement first)")
        for e in digest["top_try_scorer_edges"]:
            lines.append(
                f"  - {e['player_name']} ({e['team']}) via {e['bookmaker']}: "
                f"our {e['our_probability']*100:.1f}% vs market {e['market_probability']*100:.1f}% "
                f"(edge {e['edge']*100:+.1f}pp, fair odds {e['fair_odds']})"
            )
        lines.append("")

    if digest["fixtures_skipped"]:
        lines.append("SKIPPED FIXTURES (no real odds available)")
        for f in digest["fixtures_skipped"]:
            lines.append(f"  - {f['home_team']} v {f['away_team']}: {f['reason']}")
        lines.append("")

    if not digest["top_h2h_edges"] and not digest["top_try_scorer_edges"]:
        lines.append("No real edges surfaced this round.")

    return "\n".join(lines)


def format_html(digest):
    def section(title, items, render_item):
        if not items:
            return ""
        rendered = "".join(f"<li>{render_item(i)}</li>" for i in items)
        return f"<h3>{title}</h3><ul>{rendered}</ul>"

    body = f"<h2>NRL Bet Bot — Round {digest['round']} Predictions</h2>"
    body += (f"<p>{len(digest['fixtures_ok'])} fixtures processed, "
             f"{len(digest['fixtures_skipped'])} skipped.</p>")

    body += section(
        "Match Win Probability",
        digest["top_h2h_edges"],
        lambda e: (
            f"<b>{e['home_team']} v {e['away_team']}</b>: our model "
            f"{e['our_home_win_prob']*100:.0f}% vs market {e['market_home_win_prob']*100:.0f}% "
            f"({'favours' if e['edge'] > 0 else 'against'} home by {abs(e['edge'])*100:.1f}pp)"
        ),
    )
    body += section(
        "Top Try-Scorer Edges",
        digest["top_try_scorer_edges"],
        lambda e: (
            f"<b>{e['player_name']}</b> ({e['team']}) via {e['bookmaker']}: "
            f"our {e['our_probability']*100:.1f}% vs market {e['market_probability']*100:.1f}% "
            f"(edge {e['edge']*100:+.1f}pp, fair odds {e['fair_odds']})"
        ),
    )
    body += section(
        "Skipped Fixtures",
        digest["fixtures_skipped"],
        lambda f: f"{f['home_team']} v {f['away_team']}: {f['reason']}",
    )

    if not digest["top_h2h_edges"] and not digest["top_try_scorer_edges"]:
        body += "<p>No real edges surfaced this round.</p>"

    return body


def send_predictions_email(digest, to_email, api_key=None):
    """
    Sends the predictions digest via Resend's API. Same real mechanics
    as send_round_digest.py's send_digest_email() -- identical User-
    Agent fix, identical error handling (raises on any non-2xx, never
    silently swallows a failed send).
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
        "subject": f"NRL Bet Bot — Round {digest['round']} Predictions",
        "text": format_plain_text(digest),
        "html": format_html(digest),
    }

    req = urllib.request.Request(
        RESEND_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            # Same real fix as send_round_digest.py -- Resend's edge
            # (Cloudflare) returns HTTP 403 / error code 1010 without
            # this, confirmed 2026-06-23. Kept identical between both
            # modules deliberately.
            "User-Agent": "nrl-bet-bot-v2/1.0 (+https://github.com/Samfox96/nrl-bet-bot-v2)",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        raise RuntimeError(f"Resend API error {e.code}: {error_body}") from e


if __name__ == "__main__":
    # Dry-run: prints the formatted email content without sending, same
    # pattern as send_round_digest.py's own __main__ block.
    digest = build_predictions_digest("data/predictions_current.csv", round_num=17)
    print("=== PLAIN TEXT VERSION ===")
    print(format_plain_text(digest))
    print()
    print("=== (HTML version also available via format_html(), not printed here) ===")
