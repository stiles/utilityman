#!/usr/bin/env python3
"""
utilityman: Follow any MLB game in your shell.

- Finds today's game for a team (or uses --gamepk)
- Streams new at-bats (and optionally every pitch)
- Minimal output, ANSI color optional

Note: Uses MLB StatsAPI schedule + GUMBO live feed.
"""

from __future__ import annotations
import argparse, time, sys, json, re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import requests

API = "https://statsapi.mlb.com/api"
SCHEDULE = f"{API}/v1/schedule"
LIVE = f"{API}/v1.1/game/{{gamepk}}/feed/live"
TEAMS = f"{API}/v1/teams"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
)

# --- tiny helpers -------------------------------------------------------------

def c(enabled: bool, code: str) -> str:
    return code if enabled else ""

def colorize(enabled: bool, s: str, fg: str = "37") -> str:
    # cheap ANSI: fg expects '31'..'37'
    if not enabled:
        return s
    start = "\x1b[" + fg + "m"
    end = "\x1b[0m"
    return f"{start}{s}{end}"

def warn(msg: str):
    print(colorize(True, f"⚠ {msg}", "33"), file=sys.stderr)

def http_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.mlb.com/"
    })
    return s

def local_tz_key(default: str = "America/Los_Angeles") -> str:
    try:
        tzinfo = datetime.now().astimezone().tzinfo
        key = getattr(tzinfo, "key", None)
        if isinstance(key, str) and key:
            return key
    except Exception:
        pass
    return default

def teams_cache_path(season: int) -> str:
    import os
    base = os.path.expanduser("~/.utilityman")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, f"teams-{season}.json")

def load_teams(session: requests.Session, season: int) -> list[dict]:
    # Try cache first
    import os, json as _json
    path = teams_cache_path(season)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = _json.load(f)
                if isinstance(data, list) and data:
                    return data
        except Exception:
            pass
    r = session.get(TEAMS, params={"sportId": 1, "season": season, "activeStatus": "Y"}, timeout=15)
    r.raise_for_status()
    teams = r.json().get("teams", [])
    try:
        with open(path, "w", encoding="utf-8") as f:
            _json.dump(teams, f)
    except Exception:
        pass
    return teams

def parse_team_id(session: requests.Session, team: str, season: int) -> int:
    # Accept LAD, Dodgers, "Los Angeles Dodgers", or numeric id
    if re.fullmatch(r"\d+", team):
        return int(team)
    teams = load_teams(session, season)
    t = team.lower()
    for x in teams:
        if t in {
            x.get("abbreviation","" ).lower(),
            x.get("teamName","" ).lower(),
            x.get("name","" ),
            x.get("clubName","" ).lower()
        }:
            return x["id"]
    # try substring match as a last resort
    for x in teams:
        name = (x.get("name") or "").lower()
        if t in name:
            return x["id"]
    raise SystemExit(f"Could not resolve team: {team}")

