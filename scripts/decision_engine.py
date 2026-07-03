"""
decision_engine.py  —  Stage 4: global ranked EV list + Kelly staking

Consumes data/predictions_current.json (produced by generate_predictions.py)
and emits data/betting_decisions.json — a globally-ranked list of bets
with Kelly-fractional stakes and exposure guardrails.

WHAT THIS MODULE DOES:
  1. Reads all positive-edge try-scorer entries across every fixture
     for the round, plus any positive h2h (winner) edges.
  2. Ranks them globally by EV = edge * our_probability (not by edge
     alone -- a 20% edge on a 10% probability has less EV than a 12%
     edge on a 40% probability).
  3. Applies quarter-Kelly staking: stake = (edge / (1/our_prob - 1)) * 0.25
     Quarter-Kelly is the standard conservative choice -- full Kelly
     is theoretically optimal but practically too aggressive for a
     model with one season of data and no calibration history yet.
     Stake is expressed as a fraction of the round's total bankroll
     unit (caller decides absolute dollar amounts; this module never
     sees them, by design -- same separation principle as edge_finder).
  4. Applies two guardrails:
     a. Minimum edge threshold: MINIMUM_EDGE = 0.05 (5%). Edges below
        this are noise, not signal, at our current sample size.
     b. Per-match exposure cap: no more than MAX_STAKE_PER_MATCH = 0.10
        (10% of bankroll) in combined Kelly stakes across bets in the
        same fixture. Stacks within a fixture are correlated -- the
        same game state affects all scorers on both sides -- so they
        get a shared budget, not independent sizing.
     c. Same-match winner+tryscorer correlation rule: if we're already
        staking on a team to win (positive h2h edge) and also staking
        on try-scorers from that team, the try-scorer stakes are
        reduced by CORRELATION_DISCOUNT = 0.50 (halved), since winning
        increases the expected number of scorers from that team --
        the bets are positively correlated, which reduces their
        diversification value relative to independent bets.
  5. Emits a full "NO +EV BETS FOUND" state when nothing clears the
     minimum edge threshold -- this is a real, meaningful outcome that
     the digest should surface, not an error to suppress.

WHAT THIS MODULE DOES NOT DO:
  - Does not fetch odds or produce probabilities. Those live in
    generate_predictions.py / edge_finder.py / odds_probability.py.
  - Does not compute CLV. That requires closing odds, which aren't
    captured yet (see score_predictions.py's prediction_time_ev_log).
  - Does not decide absolute dollar amounts. Fraction of bankroll only.
  - Does not open or close bets. Operator (Sam) reviews betting_decisions.json
    before acting. This is advisory, not autonomous.

CALIBRATION CAVEAT (honest, per the Stage 2 note in score_predictions.py):
  With zero scored rounds in the ledger (as of 2026-07-04), Kelly stakes
  are computed on uncalibrated model probabilities. Treat all stakes as
  illustrative until Stage 3 calibration has at least one full season
  of scored rounds to fit against (realistically mid-2027). The quarter-
  Kelly multiplier is an explicit acknowledgement of this uncertainty.

Usage (standalone):
    python3 scripts/decision_engine.py --data-dir data

Called by generate_predictions.py after predictions are written, so
betting_decisions.json is always in sync with predictions_current.json.
"""

import argparse
import json
import os
from datetime import datetime, timezone

# ============================================================
# CONSTANTS — change here, nowhere else
# ============================================================
MINIMUM_EDGE = 0.05          # edges below this are excluded
KELLY_FRACTION = 0.25        # quarter-Kelly
MAX_STAKE_PER_MATCH = 0.10   # combined bankroll fraction per fixture
CORRELATION_DISCOUNT = 0.50  # discount on same-fixture try-scorer stakes
                              # when a winner bet also exists for that team


def _kelly_fraction_stake(our_probability, market_probability):
    """
    Kelly criterion: f = edge / (b) where b = decimal_odds - 1 = 1/market_p - 1.
    Applied at KELLY_FRACTION (quarter-Kelly).
    Returns None if inputs are invalid (probability outside (0,1)).
    """
    if not (0 < our_probability < 1) or not (0 < market_probability < 1):
        return None
    b = (1.0 / market_probability) - 1.0
    if b <= 0:
        return None
    edge = our_probability - market_probability
    if edge <= 0:
        return None
    full_kelly = edge / b
    return round(full_kelly * KELLY_FRACTION, 5)


def _ev(our_probability, market_probability):
    """
    Expected value per unit staked.
    EV = (our_p * b) - (1 - our_p)  where b = 1/market_p - 1.
    Equivalent to edge / market_p when edge > 0.
    """
    if not (0 < our_probability < 1) or not (0 < market_probability < 1):
        return None
    b = (1.0 / market_probability) - 1.0
    return round(our_probability * b - (1 - our_probability), 5)


