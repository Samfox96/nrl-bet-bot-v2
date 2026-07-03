import time
import os
import argparse
import pandas as pd
import traceback
import warnings
from parse_try_minutes import parse_try_minutes, aggregate_try_minutes, validate_try_minutes
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# ============================================================
# SETTINGS
# ============================================================
# Phase 3 update: round number and output path are now CLI arguments so this
# script can run unattended in GitHub Actions. Local manual use still works
# exactly as before -- if no args are passed, it falls back to DEFAULT_ROUND,
# same as the original single-round workflow.
DEFAULT_ROUND = 16  # fallback only used if --round is not passed

parser = argparse.ArgumentParser(description="Scrape a single NRL round's player stats.")
parser.add_argument("--round", type=int, default=None,
                     help="Round number to scrape. If omitted, falls back to DEFAULT_ROUND for local manual runs.")
parser.add_argument("--output", type=str, default=None,
                     help="Output CSV path. If omitted, defaults to nrl_round_<N>_new.csv in the current directory.")
parser.add_argument("--headless", action="store_true",
                     help="Run Chrome headless. Automatically enabled when running in GitHub Actions (CI=true).")
args = parser.parse_args()

SEASON = 2026
ROUND_TO_SCRAPE = args.round if args.round is not None else DEFAULT_ROUND
ROUNDS_TO_SCRAPE = range(ROUND_TO_SCRAPE, ROUND_TO_SCRAPE + 1)
EXISTING_CSV = None  # single-round mode: don't merge into nrl_master.csv automatically
OUTPUT_CSV = args.output if args.output else f"nrl_round_{ROUND_TO_SCRAPE}_new.csv"

# Run headless automatically in CI (GitHub Actions sets CI=true), or if explicitly requested
RUN_HEADLESS = args.headless or os.environ.get("CI", "").lower() == "true"

print(f"Scraping round {ROUND_TO_SCRAPE}, output -> {OUTPUT_CSV}, headless={RUN_HEADLESS}")

BASE = "https://www.nrl.com/draw/nrl-premiership/2026"
# REAL FIX 2026-07-03, per a full project audit: FALLBACK_URLS used to be
# a hand-maintained dict of every match URL for every round, requiring a
# manual edit each new round -- confirmed real production failure when
# Round 17 was missing (scraper crashed outright, no data captured, a
# GitHub Issue was auto-opened for manual review). It also caused a
# separate real bug previously (an erroneous "dolphins-v-rabbitohs"
# Round 13 fixture that could never have existed, since Dolphins,
# Rabbitohs, AND Titans all had a bye that round -- since removed).
#
# Retired entirely rather than patched round-by-round: this script
# already has a proven, working dynamic-discovery path below (visits
# nrl.com's round-level draw page and finds match links via Selenium)
# that was originally only a fallback for rounds missing from this
# dict. Confirmed live via a real Round 17 Actions run (2026-07-03):
# it correctly found and scraped all 8 real Round 17 matches with zero
# hardcoded URLs. Since that path already works and needs no manual
# maintenance, keeping a hand-maintained list alongside it added
# recurring maintenance burden and a recurring failure mode for zero
# real benefit -- removed per the project's own standing principle:
# never hardcode what can be derived. match_urls now always starts
# empty, so every round goes through the dynamic-discovery path below.

OUTPUT_COLUMNS = [
    "player_name", "team", "opponent", "round", "season",
    "position", "mins_played",
    "tries", "try_minutes", "points",
    "all_runs", "all_run_metres", "post_contact_metres", "kick_return_metres",
    "line_breaks", "line_break_assists", "try_assists", "line_engaged_runs",
    "tackle_breaks", "hit_ups", "play_the_ball", "average_play_the_ball_speed",
    "dummy_half_runs", "dummy_half_run_metres",
    "offloads", "passes", "receipts", "passes_to_run_ratio",
    "tackle_efficiency", "tackles_made", "missed_tackles",
    "intercepts", "kicks_defused",
    "kicks", "kicking_metres", "forced_drop_outs", "bomb_kicks", "grubbers",
    "errors", "handling_errors", "penalties",
    "ruck_infringements", "inside_10_metres",
    "sin_bins", "send_offs",
    "stint_one", "stint_two"
]

