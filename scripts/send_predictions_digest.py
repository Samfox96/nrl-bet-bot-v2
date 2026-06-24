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


def build_predictions_digest(predictions_csv_path, round_num, top_n_overall=10,
                              per_fixture_bookmaker="sportsbet", per_fixture_top_n=3):
    """
    Reads generate_predictions.py's real CSV output and builds a plain
    dict digest, mirroring generate_round_digest.py's build_digest()
    shape/spirit (a plain dict of named sections, no formatting logic
    mixed in here -- that's format_plain_text()/format_html()'s job
    below, same separation as the existing digest module).

    REVISED 2026-06-24 after real feedback on the first genuinely live
    email (Round 17): the original h2h section forced the reader to
    compare two raw percentages themselves to figure out who's actually
    favoured -- fixed by naming the real favourite explicitly (by our
    model, separately by the market, since they can disagree -- e.g.
    real Round 17 Knights v Wests Tigers: our model favours the Knights,
    market favours them MORE strongly, so "favourite" agrees but
    "edge direction" doesn't -- collapsing this to one favourite would
    have hidden that distinction).

    The original try-scorer section was also a single flat top-10
    across the WHOLE round, which in practice (confirmed via the real
    Round 17 email) gets dominated by one or two players' prices shopped
    across every bookmaker (Kurtis Morrin alone took 6 of 10 slots) --
    not genuinely 10 different real opportunities. Replaced with two
    real sections instead:
      1. Per-fixture, top `per_fixture_top_n` edges via ONE bookmaker
         (`per_fixture_bookmaker`, default sportsbet) -- gives genuine
         coverage across every real fixture rather than one match's
         hottest player crowding out the rest. Falls back to whichever
         bookmaker actually has the most try-scorer coverage for a given
         real fixture if the preferred one has none (confirmed real
         case to guard against: coverage varies by bookmaker and
         fixture, not guaranteed present every week) -- never silently
         shows an empty section for a fixture that has real data
         elsewhere.
      2. A real "best overall" section: the single best REAL price
         across ALL bookmakers per player (not one row per bookmaker --
         deduplicated to the best fair_odds/edge for that player), top
         `top_n_overall` by edge. This answers "if I could bet anywhere,
         what's the single best real opportunity," distinct from
         section 1's "what does Sportsbet specifically offer me per
         game."

    Returns:
      {
        "round": ...,
        "fixtures_ok": [...],
        "fixtures_skipped": [...],
        "h2h_summaries": [...],     # named-favourite real h2h comparisons
        "per_fixture_edges": [...], # list of {fixture, bookmaker_used, edges: [...]}
        "best_overall_edges": [...],# deduplicated-by-player, best real price
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
    h2h_summaries = []
    per_fixture_edges = []
    all_edges_for_overall = []

    for (home, away), data in fixtures.items():
        status = data["status"]
        if "skipped" in status:
            fixtures_skipped.append({"home_team": home, "away_team": away, "reason": status})
            continue

        fixtures_ok.append({"home_team": home, "away_team": away})
        first_row = data["rows"][0]

        # --- h2h: name the real favourite, separately for our model and the market ---
        if first_row.get("our_home_win_prob") and first_row.get("market_home_win_prob"):
            try:
                our_home_prob = float(first_row["our_home_win_prob"])
                market_home_prob = float(first_row["market_home_win_prob"])
                our_favourite = home if our_home_prob >= 0.5 else away
                our_favourite_prob = our_home_prob if our_home_prob >= 0.5 else 1 - our_home_prob
                market_favourite = home if market_home_prob >= 0.5 else away
                market_favourite_prob = market_home_prob if market_home_prob >= 0.5 else 1 - market_home_prob

                our_margin = float(first_row["our_predicted_margin"]) if first_row.get("our_predicted_margin") else None
                margin_mae = float(first_row["margin_mae"]) if first_row.get("margin_mae") else None
                spread_bookmaker = first_row.get("market_spread_bookmaker") or None
                spread_point = float(first_row["market_spread_point"]) if first_row.get("market_spread_point") else None

                h2h_summaries.append({
                    "home_team": home,
                    "away_team": away,
                    "our_favourite": our_favourite,
                    "our_favourite_prob": our_favourite_prob,
                    "market_favourite": market_favourite,
                    "market_favourite_prob": market_favourite_prob,
                    "agree": our_favourite == market_favourite,
                    "our_margin": our_margin,
                    "margin_mae": margin_mae,
                    "spread_bookmaker": spread_bookmaker,
                    "spread_point": spread_point,
                })
            except (ValueError, TypeError):
                pass

        # --- try-scorer: real per-fixture rows, grouped by bookmaker ---
        fixture_edges_by_bookmaker = defaultdict(list)
        for r in data["rows"]:
            if r.get("player_name") and r.get("try_scorer_edge"):
                try:
                    edge_row = {
                        "player_name": r["player_name"],
                        "team": r["player_team"],
                        "bookmaker": r["bookmaker"],
                        "our_probability": float(r["our_try_probability"]),
                        "market_probability": float(r["market_try_probability"]),
                        "edge": float(r["try_scorer_edge"]),
                        "fair_odds": r.get("fair_odds"),
                        "home_team": home,
                        "away_team": away,
                    }
                    fixture_edges_by_bookmaker[r["bookmaker"]].append(edge_row)
                    all_edges_for_overall.append(edge_row)
                except (ValueError, TypeError):
                    continue

        if fixture_edges_by_bookmaker:
            if per_fixture_bookmaker in fixture_edges_by_bookmaker:
                bookmaker_used = per_fixture_bookmaker
            else:
                # Real fallback: preferred bookmaker has no try-scorer
                # coverage for THIS fixture -- use whichever real
                # bookmaker has the most rows instead of showing nothing.
                bookmaker_used = max(fixture_edges_by_bookmaker, key=lambda b: len(fixture_edges_by_bookmaker[b]))
            fixture_rows = sorted(
                fixture_edges_by_bookmaker[bookmaker_used], key=lambda e: -e["edge"]
            )[:per_fixture_top_n]
            per_fixture_edges.append({
                "home_team": home,
                "away_team": away,
                "bookmaker_used": bookmaker_used,
                "edges": fixture_rows,
            })

    # Real "best overall" -- one row per PLAYER (not per player-bookmaker
    # pair), keeping only their single best real edge across all books.
    best_by_player = {}
    for e in all_edges_for_overall:
        key = (e["player_name"], e["home_team"], e["away_team"])
        if key not in best_by_player or e["edge"] > best_by_player[key]["edge"]:
            best_by_player[key] = e
    best_overall_edges = sorted(best_by_player.values(), key=lambda e: -e["edge"])[:top_n_overall]

    return {
        "round": round_num,
        "fixtures_ok": fixtures_ok,
        "fixtures_skipped": fixtures_skipped,
        "h2h_summaries": h2h_summaries,
        "per_fixture_edges": per_fixture_edges,
        "best_overall_edges": best_overall_edges,
    }


def _margin_text(s):
    """
    Shared between format_plain_text and format_html so the real
    sign-conversion logic (our_margin is home-minus-away; the real
    bookmaker spread point is the home team's own line) lives in one
    place, not duplicated and at risk of drifting out of sync between
    the two renderers.
    """
    if s["our_margin"] is None:
        return ""
    margin_for_favourite = abs(s["our_margin"])
    mae_note = f" (real avg error +/-{s['margin_mae']:.0f}pts)" if s["margin_mae"] else ""
    text = f". We predict {s['our_favourite']} by {margin_for_favourite:.1f}pts{mae_note}"
    if s["spread_bookmaker"] and s["spread_point"] is not None:
        market_margin_for_home = -s["spread_point"]
        market_margin_favourite = s["home_team"] if market_margin_for_home > 0 else s["away_team"]
        text += (
            f", {s['spread_bookmaker']} has {market_margin_favourite} "
            f"by {abs(market_margin_for_home):.1f}pts"
        )
    return text


def format_plain_text(digest):
    lines = []
    lines.append(f"NRL Bet Bot — Round {digest['round']} Predictions")
    lines.append(f"({len(digest['fixtures_ok'])} fixtures processed, "
                 f"{len(digest['fixtures_skipped'])} skipped)")
    lines.append("")

    if digest["h2h_summaries"]:
        lines.append("MATCH WIN PROBABILITY")
        for s in digest["h2h_summaries"]:
            agree_note = "" if s["agree"] else " -- our model DISAGREES with the market on who wins"
            lines.append(
                f"  - {s['home_team']} v {s['away_team']}: "
                f"we favour {s['our_favourite']} ({s['our_favourite_prob']*100:.0f}%), "
                f"market favours {s['market_favourite']} ({s['market_favourite_prob']*100:.0f}%)"
                f"{agree_note}{_margin_text(s)}"
            )
        lines.append("")

    if digest["per_fixture_edges"]:
        lines.append(f"TOP TRY-SCORER PICKS PER GAME (top {len(digest['per_fixture_edges'][0]['edges'])} each)")
        for fx in digest["per_fixture_edges"]:
            lines.append(f"  {fx['home_team']} v {fx['away_team']}  (via {fx['bookmaker_used']})")
            for e in fx["edges"]:
                lines.append(
                    f"    - {e['player_name']} ({e['team']}): our {e['our_probability']*100:.1f}% "
                    f"vs market {e['market_probability']*100:.1f}% "
                    f"(edge {e['edge']*100:+.1f}pp, fair odds {e['fair_odds']})"
                )
        lines.append("")

    if digest["best_overall_edges"]:
        lines.append("BEST BETS OVERALL (best real price across any bookmaker)")
        for e in digest["best_overall_edges"]:
            lines.append(
                f"  - {e['player_name']} ({e['team']}, {e['home_team']} v {e['away_team']}) "
                f"via {e['bookmaker']}: our {e['our_probability']*100:.1f}% vs market "
                f"{e['market_probability']*100:.1f}% (edge {e['edge']*100:+.1f}pp, "
                f"fair odds {e['fair_odds']})"
            )
        lines.append("")

    if digest["fixtures_skipped"]:
        lines.append("SKIPPED FIXTURES (no real odds available)")
        for f in digest["fixtures_skipped"]:
            lines.append(f"  - {f['home_team']} v {f['away_team']}: {f['reason']}")
        lines.append("")

    if not digest["h2h_summaries"] and not digest["best_overall_edges"]:
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
        digest["h2h_summaries"],
        lambda s: (
            f"<b>{s['home_team']} v {s['away_team']}</b>: we favour "
            f"<b>{s['our_favourite']}</b> ({s['our_favourite_prob']*100:.0f}%), "
            f"market favours <b>{s['market_favourite']}</b> ({s['market_favourite_prob']*100:.0f}%)"
            + ("" if s["agree"] else " &mdash; <i>we disagree with the market on who wins</i>")
            + _margin_text(s)
        ),
    )

    if digest["per_fixture_edges"]:
        body += "<h3>Top Try-Scorer Picks Per Game</h3>"
        for fx in digest["per_fixture_edges"]:
            body += f"<p><b>{fx['home_team']} v {fx['away_team']}</b> (via {fx['bookmaker_used']})</p><ul>"
            for e in fx["edges"]:
                body += (
                    f"<li>{e['player_name']} ({e['team']}): our {e['our_probability']*100:.1f}% "
                    f"vs market {e['market_probability']*100:.1f}% "
                    f"(edge {e['edge']*100:+.1f}pp, fair odds {e['fair_odds']})</li>"
                )
            body += "</ul>"

    body += section(
        "Best Bets Overall",
        digest["best_overall_edges"],
        lambda e: (
            f"<b>{e['player_name']}</b> ({e['team']}, {e['home_team']} v {e['away_team']}) "
            f"via {e['bookmaker']}: our {e['our_probability']*100:.1f}% vs market "
            f"{e['market_probability']*100:.1f}% (edge {e['edge']*100:+.1f}pp, fair odds {e['fair_odds']})"
        ),
    )
    body += section(
        "Skipped Fixtures",
        digest["fixtures_skipped"],
        lambda f: f"{f['home_team']} v {f['away_team']}: {f['reason']}",
    )

    if not digest["h2h_summaries"] and not digest["best_overall_edges"]:
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