def find_gamepk(session: requests.Session, team_id: int, date_str: str, tz: str, opponent_id: int | None = None) -> int:
    # Pull schedule for date, filtered by team
    params = {
        "sportId": 1,
        "teamId": team_id,
        "startDate": date_str,
        "endDate": date_str,
        "timeZone": tz,
        "hydrate": "linescore,team,flags,statusFlags"
    }
    if opponent_id:
        params["opponentId"] = opponent_id
    r = session.get(SCHEDULE, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    dates = data.get("dates", [])
    if not dates:
        raise SystemExit("No games found for that date")
    games = dates[0].get("games", [])
    # Prefer in-progress, then pre-game/scheduled, else last resort
    def key(g):
        s = g.get("status", {}).get("abstractGameState", "")
        rank = {"Live": 0, "Preview": 1, "Final": 2}.get(s, 9)
        return (rank, g.get("gameDate"))
    games.sort(key=key)
    gamepk = games[0]["gamePk"]
    return gamepk

def fetch_team_schedule(
    session: requests.Session,
    team_id: int,
    start_date: str,
    end_date: str,
    tz: str,
) -> list[dict]:
    # Returns a flat list of game objects for a team over a date range
    params = {
        "sportId": 1,
        "teamId": team_id,
        "startDate": start_date,
        "endDate": end_date,
        "timeZone": tz,
        "hydrate": "linescore,team,flags,statusFlags",
    }
    r = session.get(SCHEDULE, params=params, timeout=20)
    r.raise_for_status()
    data = r.json() or {}
    games: list[dict] = []
    for d in data.get("dates", []) or []:
        games.extend(d.get("games", []) or [])
    return games

def choose_live_last_next(games: list[dict], now_utc: datetime) -> tuple[dict|None, dict|None, dict|None]:
    # Picks a live game if any; otherwise the most recent Final and the next upcoming
    live = None
    last_final = None
    next_up = None

    # Normalize and sort by gameDate
    def parse_gd(g: dict) -> datetime:
        gd = (g.get("gameDate") or "").replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(gd)
        except Exception:
            return now_utc

    games_sorted = sorted(games, key=parse_gd)

    for g in games_sorted:
        status = (g.get("status") or {}).get("abstractGameState")
        if status == "Live":
            live = g
            break

    if not live:
        for g in games_sorted:
            status = (g.get("status") or {}).get("abstractGameState")
            if status == "Final":
                if not last_final or parse_gd(g) > parse_gd(last_final):
                    last_final = g

        for g in games_sorted:
            status = (g.get("status") or {}).get("abstractGameState")
            if status in {"Preview"} and parse_gd(g) >= now_utc:
                next_up = g
                break

    return live, last_final, next_up

def game_local_date(g: dict, tz_key: str) -> str | None:
    gd = (g.get("gameDate") or "").replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(gd).astimezone(ZoneInfo(tz_key)).date().isoformat()
    except Exception:
        return None

def select_gamepk_interactive(games: list[dict], team_id: int, tz_key: str, target_date: str) -> int | None:
    # Filter to target date
    candidates: list[dict] = []
    for g in games:
        if game_local_date(g, tz_key) == target_date:
            candidates.append(g)
    if len(candidates) <= 1:
        return candidates[0]["gamePk"] if candidates else None

    # Build choices
    rows: list[tuple[int, str]] = []
    for g in candidates:
        teams = (g.get("teams") or {})
        home = (teams.get("home") or {}).get("team", {}) or {}
        away = (teams.get("away") or {}).get("team", {}) or {}
        opp = away if home.get("id") == team_id else home
        opp_abbr = opp.get("abbreviation") or opp.get("teamName") or "?"
        when = game_local_date(g, tz_key)
        gd = (g.get("gameDate") or "").replace("Z", "+00:00")
        try:
            dt_local = datetime.fromisoformat(gd).astimezone(ZoneInfo(tz_key))
            when_str = dt_local.strftime("%a %I:%M %p")
        except Exception:
            when_str = when or ""
        status = (g.get("status") or {}).get("detailedState") or (g.get("status") or {}).get("abstractGameState")
        rows.append((g["gamePk"], f"{when_str} vs {opp_abbr} [{status}]"))

    print("Multiple games found. Choose one:")
    for i, (_, label) in enumerate(rows, start=1):
        print(f"  {i}) {label}")
    while True:
        try:
            choice = input("Select [1-{}]: ".format(len(rows))).strip()
        except EOFError:
            choice = "1"
        if not choice:
            choice = "1"
        if choice.isdigit() and 1 <= int(choice) <= len(rows):
            return rows[int(choice)-1][0]
        print("Invalid selection.")

def format_game_brief(g: dict, local_tz: str) -> str:
    if not g:
        return ""
    teams = (g.get("teams") or {})
    home = (teams.get("home") or {})
    away = (teams.get("away") or {})
    ht = ((home.get("team") or {}).get("abbreviation")
          or (home.get("team") or {}).get("teamName") or "Home")
    at = ((away.get("team") or {}).get("abbreviation")
          or (away.get("team") or {}).get("teamName") or "Away")
    hr = (home.get("score") if home.get("score") is not None else (g.get("linescore") or {}).get("home", {}).get("runs"))
    ar = (away.get("score") if away.get("score") is not None else (g.get("linescore") or {}).get("away", {}).get("runs"))
    hr = "-" if hr is None else hr
    ar = "-" if ar is None else ar
    gd = (g.get("gameDate") or "").replace("Z", "+00:00")
    try:
        dt_local = datetime.fromisoformat(gd).astimezone(ZoneInfo(local_tz))
        when = dt_local.strftime("%a %Y-%m-%d %I:%M %p %Z")
    except Exception:
        when = g.get("gameDate") or ""
    status = (g.get("status") or {}).get("detailedState") or (g.get("status") or {}).get("abstractGameState")
    return f"{when}  {at} {ar} @ {ht} {hr}  [{status}]"

def get_team_icon(abbr: str) -> str:
    """Always use baseball emoji for consistency"""
    return "⚾"

def fmt_scoreboard(live: dict, color: bool) -> str:
    ls = live.get("liveData", {}).get("linescore", {}) or {}
    teams = ls.get("teams", {}) or {}
    home = teams.get("home", {})
    away = teams.get("away", {})
    inning = ls.get("currentInning", 0)
    state = ls.get("inningState", "")
    gd_teams = (live.get("gameData", {}) or {}).get("teams", {})
    away_abbr = ((gd_teams.get("away") or {}).get("abbreviation")
                 or (gd_teams.get("away") or {}).get("teamName") or "AWY")
    home_abbr = ((gd_teams.get("home") or {}).get("abbreviation")
                 or (gd_teams.get("home") or {}).get("teamName") or "HME")
    
    # Get team icons
    away_icon = get_team_icon(away_abbr)
    home_icon = get_team_icon(home_abbr)
    
    # Clean, simple scoreboard format
    arrow = "▲" if state == "Top" else "▼" if state == "Bottom" else ""
    inning_text = f"{arrow} {state} {inning}" if state and inning else f"Inning {inning or '?'}"
    
    away_line = f"{away_icon} {colorize(color, away_abbr, '36')} {away.get('runs',0):>2}  (H:{away.get('hits',0):>2} E:{away.get('errors',0)})"
    home_line = f"{home_icon} {colorize(color, home_abbr, '35')} {home.get('runs',0):>2}  (H:{home.get('hits',0):>2} E:{home.get('errors',0)})"
    
    # Simple header and content - no complex borders
    sb = f"🏟️  {colorize(color, inning_text, '33')}\n     {away_line}\n     {home_line}"
    return sb

def fmt_linescore(live: dict, color: bool) -> str:
    ls = (live.get("liveData", {}) or {}).get("linescore", {}) or {}
    innings = ls.get("innings") or []
    gd_teams = (live.get("gameData", {}) or {}).get("teams", {})
    away_abbr = ((gd_teams.get("away") or {}).get("abbreviation")
                 or (gd_teams.get("away") or {}).get("teamName") or "AWY")
    home_abbr = ((gd_teams.get("home") or {}).get("abbreviation")
                 or (gd_teams.get("home") or {}).get("teamName") or "HME")
    away_cells, home_cells = [], []
    for inn in innings:
        a = ((inn.get("away") or {}).get("runs"))
        h = ((inn.get("home") or {}).get("runs"))
        away_cells.append("-" if a is None else str(a))
        home_cells.append("-" if h is None else str(h))
    a_row = f"{colorize(color, away_abbr, '36')} " + " ".join(away_cells)
    h_row = f"{colorize(color, home_abbr, '35')} " + " ".join(home_cells)
    return a_row + "\n" + h_row

def fmt_inning_banner(live: dict, color: bool) -> str:
    ls = (live.get("liveData", {}) or {}).get("linescore", {}) or {}
    inning = ls.get("currentInning")
    is_top = ls.get("isTopInning")
    if inning is None or is_top is None:
        return ""
    arrow = "\u25B2" if is_top else "\u25BC"
    label = "Top" if is_top else "Bottom"
    fg = "36" if is_top else "35"
    return colorize(color, f"{arrow} {label} {inning}", fg)

def _format_start_time_local(live: dict, tz_key: str) -> str | None:
    gd = (live.get("gameData") or {})
    dt = ((gd.get("datetime") or {}).get("dateTime")) or (live.get("gameDate"))
    if not dt:
        return None
    try:
        iso = dt.replace("Z", "+00:00")
        dt_local = datetime.fromisoformat(iso).astimezone(ZoneInfo(tz_key))
        return dt_local.strftime("%a %I:%M %p %Z")
    except Exception:
        return None

def fmt_game_header(live: dict, color: bool, tz_key: str) -> str:
    """Create a clean, organized game header"""
    gd = (live.get("gameData") or {})
    teams = (gd.get("teams") or {})
    away_team = teams.get("away") or {}
    home_team = teams.get("home") or {}
    
    away_name = away_team.get("name") or away_team.get("teamName") or "Away"
    home_name = home_team.get("name") or home_team.get("teamName") or "Home"
    
    # Game info
    venue = (gd.get("venue") or {}).get("name", "")
    
    # Format start time
    when = _format_start_time_local(live, tz_key)
    
    # Get probable pitchers
    probs = (gd.get("probablePitchers") or {})
    away_pitcher = (probs.get("away") or {}).get("fullName", "")
    home_pitcher = (probs.get("home") or {}).get("fullName", "")
    
    # Create clean header
    header_parts = []
    header_parts.append(f"⚾ Game On! ⚾")
    header_parts.append(f"Teams: {colorize(color, away_name, '36')} at {colorize(color, home_name, '35')}")
    
    if away_pitcher and home_pitcher:
        header_parts.append(f"Pitchers: {away_pitcher} vs. {home_pitcher}")
    
    if venue:
        header_parts.append(f"📍 {venue}")
    if when:
        header_parts.append(f"🕐 {when}")
    
    return "\n".join(header_parts)

def fmt_probables(live: dict, color: bool, tz_key: str) -> str | None:
    gd = (live.get("gameData") or {})
    teams = (gd.get("teams") or {})
    away = (teams.get("away") or {}).get("abbreviation") or (teams.get("away") or {}).get("teamName")
    home = (teams.get("home") or {}).get("abbreviation") or (teams.get("home") or {}).get("teamName")
    probs = (gd.get("probablePitchers") or {})
    a = (probs.get("away") or {}).get("fullName")
    h = (probs.get("home") or {}).get("fullName")
    if not (a or h):
        return None
    left = f"{colorize(color, away or 'AWY', '36')} {a or '?'}"
    right = f"{colorize(color, home or 'HME', '35')} {h or '?'}"
    when = _format_start_time_local(live, tz_key)
    when_txt = f" — {when}" if when else ""
    return f"Probables: {left} vs {right}{when_txt}"

def new_pitches(play: dict, last_count: int) -> list[str]:
    ev = play.get("playEvents") or []
    out = []
    for i in range(last_count, len(ev)):
        e = ev[i]
        if e.get("isPitch"):
            det = e.get("details", {}) or {}
            call = (det.get("call") or {}).get("description", "")
            pitch = det.get("type", {}).get("description", "")
            spd = (e.get("pitchData") or {}).get("startSpeed")
            s = f"   • {pitch or 'Pitch'} — {call or '?'}"
            if spd:
                s += f" @ {spd:.1f} mph"
            out.append(s)
    return out

def fmt_play(p: dict, color: bool, fallback_bases: set[str] | None = None) -> str:
    about = p.get("about", {})
    res = p.get("result", {})
    half = (about.get("halfInning", "") or "").lower()
    inn = about.get("inning", "?")
    desc = res.get("description") or res.get("event") or "…"
    rbi = res.get("rbi", 0)
    if rbi:
        desc += f" ({rbi} RBI)"
    count = (p.get("count", {}) or {})
    balls = count.get("balls")
    strikes = count.get("strikes")
    outs = count.get("outs")
    if outs is None:
        outs = about.get("outs", 0)
    matchup = p.get("matchup", {})
    bat = matchup.get("batter", {}).get("fullName", "")
    pit = matchup.get("pitcher", {}).get("fullName", "")
    event_type = (res.get("eventType") or "").lower()
    sides = f"{bat} vs {pit}" if bat and pit and event_type != "statuschange" else ""
    arrow = "\u25B2" if half.startswith("top") else "\u25BC"
    tag_color = "36" if half.startswith("top") else "35"
    tag = colorize(color, f"{arrow}{inn}", tag_color)
    is_scoring = about.get("isScoringPlay") or (rbi and rbi > 0)
    bases_txt = ""
    occupied = set()
    runner_names = {}  # base -> runner name
    runners = p.get("runners")
    if isinstance(runners, list) and runners:
        for r in p["runners"]:
            end_base = (r.get("movement") or {}).get("end")
            if end_base in {"1B","2B","3B"}:
                occupied.add(end_base)
                # Try to get runner name (just last name for brevity)
                runner_name = (r.get("details") or {}).get("runner", {}).get("fullName", "")
                if runner_name:
                    last_name = runner_name.split()[-1] if " " in runner_name else runner_name
                    runner_names[end_base] = last_name[:8]  # truncate long names
        
        # Enhanced base display with labels and optionally names
        base_parts = []
        for base in ["1B", "2B", "3B"]:
            if base in occupied:
                if runner_names.get(base):
                    base_parts.append(f"{base}:{runner_names[base]}")
                else:
                    base_parts.append(f"{base}:◉")
            else:
                base_parts.append(f"{base}:○")
        bases_txt = f" [{' '.join(base_parts)}]"
    elif fallback_bases:
        occupied = set(fallback_bases)
        # Fallback to simple labeled format
        base_parts = []
        for base in ["1B", "2B", "3B"]:
            symbol = "◉" if base in occupied else "○"
            base_parts.append(f"{base}:{symbol}")
        bases_txt = f" [{' '.join(base_parts)}]"
    risp = ("2B" in occupied) or ("3B" in occupied)
    
    # Enhanced scoring play emphasis
    if is_scoring:
        # Check if it's a home run for extra emphasis
        is_homer = "homers" in desc.lower() or "home run" in desc.lower()
        if is_homer:
            # Big emphasis for home runs
            desc_colored = f"🔥 {colorize(color, desc.upper(), '91')} 🔥"  # bright red
        elif rbi and rbi >= 3:
            # Special treatment for big RBI plays
            desc_colored = f"💥 {colorize(color, desc, '93')} 💥"  # bright yellow  
        else:
            # Standard scoring plays - brighter green
            desc_colored = f"⚡ {colorize(color, desc, '92')} ⚡"  # bright green
    elif risp:
        desc_colored = colorize(color, desc, "33")
    else:
        desc_colored = desc

    pitch_ct = None
    # Try to infer pitch count from playEvents length if present
    ev = p.get("playEvents") or []
    if ev:
        pitch_ct = sum(1 for e in ev if e.get("isPitch"))
    
    # Cleaner count display - integrate pitch count with ball-strike count
    if balls is not None and strikes is not None:
        if pitch_ct is not None:
            cnt_txt = f" ({balls}-{strikes}, {pitch_ct}p)"
        else:
            cnt_txt = f" ({balls}-{strikes})"
    else:
        cnt_txt = f" [{pitch_ct}p]" if pitch_ct is not None else ""
    
    return f"{tag}  {desc_colored}{cnt_txt}{bases_txt}" + (f"  — {sides}" if sides else "") + f"   [{outs} out]"

def _print_condensed_routine(pending_plays: list[tuple], color: bool, fbases: set[str]) -> None:
    """Print condensed format for routine plays in the same half-inning"""
    if not pending_plays:
        return
    
    if len(pending_plays) == 1:
        # Just one play, print normally
        print(fmt_play(pending_plays[0][0], color, fbases))
        return
    
    # Multiple routine plays - condense them
    first_play = pending_plays[0][0]
    about = first_play.get("about", {})
    half = (about.get("halfInning", "") or "").lower()
    inn = about.get("inning", "?")
    arrow = "\u25B2" if half.startswith("top") else "\u25BC"
    tag_color = "36" if half.startswith("top") else "35"
    tag = colorize(color, f"{arrow}{inn}", tag_color)
    
    # Create summary of play types
    play_types = []
    for play, _ in pending_plays:
        res = play.get("result", {}) or {}
        evt_type = (res.get("eventType") or "").lower()
        if evt_type == "strikeout":
            play_types.append("K")
        elif evt_type in {"groundout", "forceout"}:
            play_types.append("groundout")
        elif evt_type == "flyout":
            play_types.append("flyout")
        elif evt_type == "lineout":
            play_types.append("lineout")
        elif evt_type == "popout":
            play_types.append("popout")
        else:
            play_types.append("out")
    
    summary = ", ".join(play_types)
    if len(pending_plays) == 3:
        desc = f"3 up, 3 down: {summary}"
    else:
        desc = f"{len(pending_plays)} outs: {summary}"
    
    # Use muted styling for condensed plays
    desc_colored = colorize(color, desc, "90")  # dark gray
    print(f"{tag}  {desc_colored}")

def stream(gamepk: int, interval: float, show_pitches: bool, from_start: bool, color: bool, scoring_only: bool = False, line_score: bool = False, box_interval_min: float | None = None, tz_key: str | None = None, quiet: bool = False, verbose: bool = False, preface_lines: list[str] | None = None):
    s = http_session()
    etag = None
    last_len = 0
    pitch_counts: dict[int, int] = {}
    backoff = interval
    last_sb: str | None = None
    last_status: str | None = None
    play_signatures: dict[int, str] = {}
    last_inning: int | None = None
    last_state: str | None = None
    last_snapshot_ts: float = time.time()
    preface_printed: bool = False
    header_shown: bool = False

    # We'll show a nicer header when we get the first data
    while True:
        hdrs = {"If-None-Match": etag} if etag else {}
        try:
            r = s.get(LIVE.format(gamepk=gamepk), headers=hdrs, timeout=15)
        except requests.RequestException as e:
            warn(f"net hiccup: {e}; retrying in {backoff:.1f}s")
            time.sleep(backoff)
            backoff = min(backoff * 2, 20)
            continue

        if r.status_code == 304:
            time.sleep(interval)
            continue

        if r.status_code >= 400:
            warn(f"http {r.status_code}: {r.text[:200]}")
            time.sleep(interval)
            continue

        etag = r.headers.get("ETag", etag)
        backoff = interval
        data = r.json()

        sb = fmt_scoreboard(data, color)
        ls = (data.get("liveData", {}) or {}).get("linescore", {}) or {}
        cur_inning = ls.get("currentInning")
        cur_state = ls.get("inningState")
        game_status = ((data.get("gameData") or {}).get("status") or {})
        detailed = (game_status.get("detailedState") or "").lower()
        abstract = (game_status.get("abstractGameState") or "").lower()
        is_pregame = (abstract == "preview") or ("pre" in detailed) or ("warm" in detailed)

        plays = (data.get("liveData", {}).get("plays", {}) or {}).get("allPlays", [])
        
        # Show header for live games at the very start
        if not header_shown and not is_pregame and plays:
            header = fmt_game_header(data, color, tz_key or local_tz_key("America/Los_Angeles"))
            print(f"\n{header}")
            print()
            header_shown = True
        
        if is_pregame:
            # Pregame: show friendly header + scoreboard + probables with start time, skip plays entirely
            status = game_status.get("detailedState", "Preview")
            if sb != last_sb or status != last_status:
                if not preface_printed:
                    # Show nice pregame header first time
                    gd = (data.get("gameData") or {})
                    teams = (gd.get("teams") or {})
                    away_team = teams.get("away") or {}
                    home_team = teams.get("home") or {}
                    away_name = away_team.get("name") or away_team.get("teamName") or "Away"
                    home_name = home_team.get("name") or home_team.get("teamName") or "Home"
                    venue = (gd.get("venue") or {}).get("name", "")
                    when = _format_start_time_local(data, tz_key or local_tz_key("America/Los_Angeles"))
                    
                    # Get probable pitchers
                    probs = (gd.get("probablePitchers") or {})
                    away_pitcher = (probs.get("away") or {}).get("fullName", "")
                    home_pitcher = (probs.get("home") or {}).get("fullName", "")
                    
                    print(f"\n🎯 Game Starting Soon! 🎯")
                    print(f"Teams: {colorize(color, away_name, '36')} at {colorize(color, home_name, '35')}")
                    if away_pitcher and home_pitcher:
                        print(f"Pitchers: {away_pitcher} vs. {home_pitcher}")
                    if venue:
                        print(f"📍 {venue}")
                    if when:
                        print(f"🕐 {when}")
                    print()
                    preface_printed = True
                
                print(colorize(color, "─" * 48, "90"))
                print(sb)
                if preface_lines and not preface_printed:
                    for ln in preface_lines:
                        print(ln)
                # Pitchers already shown in header
                last_sb = sb
                last_status = status
            time.sleep(interval)
            continue

        if not plays:
            status = game_status.get("detailedState", "Unknown")
            if sb != last_sb or status != last_status:
                print(colorize(color, "—" * 72, "90"))
                print(sb)
                print(f"[{status}]")
                last_sb = sb
                last_status = status
            time.sleep(interval)
            continue

        start_idx = 0 if from_start else last_len
        printed_any = False
        # fallback bases from current linescore offense state
        offense = (ls.get("offense") or {})
        fbases: set[str] = set()
        if offense.get("first"):
            fbases.add("1B")
        if offense.get("second"):
            fbases.add("2B")
        if offense.get("third"):
            fbases.add("3B")

        # Smart play condensation - group routine outs in quiet innings
        pending_routine_plays = []
        
        for i in range(start_idx, len(plays)):
            p = plays[i]
            evt_type = ((p.get("result") or {}).get("eventType") or "").lower()
            if evt_type == "statuschange":
                continue
            
            # Check if this is a routine out (for condensation)
            about = p.get("about", {}) or {}
            res = p.get("result", {}) or {}
            is_scoring = about.get("isScoringPlay") or (res.get("rbi") or 0) > 0
            desc = (res.get("description") or res.get("event") or "").lower()
            
            is_routine = (
                not is_scoring and 
                evt_type in {"strikeout", "groundout", "flyout", "lineout", "popout", "forceout"} and
                "error" not in desc and
                "wild pitch" not in desc and
                "passed ball" not in desc and
                "double play" not in desc  # Don't condense double plays
            )
            
            if quiet:
                pass
            elif scoring_only:
                if not is_scoring:
                    # skip non-scoring plays in scoring-only mode
                    pass
                else:
                    print(fmt_play(p, color, fbases))
                    printed_any = True
            else:
                # For now, let's disable smart condensation to avoid bugs
                # TODO: Fix condensation logic in next iteration
                print(fmt_play(p, color, fbases))
                printed_any = True
        
        # Only set printed_any if we actually printed something in the loop above
        # (it should be set inside the loop when we actually print)
        
        # Handle pitch details and signatures for the last few plays
        for i in range(start_idx, len(plays)):
            p = plays[i]
            idx = p.get("about", {}).get("atBatIndex")
            if (show_pitches or verbose) and idx is not None and not quiet:
                seen = pitch_counts.get(idx, 0)
                for line in new_pitches(p, seen):
                    print(colorize(color, line, "37"))
                pitch_counts[idx] = len(p.get("playEvents") or [])

            # record signature for updated printing later
            if idx is not None:
                res = p.get("result", {}) or {}
                desc = (res.get("description") or res.get("event") or "")
                outs = (p.get("count", {}) or {}).get("outs")
                sig = f"{desc}|{outs}"
                play_signatures[idx] = sig

        last_len = len(plays)

        # Detect updates to the most recent few plays (at-bats completing)
        updates_printed = False
        window_start = max(len(plays) - 5, 0)
        for i in range(window_start, len(plays)):
            p = plays[i]
            idx = p.get("about", {}).get("atBatIndex")
            if idx is None:
                continue
            res = p.get("result", {}) or {}
            desc = (res.get("description") or res.get("event") or "")
            outs = (p.get("count", {}) or {}).get("outs")
            sig = f"{desc}|{outs}"
            prev = play_signatures.get(idx)
            if prev is not None and sig != prev and desc:
                # always show finalized updates even in scoring-only
                if not quiet:
                    # Add a marker to show this is an updated play result
                    updated_play = fmt_play(p, color, fbases)
                    print(f"📝 {updated_play}")
                play_signatures[idx] = sig
                updates_printed = True

        force_boundary = (cur_inning is not None and cur_state is not None and (
            cur_inning != last_inning or cur_state != last_state
        ))
        force_snapshot = False
        if box_interval_min:
            if (time.time() - last_snapshot_ts) >= box_interval_min * 60.0:
                force_snapshot = True
                last_snapshot_ts = time.time()
        
        # Only print scoreboard when there's actually something new
        should_print_scoreboard = (
            force_boundary or 
            (printed_any and sb != last_sb) or 
            updates_printed or 
            force_snapshot
        )
        
        if should_print_scoreboard:
            print(colorize(color, "─" * 48, "90"))
            print(sb)
            last_sb = sb
            last_inning = cur_inning
            last_state = cur_state
            if force_boundary:
                banner = fmt_inning_banner(data, color)
                if banner:
                    print(banner)
                print("")
            # show probable pitchers in pre-game states
            game_status = ((data.get("gameData") or {}).get("status") or {})
            detailed = (game_status.get("detailedState") or "").lower()
            abstract = (game_status.get("abstractGameState") or "").lower()
            if ("pre" in detailed) or ("warm" in detailed) or (abstract == "preview"):
                prob = fmt_probables(data, color, tz_key or local_tz_key("America/Los_Angeles"))
                if prob:
                    print(prob)
            if line_score:
                print(fmt_linescore(data, color))

        abstract = (data.get("gameData", {}).get("status", {}) or {}).get("abstractGameState")
        if abstract == "Final":
            # Show final score one more time
            final_sb = fmt_scoreboard(data, color)
            print(colorize(color, "─" * 48, "90"))
            print(final_sb)
            print()
            print(f"🏁 {colorize(color, 'Game Over! Thanks for watching.', '32')}")
            return

        from_start = False
        time.sleep(interval)

def main():
    tz_default = local_tz_key("America/Los_Angeles")
    # Load config
    import os
    cfg = {}
    cfg_path = os.path.expanduser("~/.utilityman/config.toml")
    try:
        if os.path.exists(cfg_path):
            try:
                import tomllib
            except Exception:
                tomllib = None
            if tomllib:
                with open(cfg_path, "rb") as f:
                    cfg = tomllib.load(f) or {}
    except Exception:
        cfg = {}

    tz_initial = cfg.get("tz") or tz_default
    today_local = datetime.now(ZoneInfo(tz_initial)).date()

    ap = argparse.ArgumentParser(description="Stream MLB play-by-play in your terminal")
    ap.add_argument("team", nargs="?", help="Team id, abbr, or name (e.g., 119, LAD, Dodgers)")
    ap.add_argument("--team", dest="team_flag", help="Team id, abbr, or name (e.g., 119, LAD, Dodgers)")
    ap.add_argument("--date", default=str(today_local), help="YYYY-MM-DD (default: today in local tz)")
    ap.add_argument("--gamepk", type=int, help="MLB gamePk (skips schedule lookup)")
    ap.add_argument("--interval", type=float, default=cfg.get("interval", 2.5), help="Poll seconds (default 2.5)")
    ap.add_argument("--pitches", action="store_true", help="Print each pitch")
    ap.add_argument("--from-start", action="store_true", help="Print all prior at-bats on first fetch")
    ap.add_argument("--no-color", action="store_true", default=bool(cfg.get("no_color", False)), help="Disable ANSI color")
    ap.add_argument("--scoring-only", action="store_true", help="Only print scoring plays and inning transitions")
    ap.add_argument("--opponent", help="Opponent id, abbr, or name to disambiguate doubleheaders")
    ap.add_argument("--log", help="Append stream output to a file")
    ap.add_argument("--dump", help="Write full game log to a file and exit")
    ap.add_argument("--tz", default=cfg.get("tz"), help="IANA timezone (e.g., America/New_York). Defaults to local")
    ap.add_argument("--line-score", action="store_true", default=bool(cfg.get("line_score", False)), help="Print compact inning-by-inning linescore under the scoreboard")
    ap.add_argument("--box-interval", type=float, default=cfg.get("box_interval"), help="Every N minutes, reprint scoreboard even if unchanged")
    ap.add_argument("--quiet", action="store_true", help="Scoreboard and inning banners only")
    ap.add_argument("--verbose", action="store_true", help="More details: pitches and runners")
    args = ap.parse_args()

    session = http_session()
    if args.gamepk:
        gamepk = args.gamepk
        try:
            if args.dump:
                # simple dump: fetch full plays once and write
                s = http_session()
                r = s.get(LIVE.format(gamepk=gamepk), timeout=20)
                r.raise_for_status()
                data = r.json()
                plays = (data.get("liveData", {}).get("plays", {}) or {}).get("allPlays", [])
                with open(args.dump, "w", encoding="utf-8") as f:
                    f.write(fmt_scoreboard(data, not args.no_color) + "\n")
                    for p in plays:
                        f.write(fmt_play(p, not args.no_color) + "\n")
                print(f"Wrote log to {args.dump}")
                return
            # optional streaming log
            if args.log:
                old_stdout = sys.stdout
                sys.stdout = open(args.log, "a", encoding="utf-8")
            stream(gamepk, interval=args.interval, show_pitches=args.pitches,
                   from_start=args.from_start, color=not args.no_color, scoring_only=args.scoring_only,
                   line_score=args.line_score, box_interval_min=args.box_interval, tz_key=tz_key,
                   quiet=args.quiet, verbose=args.verbose, preface_lines=None)
        except KeyboardInterrupt:
            print("\nBye.")
        return

    team_input = args.team or args.team_flag or cfg.get("team")
    if not team_input:
        try:
            team_input = input("Team (e.g., LAD, NYY, SFG or Dodgers, Yankees, Giants): ").strip()
        except EOFError:
            team_input = ""
    if not team_input:
        ap.error("team is required (positional or --team)")

    season = datetime.fromisoformat(args.date).year
    team_id = parse_team_id(session, team_input, season)
    opponent_id = None
    if args.opponent:
        opponent_id = parse_team_id(session, args.opponent, season)

    tz_key = args.tz or local_tz_key("America/Los_Angeles")
    local_zone = ZoneInfo(tz_key)
    now_local = datetime.now(local_zone)
    start = (now_local - timedelta(days=2)).date().isoformat()
    end = (now_local + timedelta(days=3)).date().isoformat()
    games = fetch_team_schedule(session, team_id, start, end, tz=tz_key)
    live, last_final, next_up = choose_live_last_next(games, now_local.astimezone(timezone.utc))

    if live:
        gamepk = live.get("gamePk")
        try:
            if args.dump:
                s = http_session()
                r = s.get(LIVE.format(gamepk=gamepk), timeout=20)
                r.raise_for_status()
                data = r.json()
                plays = (data.get("liveData", {}).get("plays", {}) or {}).get("allPlays", [])
                with open(args.dump, "w", encoding="utf-8") as f:
                    f.write(fmt_scoreboard(data, not args.no_color) + "\n")
                    for p in plays:
                        f.write(fmt_play(p, not args.no_color) + "\n")
                print(f"Wrote log to {args.dump}")
                return
            if args.log:
                old_stdout = sys.stdout
                sys.stdout = open(args.log, "a", encoding="utf-8")
            stream(gamepk, interval=args.interval, show_pitches=args.pitches,
                   from_start=args.from_start, color=not args.no_color, scoring_only=args.scoring_only,
                   line_score=args.line_score, box_interval_min=args.box_interval, tz_key=tz_key,
                   quiet=args.quiet, verbose=args.verbose, preface_lines=None)
        except KeyboardInterrupt:
            print("\nBye.")
        return

    # No live game: show last and next once
    print(colorize(not args.no_color, "—" * 72, "90"))
    if last_final:
        print("Last game:")
        print("  " + format_game_brief(last_final, tz_key))
    if next_up:
        print("Next game:")
        print("  " + format_game_brief(next_up, tz_key))

    # Interactive selection if multiple games today and none live
    selected = select_gamepk_interactive(games, team_id, tz_key, target_date=str(now_local.date()))
    if selected:
        try:
            preface: list[str] = []
            if last_final:
                preface.append("Last game:")
                preface.append("  " + format_game_brief(last_final, tz_key))
            if next_up:
                preface.append("Next game:")
                preface.append("  " + format_game_brief(next_up, tz_key))
            stream(selected, interval=args.interval, show_pitches=args.pitches,
                   from_start=args.from_start, color=not args.no_color, scoring_only=args.scoring_only,
                   line_score=args.line_score, box_interval_min=args.box_interval, tz_key=tz_key,
                   quiet=args.quiet, verbose=args.verbose, preface_lines=preface)
        except KeyboardInterrupt:
            print("\nBye.")
        return

    # If nothing selected, we've already printed last/next above

if __name__ == "__main__":
    main()