HEADER_MAP = {
    "player": "player_name", "number": "number", "position": "position",
    "mins_played": "mins_played", "points": "points", "tries": "tries",
    "conversions": "conversions", "conversion_attempts": "conversion_attempts",
    "penalty_goals": "penalty_goals", "goal_conversion_rate": "goal_conversion_rate",
    "1_point_field_goals": "field_goals_1pt", "2_point_field_goals": "field_goals_2pt",
    "total_points": "total_points", "all_runs": "all_runs",
    "all_run_metres": "all_run_metres", "kick_return_metres": "kick_return_metres",
    "post_contact_metres": "post_contact_metres", "line_breaks": "line_breaks",
    "line_break_assists": "line_break_assists", "try_assists": "try_assists",
    "line_engaged_runs": "line_engaged_runs", "tackle_breaks": "tackle_breaks",
    "hit_ups": "hit_ups", "play_the_ball": "play_the_ball",
    "average_play_the_ball_speed": "average_play_the_ball_speed",
    "dummy_half_runs": "dummy_half_runs", "dummy_half_run_metres": "dummy_half_run_metres",
    "one_on_one_steal": "one_on_one_steal", "offloads": "offloads",
    "dummy_passes": "dummy_passes", "passes": "passes", "receipts": "receipts",
    "passes_to_run_ratio": "passes_to_run_ratio", "tackle_efficiency": "tackle_efficiency",
    "tackles_made": "tackles_made", "missed_tackles": "missed_tackles",
    "ineffective_tackles": "ineffective_tackles", "intercepts": "intercepts",
    "kicks_defused": "kicks_defused", "kicks": "kicks",
    "kicking_metres": "kicking_metres", "forced_drop_outs": "forced_drop_outs",
    "bomb_kicks": "bomb_kicks", "grubbers": "grubbers", "40_20": "kick_40_20",
    "20_40": "kick_20_40", "cross_field_kicks": "cross_field_kicks",
    "kicked_dead": "kicked_dead", "errors": "errors",
    "handling_errors": "handling_errors", "one_on_one_lost": "one_on_one_lost",
    "penalties": "penalties", "ruck_infringements": "ruck_infringements",
    "inside_10_metres": "inside_10_metres", "on_report": "on_report",
    "sin_bins": "sin_bins", "send_offs": "send_offs",
    "stint_one": "stint_one", "stint_two": "stint_two",
}


def clean_dataframe(df):
    print("\nCleaning data...")
    warnings.filterwarnings("ignore")
    skip_cols = [
        "player_name", "team", "opponent", "position",
        "stint_one", "stint_two", "average_play_the_ball_speed",
        "passes_to_run_ratio", "tackle_efficiency", "mins_played",
        "try_minutes",  # e.g. "5;8" -- must not be coerced to numeric
    ]
    for col in df.columns:
        if col not in skip_cols:
            df[col] = df[col].replace("-", 0).replace("", 0)
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
    for col in ["tackle_efficiency", "passes_to_run_ratio"]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.replace("%", "", regex=False).str.strip()
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["round"] = pd.to_numeric(df["round"], errors="coerce").fillna(0).astype(int)
    df["season"] = pd.to_numeric(df["season"], errors="coerce").fillna(0).astype(int)
    print(f"Cleaning done. {len(df)} rows total.")
    return df


options = webdriver.ChromeOptions()
if RUN_HEADLESS:
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    # A realistic user-agent reduces (does not eliminate) the chance of being
    # served a different/degraded page than a real browser would see.
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
wait = WebDriverWait(driver, 15)


