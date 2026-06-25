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
from send_round_digest import _describe_due_factors


RESEND_API_URL = "https://api.resend.com/emails"
SANDBOX_FROM = "NRL Bet Bot <onboarding@resend.dev>"


def build_predictions_digest(predictions_json_path, round_num, top_n_overall=10,
                              per_fixture_bookmaker="sportsbet",
                              n_most_likely=2, n_due=2, n_biggest_margin=3,
                              position_tpg_baseline_path=None):
    """
    Reads generate_predictions.py's real JSON output (the full nested
    per-fixture structure -- NOT the flat CSV, which can't represent
    these groupings cleanly) and builds a plain dict digest.

    REWRITTEN 2026-06-24 per Sam's real request for a richer per-game
    breakdown. Each fixture now gets FOUR real, Sportsbet-priced
    sections (consistent bookmaker throughout the per-game view, same
    real reasoning as the original per_fixture_edges design -- "best
    overall" at the end remains the place for cross-bookmaker shopping):
      1. Most likely to score (n_most_likely): top by OUR raw
         probability, not edge -- "who do we think is scoring" is a
         genuinely different question from "where's the value", and
         the spec asked for both as distinct sections.
      2. Due (n_due): real composite DUE WATCH score
         (due_flags_v2.py's existing, validated system -- drought,
         opponent matchup, team form, usage trend, structure share --
         wired into generate_predictions.py's JSON output 2026-06-24
         rather than re-implemented here). NOT the same signal as
         "most likely" -- a player can be a strong, in-form scorer
         (most likely) without being statistically overdue, and vice
         versa (due = currently cold relative to their OWN proven
         record, not necessarily the best absolute bet this week).
      3. Biggest margin (n_biggest_margin): top by real edge size
         (our probability vs Sportsbet's), deduplicated to one row per
         player (same real reasoning as best_overall_edges below --
         without dedup, one player's price would crowd out genuinely
         different opportunities).
      4. Golden Boy: a player appearing in ALL THREE of the above
         three real lists for this fixture. Genuinely rare by
         construction (three independently-computed signals --
         absolute probability, a five-factor composite cold/hot signal,
         and edge-vs-market -- agreeing on the same player is real
         convergent evidence, not guaranteed to ever fire most weeks).
         None if no overlap -- never forced.

    Plus a real templated one-paragraph analysis per fixture (see
    _build_fixture_analysis() below) -- built from the actual real
    numbers already computed (favourite, margin, agreement/
    disagreement with the market, the golden boy if any), NOT a
    separate LLM call -- Sam explicitly chose deterministic, no-extra-
    cost templating over generative summarisation (2026-06-24).

    Returns:
      {
        "round": ...,
        "fixtures_ok": [...],
        "fixtures_skipped": [...],
        "h2h_summaries": [...],
        "per_game": [
          {
            "home_team", "away_team", "bookmaker_used",
            "most_likely": [...], "due": [...], "biggest_margin": [...],
            "golden_boy": {...} or None,
            "analysis": "...",
          }, ...
        ],
        "best_overall_edges": [...],
      }

    REAL FLAG ADDED 2026-06-24 (per Sam's real feedback): "most likely
    to score" is pure probability ranking, with NO positional context
    -- this surfaced a genuine real case (Round 17: Dylan Lucas, a
    2RF/second-rower, ranked above every winger/centre/fullback in the
    fixture at 53.2%, confirmed via direct lookup to be a real, not
    buggy, number -- he's scoring at 2.88x the real league-average rate
    for his position this season, 7 tries/11 games vs a 0.221 weighted
    league baseline). Sam's real point: across the whole NRL, real
    try-scoring volume concentrates heavily in WG/FB/CE (confirmed via
    the real Phase 7 weighted baseline: WG 0.635, FB 0.419, CE 0.330
    TPG, vs every other position at 0.26 or below) -- a probability-
    only ranking can't distinguish "a real outside back having a
    normal week" from "a real but unusual outlier", and presenting
    both identically risks misleading a reader who (correctly) expects
    most picks to be outside backs.

    Fix: each most_likely entry now carries is_positionally_unusual
    (True if position_code not in {WG, FB, CE}) and, when true, a
    real comparison of the player's OWN rate to their position's real
    league average (e.g. "scoring at 2.9x the normal rate for a 2RF"),
    so the read is "this is real and earned, but rare for the
    position" rather than hiding the real number OR presenting it with
    no context. Sam explicitly chose to KEEP pure probability ranking
    (the model's job is to surface real outliers, not conform to
    position norms) while making the positional context visible.

    position_tpg_baseline_path: if None, this flag is skipped entirely
    (most_likely entries simply won't carry is_positionally_unusual) --
    explicit None rather than guessing a default path, since this
    function otherwise has no dependency on xtry_model.py's data
    layout and shouldn't assume one silently.
    """
    with open(predictions_json_path) as f:
        results = json.load(f)

    league_tpg_by_position = None
    if position_tpg_baseline_path:
        # Reuses the EXACT same real Phase 7 weighted-baseline logic
        # xtry_model.py's Component 1 already uses for league-average
        # TPG -- not a separately invented threshold. Import done here
        # (not at module top-level) so this module has no hard
        # dependency on recency_weighted_baselines.py when the caller
        # doesn't supply a path.
        from recency_weighted_baselines import build_weighted_tpg_baseline
        with open(position_tpg_baseline_path) as f:
            position_tpg_rows = list(csv.DictReader(f))
        league_tpg_by_position = build_weighted_tpg_baseline(position_tpg_rows)

    OUTSIDE_BACK_POSITIONS = {"WG", "FB", "CE"}
    # Real, evidence-based set -- confirmed 2026-06-24 against the real
    # Phase 7 weighted baseline that these three positions sit in a
    # clear top tier (0.33-0.64 TPG) with a sharp real drop to every
    # other position (0.26 or below). Not an arbitrary guess.

    fixtures_ok = []
    fixtures_skipped = []
    h2h_summaries = []
    per_game = []
    all_edges_for_overall = []
    all_position_changes = []
    # Real, round-wide collection of every position-resolution change
    # surfaced by generate_predictions.py's resolve_squad_positions()
    # -- added 2026-06-24 per Sam's explicit requirement that real
    # positional changes (a confirmed team-list position differing
    # from a player's historical-frequency baseline, OR a real team
    # list being entirely unavailable for a team) should visibly alert
    # him, not be silently absorbed into the model. Genuine "no
    # historical row, new to the list" and "no real team list at all
    # this round" cases are included here too, not filtered out --
    # this function doesn't decide what's "major enough" to read, it
    # surfaces everything real and lets the email layer decide how
    # prominently to show it.

    for fixture in results:
        home = fixture["home_team"]
        away = fixture["away_team"]
        status = fixture.get("status", "")

        if status != "ok":
            fixtures_skipped.append({"home_team": home, "away_team": away, "reason": status})
            continue

        fixtures_ok.append({"home_team": home, "away_team": away})
        h2h = fixture.get("h2h", {})

        for change in fixture.get("position_changes", []):
            all_position_changes.append({"home_team": home, "away_team": away, "change": change})

        # --- h2h: name the real favourite, separately for our model and the market ---
        h2h_summary = None
        if h2h.get("our_home_win_prob") is not None and h2h.get("market_home_win_prob") is not None:
            our_home_prob = h2h["our_home_win_prob"]
            market_home_prob = h2h["market_home_win_prob"]
            our_favourite = home if our_home_prob >= 0.5 else away
            our_favourite_prob = our_home_prob if our_home_prob >= 0.5 else 1 - our_home_prob
            market_favourite = home if market_home_prob >= 0.5 else away
            market_favourite_prob = market_home_prob if market_home_prob >= 0.5 else 1 - market_home_prob

            our_favourite_fair_odds = (
                h2h.get("our_home_fair_odds") if our_favourite == home else h2h.get("our_away_fair_odds")
            )

            rating_home = h2h.get("rating_home")
            rating_away = h2h.get("rating_away")
            rating_gap_for_favourite = None
            if rating_home is not None and rating_away is not None:
                gap = rating_home - rating_away
                rating_gap_for_favourite = gap if our_favourite == home else -gap

            h2h_summary = {
                "home_team": home,
                "away_team": away,
                "our_favourite": our_favourite,
                "our_favourite_prob": our_favourite_prob,
                "our_favourite_fair_odds": our_favourite_fair_odds,
                "market_favourite": market_favourite,
                "market_favourite_prob": market_favourite_prob,
                "agree": our_favourite == market_favourite,
                "our_margin": h2h.get("our_predicted_margin"),
                "margin_mae": h2h.get("margin_mae"),
                "spread_bookmaker": h2h.get("market_spread_bookmaker"),
                "spread_point": h2h.get("market_spread_point"),
                "spread_price": h2h.get("market_spread_price"),
                "rating_gap_for_favourite": rating_gap_for_favourite,
                "real_h2h_history": h2h.get("real_h2h_history"),
                "real_home_form": h2h.get("real_home_form"),
                "real_away_form": h2h.get("real_away_form"),
                # Positive = our_favourite has been the genuinely
                # stronger real team by Elo rating this season; small
                # or negative = our_favourite is winning on raw
                # probability/home advantage despite NOT being the
                # better-rated real team -- a real, fan-relevant
                # distinction _build_fixture_analysis() below uses to
                # decide whether to frame a pick as "the form team"
                # or "a true 50/50 that fell their way."
            }
            h2h_summaries.append(h2h_summary)

        # --- real try-scorer edges for this fixture, all bookmakers ---
        all_edges = fixture.get("try_scorer_edges", [])
        for e in all_edges:
            all_edges_for_overall.append({**e, "home_team": home, "away_team": away})

        if not all_edges:
            continue

        sportsbet_edges = [e for e in all_edges if e["bookmaker"] == per_fixture_bookmaker]
        if sportsbet_edges:
            bookmaker_used = per_fixture_bookmaker
        else:
            # Real fallback: preferred bookmaker has no coverage for
            # THIS fixture -- use whichever real bookmaker has the most
            # rows instead of silently showing nothing (same pattern as
            # the original per_fixture_edges design).
            by_bm = defaultdict(list)
            for e in all_edges:
                by_bm[e["bookmaker"]].append(e)
            bookmaker_used = max(by_bm, key=lambda b: len(by_bm[b]))
            sportsbet_edges = by_bm[bookmaker_used]

        # Dedup to one row per player at this bookmaker (a player only
        # has one real price per bookmaker anyway, but defensive against
        # any future upstream change that might duplicate rows).
        by_player_at_bookmaker = {}
        for e in sportsbet_edges:
            by_player_at_bookmaker[e["player_name"]] = e

        # 1. Most likely to score -- by OUR raw probability, not edge.
        most_likely_raw = sorted(
            by_player_at_bookmaker.values(), key=lambda e: -e["our_probability"]
        )[:n_most_likely]

        most_likely = []
        for e in most_likely_raw:
            entry = dict(e)
            is_unusual = e["position_code"] not in OUTSIDE_BACK_POSITIONS
            entry["is_positionally_unusual"] = is_unusual
            entry["position_rate_multiple"] = None
            if is_unusual and league_tpg_by_position and e.get("raw_season_tpg") is not None:
                league_avg = league_tpg_by_position.get(e["position_code"])
                if league_avg and league_avg > 0:
                    # Real comparison: this player's OWN real season TPG
                    # (already computed by xtry_model.py's Component 1)
                    # vs the real league-wide average for their
                    # position -- e.g. confirmed real case, Round 17:
                    # Dylan Lucas 0.636 TPG / 0.221 league 2RF average
                    # = 2.88x, a genuine real outlier, not a model quirk.
                    entry["position_rate_multiple"] = e["raw_season_tpg"] / league_avg
            most_likely.append(entry)

        # 2. Due -- real composite DUE WATCH score, both teams pooled
        # and re-sorted (the per-team top-2 already computed in
        # generate_predictions.py is exactly n_due*2 -- re-sort+slice
        # here in case n_due is ever configured differently than the
        # upstream default of 2-per-team).
        #
        # REAL FIX 2026-06-24, per Sam's real feedback: DUE WATCH's
        # composite score is 50% weighted on "drought" (due_flags_v2.py's
        # own real WEIGHTS dict) -- it's fundamentally a BACKWARD-looking
        # "this player has gone unusually cold relative to his own
        # record" signal, genuinely independent of xtry_model.py's
        # forward-looking scoring probability. The original version of
        # this section showed our_probability/fair_odds next to the DUE
        # score, which a real reader (correctly) read as "the model
        # thinks he'll probably score" -- but a real cold player (e.g.
        # confirmed real case: Jojo Fifita and Matt Burton, BOTH 0
        # tries across their real last 4 games) can be genuinely "due"
        # while ALSO having a genuinely low real probability this week
        # -- those are two different real questions, and showing one
        # number under a label that implies the other was actively
        # misleading, not a units bug. Fixed: drop probability/odds
        # from this section entirely (Sam's explicit choice), show only
        # the real DUE score plus WHY (reusing send_round_digest.py's
        # already-built _describe_due_factors(), not reinventing it --
        # same real reasoning the player-stats digest already shows).
        due_entries_raw = fixture.get("due_watch", {}).get("home", []) + fixture.get("due_watch", {}).get("away", [])
        due_entries_sorted = sorted(due_entries_raw, key=lambda d: -d["composite_score"])[:n_due]
        due = []
        for d in due_entries_sorted:
            reasons = _describe_due_factors(d)
            due.append({
                "player_name": d["player_name"],
                "team": d["team"],
                "position_code": d["position_code"],
                "composite_score": d["composite_score"],
                "reasons": reasons,
            })

        # 3. Biggest margin -- real edge size at this bookmaker, deduped by player.
        biggest_margin = sorted(
            by_player_at_bookmaker.values(), key=lambda e: -e["edge"]
        )[:n_biggest_margin]

        # --- Golden Boy: real intersection across all three lists ---
        most_likely_names = {e["player_name"] for e in most_likely}
        due_names = {d["player_name"] for d in due}
        margin_names = {e["player_name"] for e in biggest_margin}
        golden_boy_names = most_likely_names & due_names & margin_names
        golden_boy = None
        if golden_boy_names:
            gb_name = next(iter(golden_boy_names))
            gb_edge = by_player_at_bookmaker.get(gb_name)
            golden_boy = {
                "player_name": gb_name,
                "team": gb_edge["team"] if gb_edge else None,
                "our_probability": gb_edge["our_probability"] if gb_edge else None,
                "edge": gb_edge["edge"] if gb_edge else None,
                "fair_odds": gb_edge.get("fair_odds_implied_by_our_model") if gb_edge else None,
            }

        analysis = _build_fixture_analysis(h2h_summary, most_likely, due, biggest_margin, golden_boy, home, away, due_entries_sorted)

        per_game.append({
            "home_team": home,
            "away_team": away,
            "bookmaker_used": bookmaker_used,
            "most_likely": most_likely,
            "due": due,
            "biggest_margin": biggest_margin,
            "golden_boy": golden_boy,
            "analysis": analysis,
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
        "per_game": per_game,
        "best_overall_edges": best_overall_edges,
        "position_changes": all_position_changes,
    }


def _plain_language_due_reason(due_entry):
    """
    A genuinely jargon-free version of WHY a player is flagged due,
    for the fan-voiced narrative paragraph specifically -- added
    2026-06-24 per Sam's explicit request that the narrative itself
    use no statistical language at all. Reads the SAME real factors
    send_round_digest.py's _describe_due_factors() already surfaces
    (drought, opponent_matchup, team_form, usage_trend, structure_share)
    but without touching that shared function (still used as-is for
    the standalone "Due to score" list elsewhere in this email, and
    for generate_round_digest.py's separate weekly player-stats email)
    -- this is a real, separate, narrative-only translation of the
    same real underlying signal, not a replacement for it.

    due_entry here is the full real due_watch dict (player_name, team,
    position_code, composite_score, factors, recent_tpg, season_tpg,
    opponent_this_round) -- the SAME real shape _describe_due_factors()
    consumes, just rendered in plain words with no numbers.
    """
    factors = due_entry.get("factors", {})
    available = [(k, v) for k, v in factors.items() if v is not None]
    if not available:
        return "he's been a bit quiet lately"
    available.sort(key=lambda kv: abs(kv[1]), reverse=True)
    top_factor, top_value = available[0]

    plain_labels = {
        "drought": "he's been a bit quiet in front of the posts lately, despite a real track record of scoring",
        "opponent_matchup": "this week's opponent has been leaky in defence right where he plays",
        "team_form": "his team's attack has been clicking lately",
        "usage_trend": "he's getting more of the ball lately",
        "structure_share": "he's becoming a bigger part of how his team attacks",
    }
    return plain_labels.get(top_factor, "the numbers like him this week")


def _build_fixture_analysis(h2h_summary, most_likely, due, biggest_margin, golden_boy, home, away,
                             due_entries_with_factors=None):
    """
    REWRITTEN 2026-06-24 per Sam's explicit request: write this as a
    real fan would talk about the match -- name a winner, name a
    loser, give the real reason why, in plain language. No raw
    percentages, no "edge", "TPG", "composite score" or similar
    statistical jargon in the actual prose (those numbers are still
    real and still shown elsewhere in the email -- per-player lines,
    the h2h section -- this function's only job is the narrative
    paragraph, not a replacement for the data itself).

    REVISED AGAIN 2026-06-24 after real feedback that the narrative was
    "a bit basic" and "repeats itself" -- two real changes:

    1. TWO GENUINELY NEW REAL ANALYTICAL ANGLES, not just reworded
       versions of what was already there:
       - Real head-to-head history (get_real_head_to_head() in
         generate_predictions.py) -- "how have these two specific
         teams fared against EACH OTHER", independent of how either
         has played against everyone else (a different real question
         from the Elo rating gap).
       - Real recent form streak (get_real_form_streak()) -- "how has
         each team performed, period, lately" (raw win/loss, not
         adjusted for opponent strength the way Elo is) -- a real,
         different signal again.
       Both are real, checkable against match_data_FINAL_fixed.csv,
       not invented flavour.

    2. GENUINE PHRASING VARIETY: the same real branch (e.g. "close
       rating gap") previously always produced byte-identical prose
       across every fixture in a round -- confirmed real, repetitive
       result Sam flagged directly. Each branch below now has multiple
       real phrasings, chosen via a deterministic hash of the fixture
       name (NOT random -- the same round re-run produces the same
       real output, important for reproducibility/debugging, but
       different fixtures in the same round get different real
       wording). This is still fully templated/deterministic, not
       generative -- variety comes from picking among pre-written real
       sentences, not from an LLM call.

    Still deterministic and templated -- every claim is a direct
    translation of a real number already computed elsewhere.
    """
    if not h2h_summary:
        return f"No real prediction available for {home} v {away} this week."

    # Real, deterministic per-fixture variety seed -- same round
    # re-run gives identical real output (important for debugging/
    # reproducibility), but different fixtures in the same round
    # genuinely vary in phrasing. Not used for anything that changes
    # the actual real claims, only which pre-written real sentence
    # expresses an already-real fact.
    import hashlib
    seed = int(hashlib.md5(f"{home}{away}".encode()).hexdigest(), 16)

    def pick(options):
        return options[seed % len(options)]

    winner = h2h_summary["our_favourite"]
    loser = away if winner == home else home
    margin = h2h_summary.get("our_margin")
    rating_gap = h2h_summary.get("rating_gap_for_favourite")
    agree = h2h_summary["agree"]
    h2h_history = h2h_summary.get("real_h2h_history")
    home_form = h2h_summary.get("real_home_form")
    away_form = h2h_summary.get("real_away_form")
    winner_form = home_form if winner == home else away_form
    loser_form = away_form if winner == home else home_form

    parts = []

    # --- Real opening: name the winner and loser plainly ---
    if margin is not None:
        abs_margin = abs(margin)
        if abs_margin < 3:
            parts.append(pick([
                f"This one's a real coin-flip, but we're tipping {winner} to edge out {loser}.",
                f"Tight one to call, but we're leaning {winner} over {loser}.",
                f"Could go either way, honestly -- we'll take {winner} by the barest of margins over {loser}.",
            ]))
        elif abs_margin < 10:
            parts.append(pick([
                f"We've got {winner} getting the job done against {loser} in a real arm-wrestle.",
                f"{winner} should get there against {loser}, but don't expect it to be comfortable.",
                f"We're backing {winner} here, though {loser} should make a real fight of it.",
            ]))
        else:
            parts.append(pick([
                f"{winner} should have the measure of {loser} this week.",
                f"This one looks like a real statement game for {winner} against {loser}.",
                f"We don't see much in {loser}'s favour here -- {winner} should control this from the start.",
            ]))
    else:
        parts.append(f"We're tipping {winner} to beat {loser}.")

    # --- Real reason #1: team strength, in plain language ---
    if rating_gap is not None:
        if rating_gap > 100:
            parts.append(pick([
                f"{winner} have just been the better side all year, and it shows here.",
                f"There's a real gulf in class here -- {winner} have been operating on another level all season.",
                f"{winner} have been one of the genuine form sides of the competition, and {loser} simply haven't been at that level.",
            ]))
            if margin is not None and abs(margin) < 10 and winner == away:
                parts.append(pick([
                    f"The catch: {winner} are on the road for this one, which is enough to "
                    f"keep {loser} in the contest even though they're the clearly weaker side.",
                    f"That said, {winner} have to travel for this one, which closes the gap more than "
                    f"you'd expect given how one-sided this looks on paper.",
                ]))
        elif rating_gap > 30:
            parts.append(pick([
                f"{winner} have had the wood on most teams lately, and {loser} haven't been at that level.",
                f"{winner} go in as the form side here, a level above where {loser} have been sitting.",
            ]))
        elif rating_gap > -30:
            parts.append(pick([
                f"On raw ability there's not much between these two -- this is more about who turns "
                f"up on the day, and a few key real match-ups.",
                f"These two are genuinely evenly matched on the season's evidence -- this could come "
                f"down to who wants it more on the day.",
            ]))
        else:
            parts.append(pick([
                f"{loser} have actually had the better season on paper, but {winner} get the nod here "
                f"thanks to home advantage and a few real factors in their favour this week.",
                f"On paper {loser} are the better side this year, but we like {winner} to cause an upset here.",
            ]))

    # --- Real reason #1b: head-to-head history, a genuinely new angle ---
    if h2h_history and h2h_history["games_found"] >= 2:
        a_wins, b_wins = h2h_history["team_a_wins"], h2h_history["team_b_wins"]
        n = h2h_history["games_found"]
        recent = h2h_history["most_recent"]
        winner_h2h_wins = a_wins if home == winner else b_wins
        # team_a is always `home` in get_real_head_to_head's real
        # return shape -- confirmed via that function's own docstring.
        if h2h_history["team_a_wins" if winner == home else "team_b_wins"] >= n / 2 + 1:
            parts.append(pick([
                f"{winner} have had the better of this rivalry lately too, winning {winner_h2h_wins} of the last {n}.",
                f"History's on {winner}'s side here as well -- they've taken {winner_h2h_wins} of the last {n} between these two.",
            ]))
        elif recent and recent["winner"] == loser:
            parts.append(pick([
                f"Worth noting {loser} got the better of {winner} last time these two met ({recent['score']}), "
                f"so there's a bit of real history to settle here.",
                f"{loser} actually won the last meeting between these two ({recent['score']}) -- "
                f"{winner} will want to put that right.",
            ]))

    # --- Real reason #1c: recent form streak, another new real angle ---
    if winner_form and winner_form["games"] >= 3:
        if winner_form["wins"] >= winner_form["games"] - 1:
            parts.append(pick([
                f"{winner} are flying right now, having won {winner_form['wins']} of their last {winner_form['games']}.",
                f"{winner} are red-hot coming into this -- {winner_form['wins']} wins from their last {winner_form['games']}.",
            ]))
    if loser_form and loser_form["games"] >= 3 and loser_form["wins"] <= 1:
        parts.append(pick([
            f"{loser} have really struggled lately, with just {loser_form['wins']} win from their last {loser_form['games']}.",
            f"It's been a rough stretch for {loser} -- only {loser_form['wins']} win in their last {loser_form['games']}.",
        ]))

    # --- Real reason #2: the standout player driving the upset/edge ---
    if biggest_margin:
        top = biggest_margin[0]
        parts.append(pick([
            f"Keep an eye on {top['player_name']} -- the market's underrating him, and he could be "
            f"the difference if he gets on the scoresheet early.",
            f"{top['player_name']} looks like real value to us this week -- the market hasn't quite caught up.",
            f"If you're after one name, {top['player_name']} stands out as the bookies' price looks generous to us.",
        ]))

    # --- Real reason #3: a real outlier worth a fan's attention ---
    unusual = [e for e in most_likely if e.get("is_positionally_unusual")]
    if unusual:
        u = unusual[0]
        parts.append(pick([
            f"{u['player_name']} is in the mix to score too, which is a bit unusual for "
            f"his spot on the field, but he's been in real form lately.",
            f"Don't be surprised if {u['player_name']} gets among the tries either -- not the type of "
            f"player you'd expect to see scoring, but he's earned the right to be considered this week.",
        ]))

    # --- Real reason #4: market agreement/disagreement, in fan terms ---
    if not agree:
        parts.append(pick([
            f"The bookies actually see this one going the other way, so there's real value in backing {winner}.",
            f"We're going against the market here -- the bookies favour the other side, but we like {winner}.",
        ]))

    # --- Real reason #5: the due players, named plainly, no jargon ---
    if due_entries_with_factors:
        for d in due_entries_with_factors:
            plain_reason = _plain_language_due_reason(d)
            parts.append(pick([
                f"{d['player_name']} could be the one to watch -- {plain_reason}.",
                f"Don't overlook {d['player_name']} either -- {plain_reason}.",
            ]))
    elif due:
        for d in due:
            parts.append(f"{d['player_name']} could be the one to watch -- the numbers like him this week.")

    # --- Golden Boy, kept as a real, fun callout ---
    if golden_boy:
        parts.append(
            f"If you want one name to remember, make it {golden_boy['player_name']} -- "
            f"he ticks every box for us this week."
        )

    return " ".join(parts)


def _margin_text(s):
    """
    Shared between format_plain_text and format_html so the real
    sign-conversion logic (our_margin is home-minus-away; the real
    bookmaker spread point is the home team's own line) lives in one
    place, not duplicated and at risk of drifting out of sync between
    the two renderers. Includes real $ odds for both our number and
    the market's, added 2026-06-24 per Sam's request.
    """
    text = ""
    if s.get("our_favourite_fair_odds") is not None:
        text += f" (our odds ${s['our_favourite_fair_odds']})"
    if s.get("market_favourite") and s.get("market_favourite_prob") is not None:
        # Real market fair odds for the market's own favourite, derived
        # from the SAME consensus probability already shown -- not a
        # new number, just expressed as decimal odds too.
        market_fair_odds = round(1 / s["market_favourite_prob"], 3) if s["market_favourite_prob"] > 0 else None
        if market_fair_odds:
            text += f" (market odds ${market_fair_odds})"

    if s["our_margin"] is None:
        return text
    margin_for_favourite = abs(s["our_margin"])
    mae_note = f" (real avg error +/-{s['margin_mae']:.0f}pts)" if s["margin_mae"] else ""
    text += f". We predict {s['our_favourite']} by {margin_for_favourite:.1f}pts{mae_note}"
    if s["spread_bookmaker"] and s["spread_point"] is not None:
        market_margin_for_home = -s["spread_point"]
        market_margin_favourite = s["home_team"] if market_margin_for_home > 0 else s["away_team"]
        price_note = f" at ${s['spread_price']}" if s.get("spread_price") else ""
        text += (
            f", {s['spread_bookmaker']} has {market_margin_favourite} "
            f"by {abs(market_margin_for_home):.1f}pts{price_note}"
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

    if digest["per_game"]:
        lines.append("PER-GAME BREAKDOWN")
        for g in digest["per_game"]:
            lines.append("")
            lines.append(f"  {g['home_team']} v {g['away_team']}  (odds via {g['bookmaker_used']})")
            lines.append(f"  {g['analysis']}")

            if g["most_likely"]:
                lines.append("  Most likely to score:")
                for e in g["most_likely"]:
                    gb_tag = " [GOLDEN BOY]" if g["golden_boy"] and e["player_name"] == g["golden_boy"]["player_name"] else ""
                    rarity_note = ""
                    if e.get("is_positionally_unusual"):
                        if e.get("position_rate_multiple"):
                            rarity_note = (
                                f" [rare for a {e['position_code']} -- scoring at "
                                f"{e['position_rate_multiple']:.1f}x the normal rate for the position]"
                            )
                        else:
                            rarity_note = f" [rare for a {e['position_code']}]"
                    lines.append(
                        f"    - {e['player_name']} ({e['team']}): our {e['our_probability']*100:.1f}% "
                        f"(our odds ${e['fair_odds_implied_by_our_model']}, market odds "
                        f"${round(1/e['market_probability'], 3) if e['market_probability'] else '?'})"
                        f"{rarity_note}{gb_tag}"
                    )

            if g["due"]:
                lines.append("  Due to score:")
                for d in g["due"]:
                    gb_tag = " [GOLDEN BOY]" if g["golden_boy"] and d["player_name"] == g["golden_boy"]["player_name"] else ""
                    reasons_note = "; ".join(d["reasons"]) if d.get("reasons") else "no real factors available"
                    lines.append(
                        f"    - {d['player_name']} ({d['team']}): DUE score {d['composite_score']:+.2f} "
                        f"-- {reasons_note}{gb_tag}"
                    )

            if g["biggest_margin"]:
                lines.append("  Biggest margin (our model vs market):")
                for e in g["biggest_margin"]:
                    gb_tag = " [GOLDEN BOY]" if g["golden_boy"] and e["player_name"] == g["golden_boy"]["player_name"] else ""
                    lines.append(
                        f"    - {e['player_name']} ({e['team']}): our {e['our_probability']*100:.1f}% "
                        f"vs market {e['market_probability']*100:.1f}% "
                        f"(edge {e['edge']*100:+.1f}pp, our odds ${e['fair_odds_implied_by_our_model']})"
                        f"{gb_tag}"
                    )
        lines.append("")

    if digest["best_overall_edges"]:
        lines.append("BEST BETS OVERALL (best real price across any bookmaker)")
        for e in digest["best_overall_edges"]:
            lines.append(
                f"  - {e['player_name']} ({e['team']}, {e['home_team']} v {e['away_team']}) "
                f"via {e['bookmaker']}: our {e['our_probability']*100:.1f}% vs market "
                f"{e['market_probability']*100:.1f}% (edge {e['edge']*100:+.1f}pp, "
                f"our odds ${e['fair_odds_implied_by_our_model']})"
            )
        lines.append("")

    if digest["fixtures_skipped"]:
        lines.append("SKIPPED FIXTURES (no real odds available)")
        for f in digest["fixtures_skipped"]:
            lines.append(f"  - {f['home_team']} v {f['away_team']}: {f['reason']}")
        lines.append("")

    # Moved to the very bottom per Sam's explicit request (2026-06-24).
    # Only ever shown if there's a genuine real positional swap to
    # report -- the "no real team list at all" infrastructure case is
    # now log-only (see resolve_squad_positions()'s docstring), never
    # surfaced here, so this section produces NOTHING at all (not even
    # a header) in the normal case where nothing real changed.
    if digest.get("position_changes"):
        lines.append("⚠ POSITION CHANGES THIS WEEK (real team-list updates vs historical baseline)")
        for c in digest["position_changes"]:
            lines.append(f"  - [{c['home_team']} v {c['away_team']}] {c['change']}")
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

    if digest["per_game"]:
        body += "<h3>Per-Game Breakdown</h3>"
        for g in digest["per_game"]:
            gb_name = g["golden_boy"]["player_name"] if g["golden_boy"] else None

            def gb_tag(name):
                return " <b>[GOLDEN BOY]</b>" if name == gb_name else ""

            body += f"<p><b>{g['home_team']} v {g['away_team']}</b> (odds via {g['bookmaker_used']})</p>"
            body += f"<p><i>{g['analysis']}</i></p>"

            if g["most_likely"]:
                body += "<p>Most likely to score:</p><ul>"
                for e in g["most_likely"]:
                    market_odds = round(1 / e["market_probability"], 3) if e["market_probability"] else "?"
                    rarity_note = ""
                    if e.get("is_positionally_unusual"):
                        if e.get("position_rate_multiple"):
                            rarity_note = (
                                f" <i>(rare for a {e['position_code']} -- scoring at "
                                f"{e['position_rate_multiple']:.1f}x the normal rate for the position)</i>"
                            )
                        else:
                            rarity_note = f" <i>(rare for a {e['position_code']})</i>"
                    body += (
                        f"<li>{e['player_name']} ({e['team']}): our {e['our_probability']*100:.1f}% "
                        f"(our odds ${e['fair_odds_implied_by_our_model']}, market odds ${market_odds})"
                        f"{rarity_note}{gb_tag(e['player_name'])}</li>"
                    )
                body += "</ul>"

            if g["due"]:
                body += "<p>Due to score:</p><ul>"
                for d in g["due"]:
                    reasons_note = "; ".join(d["reasons"]) if d.get("reasons") else "no real factors available"
                    body += (
                        f"<li>{d['player_name']} ({d['team']}): DUE score {d['composite_score']:+.2f} "
                        f"&mdash; {reasons_note}{gb_tag(d['player_name'])}</li>"
                    )
                body += "</ul>"

            if g["biggest_margin"]:
                body += "<p>Biggest margin (our model vs market):</p><ul>"
                for e in g["biggest_margin"]:
                    body += (
                        f"<li>{e['player_name']} ({e['team']}): our {e['our_probability']*100:.1f}% "
                        f"vs market {e['market_probability']*100:.1f}% "
                        f"(edge {e['edge']*100:+.1f}pp, our odds ${e['fair_odds_implied_by_our_model']})"
                        f"{gb_tag(e['player_name'])}</li>"
                    )
                body += "</ul>"

    body += section(
        "Best Bets Overall",
        digest["best_overall_edges"],
        lambda e: (
            f"<b>{e['player_name']}</b> ({e['team']}, {e['home_team']} v {e['away_team']}) "
            f"via {e['bookmaker']}: our {e['our_probability']*100:.1f}% vs market "
            f"{e['market_probability']*100:.1f}% (edge {e['edge']*100:+.1f}pp, "
            f"our odds ${e['fair_odds_implied_by_our_model']})"
        ),
    )
    body += section(
        "Skipped Fixtures",
        digest["fixtures_skipped"],
        lambda f: f"{f['home_team']} v {f['away_team']}: {f['reason']}",
    )

    # Moved to the very bottom per Sam's explicit request (2026-06-24).
    # Only ever shown if there's a genuine real positional swap to
    # report -- the "no real team list at all" infrastructure case is
    # now log-only (see resolve_squad_positions()'s docstring), never
    # surfaced here, so this section renders NOTHING at all (not even
    # a header) in the normal case where nothing real changed.
    if digest.get("position_changes"):
        body += (
            '<h3 style="color:#b45309;">&#9888; Position Changes This Week '
            "(real team-list updates vs historical baseline)</h3><ul>"
        )
        for c in digest["position_changes"]:
            body += f"<li><b>[{c['home_team']} v {c['away_team']}]</b> {c['change']}</li>"
        body += "</ul>"

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
    # pattern as send_round_digest.py's own __main__ block. Reads the
    # JSON output (not CSV) -- see build_predictions_digest's docstring
    # for why the per-game groupings need the richer nested structure.
    digest = build_predictions_digest(
        "data/predictions_current.json", round_num=17,
        position_tpg_baseline_path="data/historical_position_tpg_baseline.csv",
    )
    print("=== PLAIN TEXT VERSION ===")
    print(format_plain_text(digest))
    print()
    print("=== (HTML version also available via format_html(), not printed here) ===")
