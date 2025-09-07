## Scorebug: Live MLB play-by-play in the shell

Follow MLB games in your terminal. Fast to start, easy to read, scriptable.

## Install

- From PyPI
  ```bash
  pip install scorebug
  ```

- Local checkout (editable)
  - Clone this repo
  - pip install -e .

Requires Python 3.9+.

## Usage

- Positional team or prompt

```bash
scorebug dodgers
# or just run `scorebug` and enter a team when prompted
```

- Specific game by gamePk

```bash
scorebug --gamepk 716910
```

- Show every pitch and start from the first at-bat

```bash
scorebug yankees --pitches --from-start
```

## What it does

- Finds today's game for a team (or uses --gamepk)
- Streams new at-bats and optionally every pitch
- Prints a compact scoreboard on change or inning transitions
- Highlights scoring plays
- If no game is live, prints the last final and the next scheduled game

## Output behavior

- Uses team abbreviations in the scoreboard
- Shows ▲ for top and ▼ for bottom of the inning
- Reprints a play if its description updates
- Prints the scoreboard at start of halves and on End/Middle of innings
- Prints an inning banner on half-inning transitions for readability
- Colors: cyan for away, magenta for home, green for scoring plays
- Disable color with --no-color
- Includes ball-strike count and approximate pitch count per at-bat
- Shows base runners when available (◉ occupied, ○ empty)

## CLI reference

- team: team id, abbr, or name (e.g., 119, LAD, Dodgers)
- --team: same as positional team
- --date YYYY-MM-DD: date to search (default: today in Los Angeles)
- --gamepk: MLB gamePk to stream directly
- --interval: poll seconds (default 2.5)
- --pitches: print each pitch
- --from-start: print all prior at-bats on first fetch
- --no-color: disable ANSI color
- --scoring-only: only print scoring plays and inning transitions
- --opponent TEAM: disambiguate doubleheaders by opponent (id, abbr, or name)
- --log FILE: append the live stream to a file
- --dump FILE: write full game log for the selected game and exit

## Notes

- Data comes from MLB StatsAPI schedule and the v1.1 live feed
- Uses If-None-Match to avoid reprinting unchanged states

## Roadmap

- ASCII line score per inning (lightweight)
- RISP highlighting and men-on-base summary lines
- Opponent filter improvements when multiple games in a day
- Config file for defaults and cached team map
- Better historical dump by team/date range