def dismiss_cookie_banner(driver):
    """
    Best-effort dismissal of a cookie/consent banner. A first-run headless
    profile (as every GitHub Actions run is) has never accepted cookies before,
    unlike a real browser profile that has -- this is the most likely reason a
    page would render differently (or appear to hang waiting on an overlay)
    in CI versus on a local machine.

    Tries a handful of common selector patterns. Failure to find/click a
    banner is not an error -- many pages won't have one, especially on repeat
    visits within the same browser session.
    """
    selectors = [
        "//button[contains(translate(text(), 'ACEPT', 'acept'), 'accept')]",
        "//button[contains(translate(text(), 'ACEPT', 'acept'), 'agree')]",
        "//button[@id='onetrust-accept-btn-handler']",
        "//button[contains(@class, 'cookie') and contains(@class, 'accept')]",
    ]
    for sel in selectors:
        try:
            btn = driver.find_element(By.XPATH, sel)
            driver.execute_script("arguments[0].click();", btn)
            time.sleep(1)
            return True
        except Exception:
            continue
    return False


def save_failure_screenshot(driver, label):
    """
    Saves a screenshot for debugging when something unexpected happens.
    In CI these land in the workflow's working directory; the Actions workflow
    should upload them as an artifact so they're inspectable after the run
    (headless runs have no other way to "see" what the browser saw).
    """
    try:
        os.makedirs("debug_screenshots", exist_ok=True)
        path = f"debug_screenshots/{label}_{int(time.time())}.png"
        driver.save_screenshot(path)
        print(f"    Saved debug screenshot: {path}")
    except Exception as e:
        print(f"    Could not save debug screenshot: {e}")
new_rows = []


def get_player_name(cell):
    try:
        link = cell.find_element(By.TAG_NAME, "a")
        name = link.text.strip()
        if name:
            return " ".join(name.split())
        name = driver.execute_script("return arguments[0].textContent;", link).strip()
        if name:
            return " ".join(name.split())
        name = link.get_attribute("aria-label") or link.get_attribute("title") or ""
        return " ".join(name.strip().split())
    except Exception:
        try:
            return driver.execute_script("return arguments[0].textContent;", cell).strip()
        except Exception:
            return ""


def extract_table(table_el, team_name, opponent_name, round_num):
    rows_out = []
    try:
        header_rows = table_el.find_elements(By.CSS_SELECTOR, "thead tr")
        if len(header_rows) < 2:
            return []
        header_els = header_rows[-1].find_elements(By.CSS_SELECTOR, "th")
        raw_headers = [
            h.text.strip().lower().replace(" ", "_").replace("/", "_")
            for h in header_els
        ]
        if len([h for h in raw_headers if h]) < 5:
            return []
        mapped_headers = [HEADER_MAP.get(h, h) for h in raw_headers]
        for row in table_el.find_elements(By.CSS_SELECTOR, "tbody tr"):
            cells = row.find_elements(By.TAG_NAME, "td")
            if len(cells) < 3:
                continue
            player_name = get_player_name(cells[1]) or get_player_name(cells[0])
            if not player_name or player_name == "-":
                continue
            cell_values = [c.text.strip() for c in cells]
            row_dict = {h: cell_values[i] if i < len(cell_values) else "" for i, h in enumerate(mapped_headers)}
            rows_out.append({
                "player_name": player_name, "team": team_name, "opponent": opponent_name,
                "round": round_num, "season": SEASON,
                "position": row_dict.get("position", ""),
                "mins_played": row_dict.get("mins_played", ""),
                "tries": row_dict.get("tries", ""),
                "try_minutes": "",  # filled in later from the Tries summary box, see merge_try_minutes_into_rows()
                "points": row_dict.get("points", ""),
                "all_runs": row_dict.get("all_runs", ""),
                "all_run_metres": row_dict.get("all_run_metres", ""),
                "post_contact_metres": row_dict.get("post_contact_metres", ""),
                "kick_return_metres": row_dict.get("kick_return_metres", ""),
                "line_breaks": row_dict.get("line_breaks", ""),
                "line_break_assists": row_dict.get("line_break_assists", ""),
                "try_assists": row_dict.get("try_assists", ""),
                "line_engaged_runs": row_dict.get("line_engaged_runs", ""),
                "tackle_breaks": row_dict.get("tackle_breaks", ""),
                "hit_ups": row_dict.get("hit_ups", ""),
                "play_the_ball": row_dict.get("play_the_ball", ""),
                "average_play_the_ball_speed": row_dict.get("average_play_the_ball_speed", ""),
                "dummy_half_runs": row_dict.get("dummy_half_runs", ""),
                "dummy_half_run_metres": row_dict.get("dummy_half_run_metres", ""),
                "offloads": row_dict.get("offloads", ""),
                "passes": row_dict.get("passes", ""),
                "receipts": row_dict.get("receipts", ""),
                "passes_to_run_ratio": row_dict.get("passes_to_run_ratio", ""),
                "tackle_efficiency": row_dict.get("tackle_efficiency", ""),
                "tackles_made": row_dict.get("tackles_made", ""),
                "missed_tackles": row_dict.get("missed_tackles", ""),
                "intercepts": row_dict.get("intercepts", ""),
                "kicks_defused": row_dict.get("kicks_defused", ""),
                "kicks": row_dict.get("kicks", ""),
                "kicking_metres": row_dict.get("kicking_metres", ""),
                "forced_drop_outs": row_dict.get("forced_drop_outs", ""),
                "bomb_kicks": row_dict.get("bomb_kicks", ""),
                "grubbers": row_dict.get("grubbers", ""),
                "errors": row_dict.get("errors", ""),
                "handling_errors": row_dict.get("handling_errors", ""),
                "penalties": row_dict.get("penalties", ""),
                "ruck_infringements": row_dict.get("ruck_infringements", ""),
                "inside_10_metres": row_dict.get("inside_10_metres", ""),
                "sin_bins": row_dict.get("sin_bins", ""),
                "send_offs": row_dict.get("send_offs", ""),
                "stint_one": row_dict.get("stint_one", ""),
                "stint_two": row_dict.get("stint_two", ""),
            })
    except Exception as e:
        print(f"      Error: {e}")
        traceback.print_exc()
    return rows_out


