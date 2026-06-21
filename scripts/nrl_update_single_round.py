import time
import os
import argparse
import pandas as pd
import traceback
import warnings
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
FALLBACK_URLS = {
    1: [
        f"{BASE}/round-1/warriors-v-roosters",
        f"{BASE}/round-1/sea-eagles-v-raiders",
        f"{BASE}/round-1/storm-v-eels",
        f"{BASE}/round-1/sharks-v-titans",
        f"{BASE}/round-1/broncos-v-panthers",
        f"{BASE}/round-1/knights-v-cowboys",
        f"{BASE}/round-1/dolphins-v-rabbitohs",
        f"{BASE}/round-1/bulldogs-v-dragons",
    ],
    2: [
        f"{BASE}/round-2/broncos-v-eels",
        f"{BASE}/round-2/warriors-v-raiders",
        f"{BASE}/round-2/roosters-v-rabbitohs",
        f"{BASE}/round-2/sea-eagles-v-knights",
        f"{BASE}/round-2/dolphins-v-titans",
        f"{BASE}/round-2/panthers-v-sharks",
        f"{BASE}/round-2/dragons-v-storm",
        f"{BASE}/round-2/wests-tigers-v-cowboys",
    ],
    3: [
        f"{BASE}/round-3/storm-v-broncos",
        f"{BASE}/round-3/roosters-v-panthers",
        f"{BASE}/round-3/sharks-v-dolphins",
        f"{BASE}/round-3/cowboys-v-titans",
        f"{BASE}/round-3/rabbitohs-v-wests-tigers",
        f"{BASE}/round-3/raiders-v-bulldogs",
        f"{BASE}/round-3/eels-v-dragons",
        f"{BASE}/round-3/knights-v-warriors",
    ],
    4: [
        f"{BASE}/round-4/bulldogs-v-knights",
        f"{BASE}/round-4/warriors-v-wests-tigers",
        f"{BASE}/round-4/raiders-v-sharks",
        f"{BASE}/round-4/broncos-v-dolphins",
        f"{BASE}/round-4/sea-eagles-v-roosters",
        f"{BASE}/round-4/cowboys-v-storm",
        f"{BASE}/round-4/panthers-v-eels",
        f"{BASE}/round-4/titans-v-dragons",
    ],
    5: [
        f"{BASE}/round-5/titans-v-broncos",
        f"{BASE}/round-5/knights-v-raiders",
        f"{BASE}/round-5/dolphins-v-sea-eagles",
        f"{BASE}/round-5/rabbitohs-v-bulldogs",
        f"{BASE}/round-5/dragons-v-cowboys",
        f"{BASE}/round-5/eels-v-wests-tigers",
        f"{BASE}/round-5/panthers-v-storm",
        f"{BASE}/round-5/sharks-v-warriors",
    ],
    6: [
        f"{BASE}/round-6/storm-v-warriors",
        f"{BASE}/round-6/rabbitohs-v-raiders",
        f"{BASE}/round-6/dragons-v-sea-eagles",
        f"{BASE}/round-6/eels-v-titans",
        f"{BASE}/round-6/wests-tigers-v-knights",
        f"{BASE}/round-6/sharks-v-roosters",
        f"{BASE}/round-6/bulldogs-v-panthers",
        f"{BASE}/round-6/broncos-v-cowboys",
    ],
    7: [
        f"{BASE}/round-7/roosters-v-knights",
        f"{BASE}/round-7/dolphins-v-panthers",
        f"{BASE}/round-7/warriors-v-titans",
        f"{BASE}/round-7/rabbitohs-v-dragons",
        f"{BASE}/round-7/wests-tigers-v-broncos",
        f"{BASE}/round-7/eels-v-bulldogs",
        f"{BASE}/round-7/cowboys-v-sea-eagles",
        f"{BASE}/round-7/raiders-v-storm",
    ],
    8: [
        f"{BASE}/round-8/dragons-v-roosters",
        f"{BASE}/round-8/storm-v-rabbitohs",
        f"{BASE}/round-8/wests-tigers-v-raiders",
        f"{BASE}/round-8/cowboys-v-sharks",
        f"{BASE}/round-8/broncos-v-bulldogs",
        f"{BASE}/round-8/knights-v-panthers",
        f"{BASE}/round-8/sea-eagles-v-eels",
        f"{BASE}/round-8/warriors-v-dolphins",
    ],
    9: [
        f"{BASE}/round-9/bulldogs-v-cowboys",
        f"{BASE}/round-9/eels-v-warriors",
        f"{BASE}/round-9/titans-v-raiders",
        f"{BASE}/round-9/panthers-v-sea-eagles",
        f"{BASE}/round-9/roosters-v-broncos",
        f"{BASE}/round-9/knights-v-rabbitohs",
        f"{BASE}/round-9/dolphins-v-storm",
        f"{BASE}/round-9/sharks-v-wests-tigers",
    ],
    10: [
        f"{BASE}/round-10/sea-eagles-v-broncos",
        f"{BASE}/round-10/storm-v-wests-tigers",
        f"{BASE}/round-10/raiders-v-panthers",
        f"{BASE}/round-10/rabbitohs-v-sharks",
        f"{BASE}/round-10/dolphins-v-bulldogs",
        f"{BASE}/round-10/dragons-v-knights",
        f"{BASE}/round-10/cowboys-v-eels",
        f"{BASE}/round-10/roosters-v-titans",
    ],
    11: [
        f"{BASE}/round-11/wests-tigers-v-sea-eagles",
        f"{BASE}/round-11/eels-v-storm",
        f"{BASE}/round-11/rabbitohs-v-dolphins",
        f"{BASE}/round-11/titans-v-knights",
        f"{BASE}/round-11/panthers-v-dragons",
        f"{BASE}/round-11/roosters-v-cowboys",
        f"{BASE}/round-11/warriors-v-broncos",
        f"{BASE}/round-11/sharks-v-bulldogs",
    ],
    12: [
        f"{BASE}/round-12/sea-eagles-v-titans",
        f"{BASE}/round-12/dragons-v-warriors",
        f"{BASE}/round-12/raiders-v-dolphins",
        f"{BASE}/round-12/bulldogs-v-storm",
        f"{BASE}/round-12/cowboys-v-rabbitohs",
        f"{BASE}/round-12/broncos-v-roosters",
        f"{BASE}/round-12/knights-v-sharks",
        f"{BASE}/round-12/panthers-v-eels",
    ],
    13: [
        f"{BASE}/round-13/sharks-v-sea-eagles",
        f"{BASE}/round-13/knights-v-eels",
        f"{BASE}/round-13/wests-tigers-v-bulldogs",
        f"{BASE}/round-13/storm-v-roosters",
        f"{BASE}/round-13/broncos-v-dragons",
        f"{BASE}/round-13/raiders-v-cowboys",
        f"{BASE}/round-13/panthers-v-warriors",
        # NOTE: "dolphins-v-rabbitohs" removed here — per official NRL draw, Dolphins, Rabbitohs
        # AND Titans all have a bye in R13, so this fixture cannot exist. It was a data error
        # in the original script. R13 correctly has only 7 matches (14 of 17 teams play).
    ],
    # R14, R15 added — verified against official NRL 2026 draw PDF (nrl.com/globalassets/nrl-draw-2026---final.pdf)
    14: [
        f"{BASE}/round-14/sea-eagles-v-rabbitohs",
        f"{BASE}/round-14/storm-v-knights",
        f"{BASE}/round-14/raiders-v-roosters",
        f"{BASE}/round-14/cowboys-v-dolphins",
        f"{BASE}/round-14/broncos-v-titans",
        f"{BASE}/round-14/wests-tigers-v-panthers",
        f"{BASE}/round-14/sharks-v-dragons",
        f"{BASE}/round-14/bulldogs-v-eels",
        # Bye R14: Warriors
    ],
    15: [
        f"{BASE}/round-15/rabbitohs-v-broncos",
        f"{BASE}/round-15/dolphins-v-roosters",
        f"{BASE}/round-15/warriors-v-sharks",
        f"{BASE}/round-15/eels-v-raiders",
        f"{BASE}/round-15/wests-tigers-v-titans",
        # Byes R15: Bulldogs, Cowboys, Dragons, Knights, Panthers, Sea Eagles, Storm (7 teams, 5 matches)
    ],
    16: [
        f"{BASE}/round-16/knights-v-dragons",
        f"{BASE}/round-16/wests-tigers-v-dolphins",
        f"{BASE}/round-16/titans-v-panthers",
        f"{BASE}/round-16/bulldogs-v-sea-eagles",
        f"{BASE}/round-16/warriors-v-cowboys",
        f"{BASE}/round-16/storm-v-raiders",
        f"{BASE}/round-16/roosters-v-sharks",
        # Byes R16: Broncos, Eels, Rabbitohs (7 matches, 14/17 teams)
    ],
}

