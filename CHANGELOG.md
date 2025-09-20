## Changelog

All notable changes to this project will be documented in this file.

Format based on Keep a Changelog.

## [0.4.0] - 2025-09-20

### Visual Improvements
- **Enhanced scoring play emphasis** - Home runs get 🔥 fire emojis with ALL CAPS text (bright red)
- **RBI play highlighting** - Standard RBI plays get ⚡ lightning bolts (bright green)
- **Big RBI moments** - 3+ RBI plays get 💥 explosion emojis (bright yellow)
- **Improved base runner display** - Shows `[1B:Lindor 2B:Soto 3B:○]` with actual player names instead of just `◉◉○`
- **Cleaner pitch count format** - Integrated `(2-1, 5p)` instead of separate `(2-1) [5p]` display

### 🐛 Bug Fixes
- **Fixed scoreboard spam** - Eliminated repeated scoreboard printing when no new plays occur
- **Reduced polling noise** - Scoreboard now only prints on actual game state changes

### 🔧 Developer Notes
- Smart play condensation feature temporarily disabled due to grouping logic issues
- Ready for next phase of UX improvements (inning summaries, auto-verbosity)

## [0.3.0] - 2025-01-19

### 🏷️ Project Renamed
- **Package renamed** from `scorebug` to `utilityman` - the utility player for baseball fans!

### ✨ Major UI/UX Improvements
- **Clean game headers** - Organized format with Teams/Pitchers/Venue/Time sections
- **Consistent team icons** - Uses standard ⚾ baseball emoji for all teams
- **Improved game flow** - "⚾ Game On!" header appears first when joining live games
- **Cleaner scoreboard** - Simplified format without misaligned ASCII borders
- **Better play updates** - Added 📝 marker for finalized/corrected plays to reduce chronological confusion
- **Enhanced game status** - "🎯 Game Starting Soon!" for pregame, "🏁 Game Over!" for finals

### 🎨 Visual Polish
- Shorter separator lines (48 vs 72 chars) for cleaner display  
- Stadium emoji (🏟️) for scoreboard header
- Venue location with 📍 icon
- Start time with 🕐 icon
- More readable team stats formatting
- Professional, consistent emoji usage throughout

## [0.2.0] - 2025-09-07

- Added timezone override `--tz` with local tz detection
- Added team ID caching under `~/.utilityman/teams-<season>.json`
- RISP highlighting (yellow) on plays with runners in scoring position
- Optional inning line score via `--line-score`
- Periodic scoreboard snapshots via `--box-interval N` (minutes)
- Quiet/verbose modes: `--quiet` (scoreboard only), `--verbose` (pitches/runners)
- Base-state fallback from live linescore when play runners missing
- Pregame cleanup: ignore StatusChange, show Probables with local start time
- No-live-game summary: print last final and next scheduled
- Docs: expanded README CLI reference; added PUBLISH.md and publish script

## [0.1.0] - 2025-09-06

- Initial CLI with live play-by-play
- Schedule lookup, prompts, and team parsing
- Scoreboard, inning banners, base runners, counts, pitch count
- Scoring-only mode, opponent filter
- Logging: --log, --dump