def merge_try_minutes_into_rows(rows, try_minutes_agg):
    """
    Fills in the try_minutes field on each player row using the aggregated
    (player_name, team_canonical) -> "5;8" dict produced by
    aggregate_try_minutes() in parse_try_minutes.py.

    Matching is by exact player_name string match within this match's rows
    only (rows is already scoped to one team's table at the point this is
    called from the main loop) -- team_canonical isn't used to filter here
    since rows are already team-scoped, but mismatches are still possible if
    the Tries box name and Player Stats table name differ in formatting
    (e.g. a nickname). This is a known, real risk -- see
    parse_try_minutes.py's module docstring -- and is NOT silently swallowed:
    any player with tries > 0 but no try_minutes match after this merge
    should be caught by the validate_try_minutes() cross-check before
    merging into nrl_master.csv, not assumed fine just because this
    function ran without an exception.
    """
    for row in rows:
        for (player_name, team_canonical), minute_str in try_minutes_agg.items():
            if row["player_name"] == player_name:
                row["try_minutes"] = minute_str
                break
    return rows


def extract_kickoff_times(driver, round_num):
    """
    Extracts each match's AEST kickoff time from the round-level draw
    page's real match markup (the same page driver is already on when
    this is called, right after match-URL discovery -- see call site).

    Returns a list of dicts: {round, home_team, away_team, kickoff_aest}.
    Best-effort -- if this fails, callers should treat it as "kickoff times
    unavailable this run," NOT as a reason to abort the whole scrape, since
    match-URL discovery (the more critical path) doesn't depend on this.

    REAL BUG FOUND AND FIXED 2026-07-03, via a real live Actions log
    (Round 17's first genuine run through this code path -- it had never
    actually executed live before): this function's body was written
    against parse_draw_link_text.py's ORIGINAL interface
    (`parse_draw_link(label)`, parsing Selenium element aria-label text).
    That module was rewritten 2026-06-22 -- the same day this function
    was added -- to a completely different, more robust interface:
    `extract_kickoffs_from_html(page_html)`, which parses the page's raw
    HTML via BeautifulSoup instead. This caller was never updated after
    that rewrite. Confirmed real consequence: `ImportError: cannot
    import name 'parse_draw_link' from 'parse_draw_link_text'` --
    and because that import sat OUTSIDE this function's own try/except,
    it crashed the ENTIRE round-17 scrape rather than degrading
    gracefully, directly contradicting this function's own documented
    "best-effort, non-fatal" intent. Both fixed together: the call now
    matches parse_draw_link_text.py's actual, current, self-tested
    interface (page_html via driver.page_source, taken while driver is
    still on the draw page from the call site), and the import is moved
    inside the try block so ANY future failure here -- import, parsing,
    whatever -- degrades to "kickoff times unavailable this run" exactly
    as originally documented, instead of taking down the whole scrape.
    """
    try:
        from parse_draw_link_text import extract_kickoffs_from_html
        page_html = driver.page_source
        results = extract_kickoffs_from_html(page_html)
        # Defensive filter: extract_kickoffs_from_html returns every match
        # div it finds on the page, keyed by the round number embedded in
        # each match's own URL -- normally all of them belong to round_num
        # since this is a round-specific draw page, but filtering here
        # costs nothing and guards against a future page-structure change
        # silently mixing in matches from an adjacent round.
        return [r for r in results if r["round"] == round_num]
    except Exception as e:
        print(f"  Could not extract kickoff times (non-fatal): {e}")
        return []