OUTPUT_COLUMNS = [
    "player_name", "team", "opponent", "round", "season",
    "position", "mins_played",
    "tries", "points",
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
        "passes_to_run_ratio", "tackle_efficiency", "mins_played"
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
for round_num in ROUNDS_TO_SCRAPE:
    print(f"\n=== Round {round_num} ===")

    match_urls = FALLBACK_URLS.get(round_num, [])

    if not match_urls:
        draw_url = f"https://www.nrl.com/draw/?competition=111&round={round_num}&season={SEASON}"
        driver.get(draw_url)
        time.sleep(5)
        try:
            link_els = driver.find_elements(By.XPATH, "//a[contains(@href, '/draw/nrl-premiership/')]")
            match_urls = list(set([
                el.get_attribute("href").split("#")[0].rstrip("/")
                for el in link_els
                if el.get_attribute("href") and "/round-" in el.get_attribute("href")
            ]))
        except Exception as e:
            print(f"  Could not find match links: {e}")
            continue

    print(f"  Scraping {len(match_urls)} matches")

    for match_url in match_urls:
        print(f"\n  Visiting: {match_url}")
        try:
            driver.get(match_url)
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

            # Click Player Stats tab
            try:
                tab = wait.until(EC.element_to_be_clickable((
                    By.XPATH, "//a[.//span[contains(text(),'Player Stats')]]"
                )))
                driver.execute_script("arguments[0].click();", tab)
                time.sleep(3)
            except Exception as e:
                print(f"    Could not click Player Stats tab: {e}")
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

        except Exception as e:
            print(f"    Error processing match: {e}")
            traceback.print_exc()
            continue

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

    ALL_TEAMS = {
        'Broncos','Bulldogs','Cowboys','Dolphins','Dragons','Eels',
        'Knights','Panthers','Rabbitohs','Raiders','Roosters',
        'Sea Eagles','Sharks','Storm','Titans','Warriors','Wests Tigers'
    }
    BYES = {
        1:['Wests Tigers'], 2:['Bulldogs'], 3:['Sea Eagles'], 4:['Rabbitohs'],
        5:['Roosters'], 6:['Dolphins'], 7:['Sharks'], 8:['Titans'],
        9:['Dragons'], 10:['Warriors'], 11:['Raiders'],
        12:['Broncos','Eels','Knights','Panthers','Roosters','Sharks','Wests Tigers'],
        13:['Dolphins','Rabbitohs','Titans'],
        14:['Warriors'],
        15:['Bulldogs','Cowboys','Dragons','Knights','Panthers','Sea Eagles','Storm'],
        16:['Broncos','Eels','Rabbitohs'],
    }
    print("\n=== COVERAGE CHECK ===")
    for r in ROUNDS_TO_SCRAPE:
        rd = combined_df[combined_df["round"] == r]
        teams = set(rd["team"].unique())
        expected_missing = set(BYES.get(r, []))
        unexpected = sorted((ALL_TEAMS - teams) - expected_missing)
        status = "OK" if not unexpected else f"MISSING: {unexpected}"
        print(f"R{r:02d}: {len(teams)}/17 teams — {status}")

else:
    print("\nNo data scraped. Check errors above.")