def build_decisions(predictions_path, manual_notes_path=None):
    """
    Reads predictions_current.json, applies the full decision pipeline,
    returns the betting_decisions dict.
    """
    with open(predictions_path) as f:
        raw = json.load(f)

    # predictions_current.json is written by write_predictions_json() as
    # {season, round, results:[...]}; archive has the same wrapper shape.
    if isinstance(raw, dict) and "results" in raw:
        season = raw.get("season")
        round_num = raw.get("round")
        predictions = raw["results"]
    else:
        predictions = raw
        season = predictions[0].get("season") if predictions else None
        round_num = predictions[0].get("round") if predictions else None

    # Load manual notes if present -- applied after model ranking.
    manual_notes = {}
    if manual_notes_path and os.path.exists(manual_notes_path):
        with open(manual_notes_path) as f:
            mn_raw = json.load(f)
            manual_notes = mn_raw.get("notes", mn_raw)


    # ── Step 1: collect all candidates above the minimum edge ──────────
    candidates = []

    # Track which teams have a positive h2h winner edge, for correlation discount
    teams_with_winner_edge = set()

    for fixture in predictions:
        home = fixture.get("home_team")
        away = fixture.get("away_team")
        if fixture.get("status") not in ("ok", None):
            continue

        h2h = fixture.get("h2h", {})
        h2h_edge = h2h.get("edge") or 0

        # h2h (winner) market
        if h2h_edge >= MINIMUM_EDGE:
            our_p = h2h.get("our_home_win_prob")
            mkt_p = h2h.get("market_home_win_prob")
            stake = _kelly_fraction_stake(our_p, mkt_p)
            ev = _ev(our_p, mkt_p)
            if stake and ev and our_p and mkt_p:
                predicted_winner = home if our_p > 0.5 else away
                teams_with_winner_edge.add(predicted_winner)
                candidates.append({
                    "market": "winner",
                    "fixture": f"{home} v {away}",
                    "home_team": home,
                    "away_team": away,
                    "description": f"{predicted_winner} to win",
                    "our_probability": round(our_p, 4),
                    "market_probability": round(mkt_p, 4),
                    "edge": round(h2h_edge, 4),
                    "ev_per_unit": ev,
                    "kelly_stake_fraction": stake,
                    "adjusted_stake_fraction": stake,  # may be modified by caps
                    "bookmaker": h2h.get("market_spread_bookmaker", "unknown"),
                    "manual_note": None,
                    "correlation_discounted": False,
                })

        # try-scorer market
        for edge_entry in fixture.get("try_scorer_edges", []):
            edge_val = edge_entry.get("edge") or 0
            if edge_val < MINIMUM_EDGE:
                continue
            our_p = edge_entry.get("our_probability")
            mkt_p = edge_entry.get("market_probability")
            stake = _kelly_fraction_stake(our_p, mkt_p)
            ev = _ev(our_p, mkt_p)
            if stake is None or ev is None:
                continue

            player = edge_entry.get("player_name")
            team = edge_entry.get("team")

            # Attach any manual note for this player this round
            note_key = f"{player}:{round_num}"
            note = (manual_notes.get(note_key) or {}).get("note")

            candidates.append({
                "market": "try_scorer",
                "fixture": f"{home} v {away}",
                "home_team": home,
                "away_team": away,
                "description": f"{player} anytime try scorer",
                "player_name": player,
                "team": team,
                "position_code": edge_entry.get("position_code"),
                "our_probability": round(our_p, 4),
                "market_probability": round(mkt_p, 4),
                "edge": round(edge_val, 4),
                "ev_per_unit": ev,
                "kelly_stake_fraction": stake,
                "adjusted_stake_fraction": stake,
                "bookmaker": edge_entry.get("bookmaker", "unknown"),
                "manual_note": note,
                "correlation_discounted": False,
            })

    # ── Step 1b: deduplicate multi-bookmaker try-scorer entries ────────
    # edge_finder.py produces one entry per (player, bookmaker) when
    # multiple books price the same player. Keep only the best-EV entry
    # per (player, fixture) so we don't accidentally triple-stake a
    # player just because three bookmakers priced them. Winner-market
    # entries are never duplicated (one h2h edge per fixture).
    seen_player_fixture = {}
    deduped = []
    for c in candidates:
        if c["market"] != "try_scorer":
            deduped.append(c); continue
        key = (c.get("player_name"), c["fixture"])
        if key not in seen_player_fixture:
            seen_player_fixture[key] = len(deduped)
            deduped.append(c)
        else:
            # Replace if this bookmaker has a better EV
            existing_idx = seen_player_fixture[key]
            if c["ev_per_unit"] > deduped[existing_idx]["ev_per_unit"]:
                deduped[existing_idx] = c
    candidates = deduped

    # ── Step 2: rank globally by EV descending ─────────────────────────
    candidates.sort(key=lambda c: c["ev_per_unit"], reverse=True)

    # ── Step 3: correlation discount ───────────────────────────────────
    # Try-scorer bets where the player's team also has a winner-edge bet
    # are positively correlated -- halve their stake.
    for c in candidates:
        if c["market"] == "try_scorer" and c.get("team") in teams_with_winner_edge:
            c["adjusted_stake_fraction"] = round(c["kelly_stake_fraction"] * CORRELATION_DISCOUNT, 5)
            c["correlation_discounted"] = True

    # ── Step 4: per-fixture exposure cap ──────────────────────────────
    # Accumulate adjusted stakes per fixture; reduce proportionally if
    # total exceeds MAX_STAKE_PER_MATCH. Process in EV order so we
    # preserve the highest-EV bets within each fixture's budget.
    fixture_stake_used = {}
    for c in candidates:
        fx = c["fixture"]
        used = fixture_stake_used.get(fx, 0.0)
        headroom = max(0.0, MAX_STAKE_PER_MATCH - used)
        if c["adjusted_stake_fraction"] > headroom:
            c["adjusted_stake_fraction"] = round(headroom, 5)
            c["capped_by_fixture_limit"] = True
        else:
            c["capped_by_fixture_limit"] = False
        fixture_stake_used[fx] = used + c["adjusted_stake_fraction"]

    # ── Step 5: filter out zero-stake entries (cap exhausted) ─────────
    actionable = [c for c in candidates if c["adjusted_stake_fraction"] > 0.001]
    excluded_by_cap = len(candidates) - len(actionable)

    # ── Step 6: assemble output ────────────────────────────────────────
    total_stake = round(sum(c["adjusted_stake_fraction"] for c in actionable), 4)

    no_bets = len(actionable) == 0

    return {
        "season": season,
        "round": round_num,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "parameters": {
            "minimum_edge": MINIMUM_EDGE,
            "kelly_fraction": KELLY_FRACTION,
            "max_stake_per_match": MAX_STAKE_PER_MATCH,
            "correlation_discount": CORRELATION_DISCOUNT,
        },
        "summary": {
            "status": "NO_POSITIVE_EV_BETS_FOUND" if no_bets else "ok",
            "total_bets": len(actionable),
            "total_stake_fraction": total_stake,
            "excluded_below_minimum_edge": len([c for c in candidates
                                                 if c not in actionable
                                                 and c["adjusted_stake_fraction"] <= 0.001
                                                 and c not in candidates[:len(actionable)]]),
            "excluded_by_fixture_cap": excluded_by_cap,
            "calibration_warning": (
                "Stakes are computed on uncalibrated model probabilities. "
                "Treat as illustrative until Stage 3 calibration has a full "
                "season of scored rounds (mid-2027 at earliest). Quarter-Kelly "
                "multiplier is an explicit hedge against this uncertainty."
            ),
        },
        "bets": actionable,
    }