def click_team_tab(driver, team_name, is_away=False):
    """
    Click the team tab by matching button text on the page.
    The NRL site shows team name buttons like 'Knights' and 'Cowboys'.
    Falls back to index-based clicking if text match fails.
    """
    # Strategy 1: exact text match anywhere on page
    try:
        btn = driver.find_element(
            By.XPATH, f"//button[normalize-space(text())='{team_name}']"
        )
        driver.execute_script("arguments[0].click();", btn)
        time.sleep(2.5)
        print(f"      Clicked tab by name: {team_name}")
        return True
    except Exception:
        pass

    # Strategy 2: partial text match
    try:
        btn = driver.find_element(
            By.XPATH, f"//button[contains(text(),'{team_name}')]"
        )
        driver.execute_script("arguments[0].click();", btn)
        time.sleep(2.5)
        print(f"      Clicked tab (partial match): {team_name}")
        return True
    except Exception:
        pass

    # Strategy 3: find all buttons with visible text, print them, click by index
    try:
        all_btns = driver.find_elements(
            By.XPATH, "//button[string-length(normalize-space(text())) > 2]"
        )
        btn_texts = [b.text.strip() for b in all_btns]
        print(f"      Visible buttons on page: {btn_texts[:10]}")

        # Try to find matching button in the list
        for btn in all_btns:
            if team_name.lower() in btn.text.strip().lower():
                driver.execute_script("arguments[0].click();", btn)
                time.sleep(2.5)
                print(f"      Clicked tab (list search): {btn.text.strip()}")
                return True

        # Absolute fallback: 0=home, 1=away by index
        if len(all_btns) >= 2:
            btn_index = 1 if is_away else 0
            driver.execute_script("arguments[0].click();", all_btns[btn_index])
            time.sleep(2.5)
            print(f"      Clicked tab (index fallback {btn_index})")
            return True

    except Exception as e:
        print(f"      click_team_tab failed entirely: {e}")

    return False


