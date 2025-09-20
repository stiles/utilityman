# deps
uv pip install requests      # or: pip install requests

# run: follow a team today
scorebug dodgers

# run: explicit gamePk, show pitches, start from first at-bat
scorebug --gamepk 776443 --pitches --from-start

# run: any team on a specific date (YYYY-MM-DD)
scorebug --team Orioles --date 2025-09-06


==

Why this works

schedule gives you the gamePk for a team on a date; you don’t need the monster hydrate string you pasted unless you want extras. 
xStats

v1.1/game/{gamePk}/feed/live is the unified GUMBO feed with liveData.plays.allPlays, currentPlay, and linescore. Polling it with If-None-Match avoids duplicate payloads. 
controlc.com
AndSchneider
GitHub

Done

- Packaged as CLI with `scorebug` entry point
- Positional team arg and prompt fallback
- Real team abbreviations in scoreboard
- Scoring plays highlighted
- Scoreboard prints on change and inning transitions
- Reprints plays when descriptions finalize
- Ball/strike count and pitch count per play
- Base runner indicators when available (◉○○)
- Inning banners on half-inning transitions
- Logging: --log for streaming, --dump for full-game export
- Config defaults via ~/.scorebug/config.toml (team, tz, color, interval)
- Quiet/verbose modes
- Base-state fallback when runners list is missing

Next features

- Scoring-only refinements (concise between-plays summaries)
- Box score snapshot every N minutes or on inning end
- Opponent filter improvements when multiple games in a day
- Save game log to file (--log path)
- Dump historical play-by-play for a specific date/gamePk to a file
- ASCII line score per inning and RISP highlighting

Visual/UX improvements (prioritized by value vs complexity)

🎯 **Quick wins (high value, low complexity):** ✅ COMPLETED v0.4.0
- ✅ Enhanced scoring emphasis: 🔥 home runs with fire emojis + ALL CAPS, ⚡ RBI plays with lightning, 💥 big RBI plays (3+)
- ⏸️ Smart play condensation: temporarily disabled due to grouping bugs (TODO: fix in future release)
- ✅ Better base runner display: [1B:Lindor 2B:Soto 3B:○] with player names and labeled bases
- ✅ Cleaner pitch count format: (2-1, 5p) integrated format instead of separate [5p]
- ✅ Fixed scoreboard spam: reduced frequency to only print on actual changes

🚀 **High impact features (high value, medium complexity):**
- Inning summaries: show runs/hits scored in each half-inning on transitions (enhance boundary detection lines 651-669)
- Auto-verbosity: more detail in close games, less in blowouts (modify streaming logic around line 593)
- Better incomplete play indicator: replace "..." with clearer waiting/updating status (around line 419)

⭐ **Polish improvements (medium value, low complexity):**
- Enhanced game state: more prominent inning/outs/count display in tense moments (enhance fmt_scoreboard() around line 277)
- Pitcher context: show current pitcher's pitch count and inning stats (add new function, integrate around line 660)

🔧 **Advanced features (medium value, medium complexity):**
- Compact routine plays: shorter format for standard strikeouts/groundouts vs. action plays (requires play classification logic)