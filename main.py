#!/usr/bin/env python3
"""
scorebug: Follow any MLB game in your shell.

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

def parse_team_id(session: requests.Session, team: str, season: int) -> int:
    # Accept LAD, Dodgers, "Los Angeles Dodgers", or numeric id
    if re.fullmatch(r"\d+", team):
        return int(team)
    r = session.get(TEAMS, params={"sportId": 1, "season": season, "activeStatus": "Y"}, timeout=15)
    r.raise_for_status()
    teams = r.json().get("teams", [])
    t = team.lower()
    for x in teams:
        if t in {
            x.get("abbreviation","").lower(),
            x.get("teamName","").lower(),
            x.get("name","").lower(),
            x.get("clubName","").lower()
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
                # keep most recent final
                if not last_final or parse_gd(g) > parse_gd(last_final):
                    last_final = g

        for g in games_sorted:
            status = (g.get("status") or {}).get("abstractGameState")
            if status in {"Preview"} and parse_gd(g) >= now_utc:
                next_up = g
                break

    return live, last_final, next_up

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
    sb = (
        f"[{state} {inning or ''}]  "
        f"{colorize(color, away_abbr, '36')} {away.get('runs','-')} "
        f"{colorize(color, 'H', '36')} {away.get('hits','-')} "
        f"{colorize(color, 'E', '36')} {away.get('errors','-')}  |  "
        f"{colorize(color, home_abbr, '35')} {home.get('runs','-')} "
        f"{colorize(color, 'H', '35')} {home.get('hits','-')} "
        f"{colorize(color, 'E', '35')} {home.get('errors','-')}"
    )
    return sb

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

def fmt_play(p: dict, color: bool) -> str:
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
    # who’s batting
    matchup = p.get("matchup", {})
    bat = matchup.get("batter", {}).get("fullName", "")
    pit = matchup.get("pitcher", {}).get("fullName", "")
    sides = f"{bat} vs {pit}" if bat and pit else ""
    arrow = "\u25B2" if half.startswith("top") else "\u25BC"
    tag_color = "36" if half.startswith("top") else "35"
    tag = colorize(color, f"{arrow}{inn}", tag_color)
    is_scoring = about.get("isScoringPlay") or (rbi and rbi > 0)
    desc_colored = colorize(color, desc, "32") if is_scoring else desc
    bases_txt = ""
    if isinstance(p.get("runners"), list):
        occupied = set()
        for r in p["runners"]:
            end_base = (r.get("movement") or {}).get("end")
            if end_base in {"1B","2B","3B"}:
                occupied.add(end_base)
        def dot(b):
            return "◉" if b in occupied else "○"
        bases_txt = f" {dot('1B')}{dot('2B')}{dot('3B')}"

    pitch_ct = None
    ev = p.get("playEvents") or []
    if ev:
        pitch_ct = sum(1 for e in ev if e.get("isPitch"))
    cnt_txt = f" ({balls}-{strikes})" if balls is not None and strikes is not None else ""
    pc_txt = f" [{pitch_ct}p]" if pitch_ct is not None else ""
    return f"{tag}  {desc_colored}{cnt_txt}{bases_txt}" + (f"  — {sides}" if sides else "") + f"   [{outs} out]{pc_txt}"

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

# --- streamer ----------------------------------------------------------------

def stream(gamepk: int, interval: float, show_pitches: bool, from_start: bool, color: bool, scoring_only: bool = False):
    s = http_session()
    etag = None
    last_len = 0
    pitch_counts: dict[int, int] = {}  # atBatIndex -> #events seen
    backoff = interval
    last_sb: str | None = None
    last_status: str | None = None
    last_inning: int | None = None
    last_state: str | None = None

    print(colorize(color, f"Following gamePk {gamepk}", "32"))
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
        backoff = interval  # reset on success
        data = r.json()

        # scoreboard string for diffing
        sb = fmt_scoreboard(data, color)
        ls = (data.get("liveData", {}) or {}).get("linescore", {}) or {}
        cur_inning = ls.get("currentInning")
        cur_state = ls.get("inningState")

        plays = (data.get("liveData", {}).get("plays", {}) or {}).get("allPlays", [])
        if not plays:
            # not started yet
            status = (data.get("gameData", {}).get("status", {}) or {}).get("detailedState", "Unknown")
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
        for i in range(start_idx, len(plays)):
            p = plays[i]
            if scoring_only:
                about = p.get("about", {}) or {}
                res = p.get("result", {}) or {}
                is_scoring = about.get("isScoringPlay") or (res.get("rbi") or 0) > 0
                if is_scoring:
                    print(fmt_play(p, color))
            else:
                print(fmt_play(p, color))
            idx = p.get("about", {}).get("atBatIndex")
            if show_pitches and idx is not None:
                seen = pitch_counts.get(idx, 0)
                for line in new_pitches(p, seen):
                    print(colorize(color, line, "37"))
                pitch_counts[idx] = len(p.get("playEvents") or [])
            printed_any = True

        last_len = len(plays)
        force_boundary = (cur_inning is not None and cur_state is not None and (
            cur_inning != last_inning or cur_state != last_state
        ))
        if force_boundary or printed_any or sb != last_sb:
            print(colorize(color, "—" * 72, "90"))
            print(sb)
            last_sb = sb
            last_inning = cur_inning
            last_state = cur_state
            if force_boundary:
                banner = fmt_inning_banner(data, color)
                if banner:
                    print(banner)
                print("")

        # end condition
        abstract = (data.get("gameData", {}).get("status", {}) or {}).get("abstractGameState")
        if abstract == "Final":
            print(colorize(color, "Final. Stream closed.", "32"))
            return

        from_start = False  # only apply once
        time.sleep(interval)

# --- cli ---------------------------------------------------------------------

def main():
    tz_local = "America/Los_Angeles"
    today_local = datetime.now(ZoneInfo(tz_local)).date()

    ap = argparse.ArgumentParser(description="Stream MLB play-by-play in your terminal")
    ap.add_argument("team", nargs="?", help="Team id, abbr, or name (e.g., 119, LAD, Dodgers)")
    ap.add_argument("--team", dest="team_flag", help="Team id, abbr, or name (e.g., 119, LAD, Dodgers)")
    ap.add_argument("--date", default=str(today_local), help="YYYY-MM-DD (default: today in LA)")
    ap.add_argument("--gamepk", type=int, help="MLB gamePk (skips schedule lookup)")
    ap.add_argument("--interval", type=float, default=2.5, help="Poll seconds (default 2.5)")
    ap.add_argument("--pitches", action="store_true", help="Print each pitch")
    ap.add_argument("--from-start", action="store_true", help="Print all prior at-bats on first fetch")
    ap.add_argument("--no-color", action="store_true", help="Disable ANSI color")
    ap.add_argument("--scoring-only", action="store_true", help="Only print scoring plays and inning transitions")
    ap.add_argument("--opponent", help="Opponent id, abbr, or name to disambiguate doubleheaders")
    ap.add_argument("--log", help="Append stream output to a file")
    ap.add_argument("--dump", help="Write full game log to a file and exit")
    args = ap.parse_args()

    session = http_session()
    if args.gamepk:
        gamepk = args.gamepk
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
                   from_start=args.from_start, color=not args.no_color, scoring_only=args.scoring_only)
        except KeyboardInterrupt:
            print("\nBye.")
        return

    # Determine team input
    team_input = args.team or args.team_flag
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

    # Prefer live game today; otherwise show last and next
    local_zone = ZoneInfo(tz_local)
    now_local = datetime.now(local_zone)
    start = (now_local - timedelta(days=2)).date().isoformat()
    end = (now_local + timedelta(days=3)).date().isoformat()
    games = fetch_team_schedule(session, team_id, start, end, tz=tz_local)
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
                   from_start=args.from_start, color=not args.no_color, scoring_only=args.scoring_only)
        except KeyboardInterrupt:
            print("\nBye.")
        return

    # No live game: print last result and next game
    print(colorize(not args.no_color, "—" * 72, "90"))
    if last_final:
        print("Last game:")
        print("  " + format_game_brief(last_final, tz_local))
    else:
        print("No recent completed game found.")

    if next_up:
        print("Next game:")
        print("  " + format_game_brief(next_up, tz_local))
    else:
        print("No upcoming game found in the next few days.")

if __name__ == "__main__":
    main()