# ============================================================
# MAIN SCRAPE LOOP
# ============================================================
try:
    for round_num in ROUNDS_TO_SCRAPE:
        print(f"\n=== Round {round_num} ===")

        match_urls = []  # always discovered dynamically now -- see comment above (FALLBACK_URLS retired)

        if not match_urls:
            draw_url = f"https://www.nrl.com/draw/?competition=111&round={round_num}&season={SEASON}"
            try:
                driver.set_page_load_timeout(30)  # fail fast instead of hanging for the default ~120s
                driver.get(draw_url)
            except Exception as e:
                print(f"  Page load timed out or failed for {draw_url}: {e}")
                continue

            dismiss_cookie_banner(driver)
            time.sleep(3)

            # Detect nrl.com's own "not published yet" state before trying to find match links.
            # Seen verbatim on the site for rounds whose draw hasn't been published/dated yet.
            page_text = ""
            try:
                page_text = driver.find_element(By.TAG_NAME, "body").text
            except Exception:
                pass

            if "couldn't load that draw" in page_text.lower() or "no data available" in page_text.lower():
                print(f"  Round {round_num} draw is not yet available on nrl.com "
                      f"(page reports no data for this round). Skipping -- try again closer to game day.")
                continue

            try:
                link_els = driver.find_elements(By.XPATH, "//a[contains(@href, '/draw/nrl-premiership/')]")
                match_urls = list(set([
                    el.get_attribute("href").split("#")[0].rstrip("/")
                    for el in link_els
                    if el.get_attribute("href") and "/round-" in el.get_attribute("href")
                ]))
            except Exception as e:
                print(f"  Could not find match links: {e}")
                save_failure_screenshot(driver, f"round{round_num}_no_match_links")
                continue

            # Best-effort: also capture kickoff times from this same page visit,
            # so Job B (team-list polling) can know exactly when to check without
            # a second browser session. Written as a sidecar file next to the
            # main output -- failure here never blocks the main stats scrape.
            kickoffs = extract_kickoff_times(driver, round_num)
            if kickoffs:
                import json
                kickoff_path = os.path.join(os.path.dirname(OUTPUT_CSV) or ".",
                                             f"round_{round_num}_kickoffs.json")
                try:
                    with open(kickoff_path, "w") as f:
                        json.dump(
                            [{**k, "kickoff_aest": k["kickoff_aest"].isoformat()} for k in kickoffs],
                            f, indent=2
                        )
                    print(f"  Saved {len(kickoffs)} kickoff times to {kickoff_path}")
                except Exception as e:
                    print(f"  Could not save kickoff times sidecar file (non-fatal): {e}")

            if not match_urls:
                print(f"  No match links found for round {round_num} even though the page loaded. "
                      f"The draw page structure may have changed, or this round genuinely has no "
                      f"fixtures published yet.")
                continue

        print(f"  Scraping {len(match_urls)} matches")

        for match_url in match_urls:
            print(f"\n  Visiting: {match_url}")
            try:
                driver.set_page_load_timeout(30)
                driver.get(match_url)
                dismiss_cookie_banner(driver)
                time.sleep(4)

                try:
                    slug = match_url.split("/")[-1]
                    parts = slug.split("-v-")
                    home_slug = parts[0].replace("-", " ").title() if parts else "Home"
                    away_slug = parts[1].replace("-", " ").title() if len(parts) > 1 else "Away"
                except Exception:
                    home_slug, away_slug = "Home", "Away"

                home_team, away_team = home_slug, away_slug
                try:
                    team_els = driver.find_elements(By.CSS_SELECTOR, ".match-header__team-name")
                    if len(team_els) >= 2:
                        home_team = team_els[0].text.strip()
                        away_team = team_els[1].text.strip()
                except Exception:
                    pass
                print(f"    {home_team} vs {away_team}")

                # ── TRY MINUTES (Phase 4) ────────────────────────────────────────
                # Captured here, BEFORE clicking into Player Stats, because the
                # Tries summary box renders on the page's default/initial view
                # (it sits above the News & Video / Play by Play / Team Lists /
                # Team Stats / Player Stats tab row -- confirmed via real DevTools
                # capture, Round 16, 2026-06-23). Best-effort: failure here must
                # never block the main player-stats scrape, since that's the more
                # critical data path.
                try:
                    match_page_html = driver.page_source
                    # REAL BUG FOUND AND FIXED 2026-07-03, via a real live
                    # Actions log: this passed the bare filename
                    # "team_aliases.json", but weekly-update.yml runs this
                    # script from the repo root (git checkout puts
                    # everything there), where the real file only exists
                    # at data/team_aliases.json. Confirmed real
                    # consequence: every single match in the Round 17 run
                    # logged "Could not parse try minutes (non-fatal):
                    # [Errno 2] No such file or directory:
                    # 'team_aliases.json'" -- caught only because the
                    # surrounding try/except correctly treated it as
                    # non-fatal (per this block's own design), not because
                    # the path was right. try_minutes silently never
                    # populated as a result. Checked parse_try_minutes.py's
                    # own __main__ self-test block for the same bare
                    # filename -- that one is a deliberate, documented
                    # local-testing convention (files kept alongside the
                    # script for ad-hoc runs) and is NOT a live production
                    # code path, so left untouched. This call site is the
                    # only real production caller and is the one that
                    # actually broke.
                    parsed_tries = parse_try_minutes(match_page_html, team_aliases_path="data/team_aliases.json")
                    try_minutes_agg = aggregate_try_minutes(parsed_tries)
                    if try_minutes_agg:
                        print(f"    Parsed {len(parsed_tries)} try entries from Tries summary box")
                    else:
                        print(f"    No Tries summary box entries found (0-0 first half, or page structure differs)")
                except Exception as e:
                    print(f"    Could not parse try minutes (non-fatal): {e}")
                    try_minutes_agg = {}

                # Click Player Stats tab
                try:
                    tab = wait.until(EC.element_to_be_clickable((
                        By.XPATH, "//a[.//span[contains(text(),'Player Stats')]]"
                    )))
                    driver.execute_script("arguments[0].click();", tab)
                    time.sleep(3)
                except Exception as e:
                    print(f"    Could not click Player Stats tab: {e}")
                    save_failure_screenshot(driver, f"round{round_num}_no_stats_tab")
                    continue

                # Wait for table
                try:
                    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div#player-stats table")))
                except Exception as e:
                    print(f"    No table found: {e}")
                    continue

                # ── HOME TEAM ─────────────────────────────────────────────────────
                print(f"    Clicking home tab: {home_team}")
                click_team_tab(driver, home_team, is_away=False)

                home_rows = []
                tables = driver.find_elements(By.CSS_SELECTOR, "div#player-stats table")
                print(f"    Found {len(tables)} tables")
                for table in tables:
                    rows = extract_table(table, home_team, away_team, round_num)
                    if rows:
                        home_rows = rows
                        break
                home_rows = merge_try_minutes_into_rows(home_rows, try_minutes_agg)
                new_rows.extend(home_rows)
                print(f"    Got {len(home_rows)} home rows for {home_team}")

                # ── AWAY TEAM ─────────────────────────────────────────────────────
                print(f"    Clicking away tab: {away_team}")
                clicked = click_team_tab(driver, away_team, is_away=True)
                if not clicked:
                    print(f"    WARNING: Could not click away tab — SKIPPING {away_team}")
                    continue

                away_rows = []
                tables = driver.find_elements(By.CSS_SELECTOR, "div#player-stats table")
                for table in tables:
                    rows = extract_table(table, away_team, home_team, round_num)
                    if rows:
                        away_rows = rows
                        break
                away_rows = merge_try_minutes_into_rows(away_rows, try_minutes_agg)

                # Dedup guard
                if away_rows and home_rows:
                    home_players = {r["player_name"] for r in home_rows}
                    away_players = {r["player_name"] for r in away_rows}
                    overlap_pct = len(home_players & away_players) / max(len(home_players), 1)
                    if overlap_pct > 0.5:
                        print(f"    WARNING: Away data is duplicate ({overlap_pct:.0%} overlap) — DISCARDING")
                        away_rows = []
                    else:
                        new_rows.extend(away_rows)
                        print(f"    Got {len(away_rows)} away rows for {away_team}")
                elif away_rows:
                    new_rows.extend(away_rows)
                    print(f"    Got {len(away_rows)} away rows for {away_team}")
                else:
                    print(f"    No away rows captured for {away_team}")

                # ── TRY MINUTES VALIDATION (Phase 4) ─────────────────────────────
                # Cross-checks parsed try_minutes counts against this match's own
                # `tries` column, per the validation gap flagged in STATUS.md
                # ("no validation cross-check against the existing tries column
                # count exists yet"). Never silently trusts a clean-looking parse.
                # A failure here is logged loudly but does NOT abort the scrape --
                # the underlying player-stats data (tries, points, etc.) is still
                # good even if try_minutes attribution has an issue this match.
                try:
                    this_match_rows = [r for r in (home_rows + away_rows) if r.get("tries")]
                    if this_match_rows and try_minutes_agg:
                        validation = validate_try_minutes(parsed_tries, this_match_rows)
                        if validation["ok"]:
                            print(f"    Try-minute validation: OK ({len(parsed_tries)} tries matched)")
                        else:
                            print(f"    Try-minute validation: MISMATCH — review needed")
                            if validation["mismatches"]:
                                print(f"      Count mismatches: {validation['mismatches']}")
                            if validation["unmatched_team_names"]:
                                print(f"      Unresolved team names: {validation['unmatched_team_names']}")
                            if validation["unparsed_entries"]:
                                print(f"      Unparsed li entries (unexpected minute format?): {validation['unparsed_entries']}")
                except Exception as e:
                    print(f"    Try-minute validation failed to run (non-fatal): {e}")

            except Exception as e:
                print(f"    Error processing match: {e}")
                traceback.print_exc()
                continue

