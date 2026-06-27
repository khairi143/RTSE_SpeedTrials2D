# Score Tracker — Design

## Purpose
A standalone terminal utility for logging the score of each test run of the car (separate from the simulator/controller code), so runs can be tracked and compared over time.

## Scope
- New file: `score_tracker.py` at the repo root.
- Not integrated with `sample_drive.py` or the simulator — purely a manual data-entry/logging tool run on its own.

## Data
- Two columns: `run` (int, auto-incrementing) and `score` (numeric).
- Persisted to `scores.csv` at the repo root, with header `run,score`.

## Behavior
1. On startup, load `scores.csv` if it exists and print the existing table. Determine the next run number as `(max existing run) + 1`, or `1` if no file/rows exist.
2. Loop:
   - Prompt: `Enter score for run N (or q to quit): `
   - If input is `q` or `quit` (case-insensitive), exit cleanly.
   - Otherwise, validate the input parses as a number (int or float). On invalid input, print an error and re-prompt without advancing the run number.
   - On valid input, append the row to the in-memory table, write the full table to `scores.csv` immediately (so no data is lost if the terminal is closed), reprint the updated table, and advance to the next run number.
3. On exit (via `q`/`quit`), print a short confirmation that data was saved to `scores.csv`.

## Error handling
- Invalid (non-numeric) score input: print an error message, re-prompt for the same run number.
- Missing/corrupt `scores.csv` on load: treat as empty table and start fresh (don't crash).

## Out of scope
- No editing/deleting past rows, no GUI, no curses-based live table, no integration with the simulator.
