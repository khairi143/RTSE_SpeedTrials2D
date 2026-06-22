# SpeedTrials2D — STONKER

A multi-threaded Python control client for the **SpeedTrials2D** self-driving simulation, built for **SECJ 4423 Real-Time Software Engineering, Assignment 2**. The controller mimics a uC/OS-II-style real-time task structure, decomposing autonomous driving into independently scheduled **Perceive → Compute → Actuate** threads.

## Team — STONKER

| Member | Primary contribution |
|---|---|
| Muhammad Khair Bin Romzi | Token decision logic (V1.0); Police Car event (V2.5); EV5 Golden Lane event (V3.0) |
| Ali Hariz Bin Anuari | Steering tap state machine (V1.0/V2.5); Chasing car detection (V2.5) |
| Muhammad Aqil Haziq Bin Zulkarnain | Police car / police red token detection (V2.5); shared-state integration |
| Muhammad Shahir Bin Roswadi | Colour-based token detection (V1.0) |

## What it does

`sample_drive.py` connects to the SpeedTrials2D Unity simulator over three TCP sockets — a front camera feed, a rear camera feed, and a control channel — decodes the live video, detects coloured tokens and in-game events, decides a steering direction, and sends a `(steering, acceleration)` command back to the simulator. Everything happens concurrently across five real-time threads sharing a single mutex-protected state dictionary.

## Architecture

| Task | Stage | Priority | Period | Phase |
|---|---|---|---|---|
| `ReadFrontCamera` | Perceive | HIGH | 5 ms | V1.0 |
| `ReadBackCamera` | Perceive | HIGH | 5 ms | V1.0 |
| `Processing` | Compute (Decide) | MEDIUM | 5 ms | V1.0 / V2.5 / V3.0 |
| `RearProcessing` | Compute (Decide) | MEDIUM | 5 ms | V2.5 |
| `SendControls` | Actuate | HIGH | 5 ms | V1.0 / V2.5 |

Each task is an instance of the `RTTask` class (a `threading.Thread` subclass) that sets its native OS thread priority via `ctypes.SetThreadPriority` and runs its target function on a fixed period, self-correcting for execution time each cycle. All inter-task communication goes through a single global `shared_data` dict guarded by one `threading.Lock` (`data_lock`) — no per-field locks or queues.

## Features by version

**V1.0 — Base pipeline**
- `detect_tokens()` — HSV colour detection for green/red/yellow tokens
- `decide_steering()` — priority-ordered steering decision (chase green → avoid red → dodge yellow)

**V2.5 — Stability & survival**
- Low-light detection and reverse-recovery
- Rear-camera chasing-car detection and max-acceleration escape
- Steering-tap state machine (125 ms pulse per lane change)
- Police Car event — detect an oversized red "ticket" token and a blue/purple police car, chase the ticket while swerving away from the car's lane

**V3.0 — Game-day events**
- EV5 Golden Lane event — detect the full-screen green flash, then tally close, high-confidence green token detections per lane over the 5-second event window (rather than trusting a single largest blob per frame, which is unreliable since green is also a normal token colour during regular play)

Every function and section in `sample_drive.py` is comment-tagged `[PERSON N VX.X - Feature Name]` so contributions and versions are traceable at a glance.

## Project structure

```
RTSE_SpeedTrials2D/
├── sample_drive.py          # Main control client (the only file the team modifies)
├── test_communication.py    # Provided connectivity sanity-check script
├── requirements.txt         # opencv-python, numpy, keyboard
└── SpeedTrials2D/           # Unity simulator build (SpeedTrials2D.exe)
```

## Running it

1. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
2. Launch the simulator: run `SpeedTrials2D/SpeedTrials2D.exe`.
3. Run the controller:
   ```
   python sample_drive.py
   ```
   It connects to the front camera (port 8080) and back camera (port 8082) as a client, and listens for the simulator's control connection on port 8081.

## Constraints

- `detect_tokens()` and `preprocess_frame()` are intentionally never modified when adding new features — all V2.5/V3.0 additions are implemented as new, separate functions that read from the same `shared_data` structure.