finally:
    driver.quit()
    print("\nBrowser closed.")

# ============================================================
# SAVE
# ============================================================
if new_rows:
    new_df = pd.DataFrame(new_rows, columns=OUTPUT_COLUMNS)
    new_df = new_df[new_df["player_name"] != ""].reset_index(drop=True)
    print(f"\nNew rows scraped: {len(new_df)}")

    if EXISTING_CSV and os.path.exists(EXISTING_CSV):
        existing_df = pd.read_csv(EXISTING_CSV)
        print(f"Existing rows: {len(existing_df)}")
        combined_df = pd.concat([existing_df, new_df], ignore_index=True)
        before = len(combined_df)
        combined_df = combined_df.drop_duplicates(
            subset=["player_name", "team", "round", "season"],
            keep="last"
        ).reset_index(drop=True)
        print(f"Dedup removed {before - len(combined_df)} rows")
    else:
        # Single-round mode: just dedupe within this round's own scrape
        # (in case the script re-visits a team tab twice in one run)
        combined_df = new_df.drop_duplicates(
            subset=["player_name", "team", "round", "season"],
            keep="last"
        ).reset_index(drop=True)

    combined_df = clean_dataframe(combined_df)
    combined_df.to_csv(OUTPUT_CSV, index=False)
    print(f"\nSaved {len(combined_df)} total rows to {OUTPUT_CSV}")

    # REAL FIX 2026-07-03, per a full project audit: this used to be a
    # second, separate hardcoded bye dict (short team names, rounds
    # 1-16 only) -- a duplicate of the same real-world fact already
    # maintained properly in scripts/bye_schedule.json (used by
    # validate_round.py, which already covers all 27 rounds). Two
    # separate hand-maintained copies of the same schedule is exactly
    # the kind of drift risk this project has been burned by before
    # (see merge_match_results_backfill.py's own EXPECTED_BYES, fixed
    # in this same pass, which had actually drifted -- it claimed zero
    # byes for Round 17 while this file's version and the real official
    # draw both correctly show the Sharks bye). Now derives from the
    # same two real, already-canonical source files every other part of
    # this project uses: team_aliases.json for the full team list, and
    # bye_schedule.json for the per-round bye list. This coverage check
    # runs before canonical normalization happens (that's
    # merge_round.py's job, a later step), so scraped team names here
    # are still short-form ("Knights", not "Newcastle Knights") --
    # resolved through team_aliases.json's aliases map for the
    # comparison, matching the pattern validate_round.py already uses.
    import json as _json
    with open("data/team_aliases.json") as _f:
        _team_aliases_data = _json.load(_f)
    _short_to_canonical = _team_aliases_data["aliases"]
    ALL_TEAMS_CANONICAL = set(_team_aliases_data["canonical_teams"])
    with open("scripts/bye_schedule.json") as _f:
        _bye_schedule_raw = _json.load(_f)
    BYE_SCHEDULE = {int(k): v for k, v in _bye_schedule_raw.items() if not k.startswith("_")}

    print("\n=== COVERAGE CHECK ===")
    for r in ROUNDS_TO_SCRAPE:
        rd = combined_df[combined_df["round"] == r]
        teams_present_canonical = {
            _short_to_canonical.get(t, t) for t in rd["team"].unique()
        }
        expected_missing = set(BYE_SCHEDULE.get(r, []))
        unexpected = sorted((ALL_TEAMS_CANONICAL - teams_present_canonical) - expected_missing)
        status = "OK" if not unexpected else f"MISSING: {unexpected}"
        print(f"R{r:02d}: {len(teams_present_canonical)}/17 teams — {status}")

else:
    print("\nNo data scraped. Check errors above.")
