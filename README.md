# PulseMotion Input Calibration Suite

Local web app for calibrating input compensation with biomechanical motion modeling, 40 portable profiles, and phone-friendly LAN access.

## Features

- **Tap vs hold**: Quick LMB taps apply ~50% compensation (configurable). Sustained hold ramps to 100% over `hold_ramp_ms`, with an optional spray ramp for full-auto.
- **Biomechanical engine**: Minimum-jerk trajectories, spring-damper dynamics, seeded Simplex/OU noise (macro drift, micro correction, physiological tremor).
- **40 local profiles**: Stored as JSON in `profiles/` — import, export, duplicate, no accounts or cloud.
- **Scroll profile switching**: In the web UI, scroll up/down to switch primary/secondary profiles.
- **Safety interlock** (optional): Hold M4 + M5 while firing when enabled.
- **Gun presets**: Original per-game gun configs still work under the Guns tab.
- **Phone access**: Open the LAN URL shown at startup on any device on the same Wi‑Fi.

## Requirements

- Python 3.10+
- Makcu device

## Setup

```bash
pip install -r requirements.txt
```

Allow port 8000 through Windows Firewall (PowerShell as admin):

```powershell
New-NetFirewallRule -DisplayName "PulseMotion Port 8000" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8000
```

## Usage

```bash
python truly.py
```

Console output:

```
PulseMotion Input Calibration Suite
This PC:     http://localhost:8000
Phone/LAN:   http://192.168.x.x:8000
```

Open either URL in a browser. Add the LAN link to your phone home screen for quick access (PWA manifest included).

## Tap / Hold behavior

| Action | Effect |
|--------|--------|
| Quick tap (< `tap_threshold_ms`) | `tap_strength` × pull (default 50%) |
| Hold past threshold | Ramps from tap strength → 100% over `hold_ramp_ms` |
| Sustained spray | Optional fine ramp via `spray_ramp_ms` |

Live output strength is shown in the UI meter while firing.

## Profiles

Each profile (`profiles/profile_01.json` … `profile_40.json`) stores calibration values, tremor fingerprint, interlock buttons, and tap/hold settings. Copy the `profiles/` folder to back up or move to another PC.

## Controls

- **Toggle key** (M4/M5/MMB): Enable/disable the system
- **Interlock** (optional): Both side buttons must be held to compensate
- **LMB**: Fire — compensation strength depends on tap vs hold

## Legacy gun configs

Game configs remain in `configs/` (e.g. `r6.json`, `rust.json`).
