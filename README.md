# PulseMotion Input Calibration Suite

**Repo:** https://github.com/alexg0dev/pulsemotion

Local web app for input calibration with biomechanical motion modeling, 40 profiles, tap-vs-hold compensation, and phone-friendly LAN access.

---

## Run on a different PC (full guide)

### 1. Clone the repo

**Option A — Git (recommended)**

```bash
git clone https://github.com/alexg0dev/pulsemotion.git
cd pulsemotion
```

**Option B — Download ZIP**

1. Open https://github.com/alexg0dev/pulsemotion  
2. Click **Code → Download ZIP**  
3. Extract the folder anywhere (e.g. `C:\pulsemotion`)

### 2. Install Python

- Download **Python 3.10+** from https://www.python.org/downloads/  
- During install, check **"Add Python to PATH"**

### 3. Install dependencies

**Windows — double-click:**

```
setup.bat
```

**Or in terminal:**

```bash
pip install -r requirements.txt
```

### 4. Allow firewall (Windows, run PowerShell as admin)

```powershell
New-NetFirewallRule -DisplayName "PulseMotion" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8000-8020
```

(Ports 8000–8020 covers auto-fallback if 8000 is busy.)

### 5. Connect Makcu

Plug in your Makcu device before starting. The app retries connection automatically if not found at first.

### 6. Start the app

**Windows — double-click:**

```
start.bat
```

**Or in terminal:**

```bash
python truly.py
```

Keep the console window **open** while using PulseMotion.

### 7. Open the UI

The console prints URLs like:

```
This PC:     http://localhost:8000
Phone/LAN:   http://192.168.x.x:8000
```

- **Same PC:** open `http://localhost:8000` (or whatever port it shows)  
- **Phone / other device:** same Wi‑Fi → open the **Phone/LAN** URL

---

## What's included in the repo

| Folder / file | Purpose |
|---------------|---------|
| `truly.py` | Main app (FastAPI server + mouse loop) |
| `start.bat` | Launch on Windows |
| `setup.bat` | First-time install on Windows |
| `engine/` | Biomechanical motion engine |
| `profiles/` | 40 local calibration profiles (JSON) |
| `configs/` | Gun presets (R6, Rust, etc.) |
| `static/` | Web UI |
| `mouse/` | Makcu driver wrapper |
| `requirements.txt` | Python dependencies |

Everything you need is in the repo — no separate downloads.

---

## Features

- **Tap vs hold** — taps ~50% compensation, hold ramps to 100%
- **Humanization** — tremor, drift, variable timing (Motion tab → intensity slider)
- **40 profiles** — import/export JSON, scroll to switch in UI
- **Gun presets** — per-weapon configs under Guns tab
- **Optional interlock** — M4 + M5 must be held when enabled

---

## Tap / Hold behavior

| Action | Effect |
|--------|--------|
| Quick tap (< `tap_threshold_ms`) | `tap_strength` × pull (default 50%) |
| Hold past threshold | Ramps to 100% over `hold_ramp_ms` |
| Sustained spray | Fine ramp via `spray_ramp_ms` |

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Window closes instantly | Port 8000 busy — use `start.bat`; app auto-picks next free port |
| `Python not found` | Reinstall Python with **Add to PATH** checked |
| `Makcu device not found` | Plug in Makcu, install Makcu drivers, restart app |
| Phone can't connect | Same Wi‑Fi, run firewall rule, use **Phone/LAN** URL from console |
| Wrong port in browser | Read the port number printed at startup (may be 8001, 8002…) |

---

## Controls

- **Toggle key** (M4/M5/MMB): Enable/disable system  
- **LMB**: Fire — strength depends on tap vs hold  
- **Interlock** (optional): Both side buttons held while firing  

---

## Sync settings between PCs

Copy these folders to move your setup:

- `profiles/` — calibration profiles  
- `configs/` — gun presets  

Or use **Import/Export** in the web UI (Profiles tab).
