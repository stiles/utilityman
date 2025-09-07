## Changelog

All notable changes to this project will be documented in this file.

Format based on Keep a Changelog.

## [0.2.0]

- Added timezone override `--tz` with local tz detection
- Added team ID caching under `~/.scorebug/teams-<season>.json`
- RISP highlighting (yellow) on plays with runners in scoring position
- Optional inning line score via `--line-score`
- Periodic scoreboard snapshots via `--box-interval N` (minutes)
- Quiet/verbose modes: `--quiet` (scoreboard only), `--verbose` (pitches/runners)
- Base-state fallback from live linescore when play runners missing
- Docs: expanded README CLI reference; added PUBLISH.md and publish script

## [0.1.0] - 2025-09-06

- Initial CLI with live play-by-play
- Schedule lookup, prompts, and team parsing
- Scoreboard, inning banners, base runners, counts, pitch count
- Scoring-only mode, opponent filter
- Logging: --log, --dump