def write_decisions(decisions, output_path):
    dirname = os.path.dirname(output_path)
    if dirname:
        os.makedirs(dirname, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(decisions, f, indent=2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stage 4 decision engine: ranked EV + Kelly stakes")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--output", default="data/betting_decisions.json")
    parser.add_argument("--manual-notes", default="data/manual_notes.json")
    args = parser.parse_args()

    predictions_path = os.path.join(args.data_dir, "predictions_current.json")
    decisions = build_decisions(predictions_path, args.manual_notes)

    write_decisions(decisions, args.output)

    s = decisions["summary"]
    print(f"Round {decisions['round']} ({decisions['season']}) decisions:")
    if s["status"] == "NO_POSITIVE_EV_BETS_FOUND":
        print("  NO +EV BETS FOUND this round.")
    else:
        print(f"  {s['total_bets']} bets, total stake: {s['total_stake_fraction']:.3f} units")
        print(f"  Top 5 by EV:")
        for b in decisions["bets"][:5]:
            note = f"  [NOTE: {b['manual_note']}]" if b.get("manual_note") else ""
            disc = " [corr-disc]" if b.get("correlation_discounted") else ""
            cap = " [cap-reduced]" if b.get("capped_by_fixture_limit") else ""
            print(f"    {b['description'][:40]:40s}  edge={b['edge']:+.3f}  "
                  f"ev={b['ev_per_unit']:+.4f}  stake={b['adjusted_stake_fraction']:.4f}"
                  f"{disc}{cap}{note}")
    print(f"Written: {args.output}")
    print(f"WARNING: {s['calibration_warning'][:80]}...")
