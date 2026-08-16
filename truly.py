import json
import os
import socket
import threading
import time
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from engine.biomechanical import BiomechanicalEngine, ProfileFingerprint
from mouse.makcu import makcu_controller
from profiles.manager import (
    DEFAULT_PROFILE_COUNT,
    export_profile,
    import_profile,
    init_default_profiles,
    list_profiles,
    read_profile,
    write_profile,
)

CONFIG_DIR = os.path.join(os.path.dirname(__file__), "configs")
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(CONFIG_DIR, exist_ok=True)

DEFAULT_CONFIG_FILE = "r6.json"
VALID_TOGGLE_BUTTONS = ["MMB", "M4", "M5"]
VALID_INTERLOCK_BUTTONS = ["MMB", "M4", "M5", "LMB", "RMB"]

init_default_profiles()


class GunConfig(BaseModel):
    gun_name: str = Field(..., min_length=1, max_length=50, pattern=r"^[a-zA-Z0-9_\- ]+$")
    pull_down_value: float = Field(..., ge=0, le=300)
    horizontal_value: float = Field(default=0, ge=-300, le=300)
    horizontal_delay_ms: int = Field(default=500, ge=0, le=5000)
    horizontal_duration_ms: int = Field(default=2000, ge=0, le=10000)


class ProfileUpdate(BaseModel):
    name: str | None = None
    pull_down: float | None = Field(default=None, ge=0, le=300)
    horizontal: float | None = Field(default=None, ge=-300, le=300)
    horizontal_delay_ms: int | None = Field(default=None, ge=0, le=5000)
    horizontal_duration_ms: int | None = Field(default=None, ge=0, le=10000)
    tap_strength: float | None = Field(default=None, ge=0.1, le=1.0)
    tap_threshold_ms: int | None = Field(default=None, ge=50, le=400)
    hold_ramp_ms: int | None = Field(default=None, ge=0, le=1000)
    spray_ramp_ms: int | None = Field(default=None, ge=0, le=2000)
    tremor_hz: float | None = Field(default=None, ge=8.0, le=12.0)
    fatigue_rate: float | None = Field(default=None, ge=0.005, le=0.1)
    phenotype: str | None = None
    vertical_asymmetry: float | None = Field(default=None, ge=1.15, le=1.25)
    humanization_intensity: float | None = Field(default=None, ge=0.5, le=3.0)
    timing_variance: float | None = Field(default=None, ge=0.0, le=1.0)
    interlock_primary: str | None = None
    interlock_secondary: str | None = None
    interlock_required: bool | None = None
    secondary_slot: int | None = Field(default=None, ge=1, le=DEFAULT_PROFILE_COUNT)


def get_config_path(filename: str) -> str:
    return os.path.join(CONFIG_DIR, filename)


def read_configs(config_file: str | None = None) -> dict:
    if config_file is None:
        config_file = DEFAULT_CONFIG_FILE
    config_path = get_config_path(config_file)
    if not os.path.exists(config_path):
        return {}
    try:
        with open(config_path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"[CONFIG] Error reading configs: {e}")
        return {}


def write_configs(configs: dict, config_file: str | None = None) -> None:
    if config_file is None:
        config_file = DEFAULT_CONFIG_FILE
    config_path = get_config_path(config_file)
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(configs, f, indent=4)
    except OSError as e:
        print(f"[CONFIG] Error writing configs: {e}")


def list_config_files() -> list[str]:
    try:
        return sorted(f for f in os.listdir(CONFIG_DIR) if f.endswith(".json"))
    except OSError:
        return []


class AppState:
    def __init__(self):
        self.lock = threading.Lock()
        self.is_enabled = False
        self.toggle_button = "M5"
        self.current_config_file = DEFAULT_CONFIG_FILE
        self.active_slot = 1
        self.secondary_slot = 2

        self.active_pull_down_value = 50.0
        self.active_horizontal_value = 0.0
        self.horizontal_delay_ms = 500
        self.horizontal_duration_ms = 2000

        self.tap_strength = 0.5
        self.tap_threshold_ms = 180
        self.hold_ramp_ms = 200
        self.spray_ramp_ms = 300

        self.interlock_primary = "M4"
        self.interlock_secondary = "M5"
        self.interlock_required = False
        self.interlock_held = False
        self.output_strength = 0.0

        self.tremor_hz = 10.0
        self.fatigue_rate = 0.025
        self.phenotype = "Conservative"
        self.vertical_asymmetry = 1.2
        self.humanization_intensity = 1.5
        self.timing_variance = 0.35
        self.profile_seed = 1001

        self._load_active_profile()

    def _load_active_profile(self) -> None:
        p = read_profile(self.active_slot)
        self._apply_profile_dict(p)

    def _apply_profile_dict(self, p: dict) -> None:
        self.active_pull_down_value = float(p.get("pull_down", 50))
        self.active_horizontal_value = float(p.get("horizontal", 0))
        self.horizontal_delay_ms = int(p.get("horizontal_delay_ms", 500))
        self.horizontal_duration_ms = int(p.get("horizontal_duration_ms", 2000))
        self.tap_strength = float(p.get("tap_strength", 0.5))
        self.tap_threshold_ms = int(p.get("tap_threshold_ms", 180))
        self.hold_ramp_ms = int(p.get("hold_ramp_ms", 200))
        self.spray_ramp_ms = int(p.get("spray_ramp_ms", 300))
        self.interlock_primary = p.get("interlock_primary", "M4")
        self.interlock_secondary = p.get("interlock_secondary", "M5")
        self.interlock_required = bool(p.get("interlock_required", False))
        self.secondary_slot = int(p.get("secondary_slot", 2))
        self.tremor_hz = float(p.get("tremor_hz", 10.0))
        self.fatigue_rate = float(p.get("fatigue_rate", 0.025))
        self.phenotype = p.get("phenotype", "Conservative")
        self.vertical_asymmetry = float(p.get("vertical_asymmetry", 1.2))
        self.humanization_intensity = float(p.get("humanization_intensity", 1.5))
        self.timing_variance = float(p.get("timing_variance", 0.35))
        self.profile_seed = int(p.get("seed", 1000 + self.active_slot * 137))

    def fingerprint(self) -> ProfileFingerprint:
        return ProfileFingerprint(
            seed=self.profile_seed,
            tremor_hz=self.tremor_hz,
            fatigue_rate=self.fatigue_rate,
            phenotype=self.phenotype,
            vertical_asymmetry=self.vertical_asymmetry,
            humanization_intensity=self.humanization_intensity,
            timing_variance=self.timing_variance,
        )

    def update_from_ws(self, msg: dict) -> None:
        with self.lock:
            for key, attr, conv in (
                ("pull_down", "active_pull_down_value", float),
                ("horizontal", "active_horizontal_value", float),
                ("horizontal_delay_ms", "horizontal_delay_ms", int),
                ("horizontal_duration_ms", "horizontal_duration_ms", int),
                ("tap_strength", "tap_strength", float),
                ("tap_threshold_ms", "tap_threshold_ms", int),
                ("hold_ramp_ms", "hold_ramp_ms", int),
                ("spray_ramp_ms", "spray_ramp_ms", int),
                ("tremor_hz", "tremor_hz", float),
                ("fatigue_rate", "fatigue_rate", float),
                ("phenotype", "phenotype", str),
                ("vertical_asymmetry", "vertical_asymmetry", float),
                ("humanization_intensity", "humanization_intensity", float),
                ("timing_variance", "timing_variance", float),
                ("interlock_primary", "interlock_primary", str),
                ("interlock_secondary", "interlock_secondary", str),
                ("interlock_required", "interlock_required", bool),
                ("active_slot", "active_slot", int),
                ("secondary_slot", "secondary_slot", int),
            ):
                if key in msg:
                    setattr(self, attr, conv(msg[key]))

    def get_motion_params(self) -> dict:
        with self.lock:
            return {
                "pull_down": self.active_pull_down_value,
                "horizontal": self.active_horizontal_value,
                "horizontal_delay_ms": self.horizontal_delay_ms,
                "horizontal_duration_ms": self.horizontal_duration_ms,
                "tap_strength": self.tap_strength,
                "tap_threshold_ms": self.tap_threshold_ms,
                "hold_ramp_ms": self.hold_ramp_ms,
                "spray_ramp_ms": self.spray_ramp_ms,
                "interlock_primary": self.interlock_primary,
                "interlock_secondary": self.interlock_secondary,
            }

    def set_interlock_held(self, held: bool) -> None:
        with self.lock:
            self.interlock_held = held

    def set_output_strength(self, s: float) -> None:
        with self.lock:
            self.output_strength = s

    def get_enabled(self) -> bool:
        with self.lock:
            return self.is_enabled

    def toggle_enabled(self) -> bool:
        with self.lock:
            self.is_enabled = not self.is_enabled
            return self.is_enabled

    def set_toggle_button(self, button: str) -> str | None:
        with self.lock:
            if button in VALID_TOGGLE_BUTTONS:
                self.toggle_button = button
                return self.toggle_button
            return None

    def get_toggle_button(self) -> str:
        with self.lock:
            return self.toggle_button

    def set_current_config_file(self, filename: str) -> str:
        with self.lock:
            if not filename.endswith(".json"):
                filename = filename + ".json"
            self.current_config_file = filename
            return filename

    def get_current_config_file(self) -> str:
        with self.lock:
            return self.current_config_file

    def get_status(self) -> dict:
        with self.lock:
            return {
                "is_enabled": self.is_enabled,
                "toggle_button": self.toggle_button,
                "pull_down": self.active_pull_down_value,
                "horizontal": self.active_horizontal_value,
                "horizontal_delay_ms": self.horizontal_delay_ms,
                "horizontal_duration_ms": self.horizontal_duration_ms,
                "current_config_file": self.current_config_file,
                "active_slot": self.active_slot,
                "secondary_slot": self.secondary_slot,
                "tap_strength": self.tap_strength,
                "tap_threshold_ms": self.tap_threshold_ms,
                "hold_ramp_ms": self.hold_ramp_ms,
                "spray_ramp_ms": self.spray_ramp_ms,
                "interlock_primary": self.interlock_primary,
                "interlock_secondary": self.interlock_secondary,
                "interlock_required": self.interlock_required,
                "interlock_held": self.interlock_held,
                "output_strength": self.output_strength,
                "tremor_hz": self.tremor_hz,
                "phenotype": self.phenotype,
                "humanization_intensity": self.humanization_intensity,
                "timing_variance": self.timing_variance,
            }


app_state = AppState()
motion_engine = BiomechanicalEngine(app_state.fingerprint())


def mouse_control_loop() -> None:
    makcu_controller.StartButtonListener()
    toggle_was_pressed = False
    lmb_hold_start: float | None = None
    lmb_was_down = False
    last_fp_key: tuple | None = None

    while True:
        if not makcu_controller.is_connected():
            time.sleep(0.5)
            makcu_controller.connect()
            continue

        params = app_state.get_motion_params()
        fp = app_state.fingerprint()
        fp_key = (fp.seed, fp.tremor_hz, fp.humanization_intensity, fp.timing_variance, fp.phenotype)
        if fp_key != last_fp_key:
            motion_engine.set_fingerprint(fp)
            last_fp_key = fp_key

        btn = app_state.get_toggle_button()
        toggle_pressed = makcu_controller.get_button_state(btn)
        if toggle_pressed and not toggle_was_pressed:
            app_state.toggle_enabled()
        toggle_was_pressed = toggle_pressed

        interlock = makcu_controller.get_interlock_held(
            params["interlock_primary"],
            params["interlock_secondary"],
        )
        app_state.set_interlock_held(interlock)

        lmb_down = makcu_controller.get_button_state("LMB")
        with app_state.lock:
            need_interlock = app_state.interlock_required
        enabled = app_state.get_enabled() and (interlock if need_interlock else True)

        dt, skip_tick = motion_engine.next_interval()

        if enabled and lmb_down:
            if not lmb_was_down:
                motion_engine.begin_activation()
            lmb_was_down = True

            now = time.time()
            if lmb_hold_start is None:
                lmb_hold_start = now

            hold_ms = (now - lmb_hold_start) * 1000
            strength = motion_engine.compute_strength(
                hold_ms,
                params["tap_threshold_ms"],
                params["tap_strength"],
                params["hold_ramp_ms"],
                params["spray_ramp_ms"],
            )
            app_state.set_output_strength(strength)

            if not skip_tick:
                pull_value = params["pull_down"] * strength
                target_y = pull_value / 5.0 if pull_value > 0 else 0.0

                target_x = 0.0
                delay = params["horizontal_delay_ms"]
                duration = params["horizontal_duration_ms"]
                if hold_ms >= delay and (duration == 0 or hold_ms <= delay + duration):
                    h_value = params["horizontal"] * strength
                    target_x = h_value / 5.0

                ix, iy = motion_engine.step(target_x, target_y, strength, engaged=True, dt=dt)
                if ix or iy:
                    makcu_controller.simple_move_mouse(ix, iy)
        else:
            if lmb_was_down:
                motion_engine.end_activation()
            lmb_was_down = False
            lmb_hold_start = None
            app_state.set_output_strength(0.0)
            motion_engine.step(0, 0, 0, engaged=False, dt=dt)

        time.sleep(dt)


@asynccontextmanager
async def lifespan(app: FastAPI):
    thread = threading.Thread(target=mouse_control_loop, daemon=True)
    thread.start()
    yield


app = FastAPI(title="PulseMotion", lifespan=lifespan)


def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


@app.get("/access")
async def access_urls():
    ip = get_local_ip()
    port = int(os.environ.get("PORT", "8000"))
    return {
        "local": f"http://localhost:{port}",
        "lan": f"http://{ip}:{port}",
    }


@app.get("/manifest.json")
async def manifest():
    return JSONResponse({
        "name": "PulseMotion",
        "short_name": "PulseMotion",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0a0a0f",
        "theme_color": "#6c5ce7",
    })


@app.get("/", response_class=HTMLResponse)
async def index():
    path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(path):
        return FileResponse(path)
    return HTMLResponse("<h1>PulseMotion</h1><p>static/index.html missing</p>")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                app_state.update_from_ws(msg)
            except (json.JSONDecodeError, ValueError, TypeError):
                pass
    except WebSocketDisconnect:
        pass


@app.get("/status")
async def get_status():
    return app_state.get_status()


@app.post("/toggle")
async def toggle_status():
    return {"is_enabled": app_state.toggle_enabled()}


class ToggleButtonConfig(BaseModel):
    button: str


@app.post("/toggle-button")
async def set_toggle_button(config: ToggleButtonConfig):
    result = app_state.set_toggle_button(config.button)
    if result is None:
        raise HTTPException(status_code=400, detail=f"Invalid button. Must be one of: {VALID_TOGGLE_BUTTONS}")
    return {"toggle_button": result}


@app.get("/profiles")
async def get_profiles():
    profiles = list_profiles()
    return [{"slot": i + 1, **p} for i, p in enumerate(profiles)]


@app.get("/profiles/{slot}")
async def get_profile(slot: int):
    if slot < 1 or slot > DEFAULT_PROFILE_COUNT:
        raise HTTPException(status_code=404, detail="Invalid profile slot")
    return {"slot": slot, **read_profile(slot)}


@app.put("/profiles/{slot}")
async def update_profile(slot: int, body: ProfileUpdate):
    if slot < 1 or slot > DEFAULT_PROFILE_COUNT:
        raise HTTPException(status_code=404, detail="Invalid profile slot")
    data = read_profile(slot)
    data.update(body.model_dump(exclude_none=True))
    write_profile(slot, data)
    if slot == app_state.active_slot:
        app_state._apply_profile_dict(data)
        motion_engine.set_fingerprint(app_state.fingerprint())
    return {"slot": slot, **read_profile(slot)}


@app.get("/profiles/{slot}/export")
async def export_profile_file(slot: int):
    if slot < 1 or slot > DEFAULT_PROFILE_COUNT:
        raise HTTPException(status_code=404, detail="Invalid profile slot")
    path = os.path.join(CONFIG_DIR, f"_export_profile_{slot:02d}.json")
    export_profile(slot, path)
    return FileResponse(path, filename=f"pulsemotion_profile_{slot:02d}.json", media_type="application/json")


@app.post("/profiles/{slot}/import")
async def import_profile_file(slot: int, body: dict):
    if slot < 1 or slot > DEFAULT_PROFILE_COUNT:
        raise HTTPException(status_code=404, detail="Invalid profile slot")
    write_profile(slot, body)
    if slot == app_state.active_slot:
        app_state._apply_profile_dict(body)
        motion_engine.set_fingerprint(app_state.fingerprint())
    return {"slot": slot, **read_profile(slot)}


class ConfigFileRequest(BaseModel):
    filename: str


@app.get("/config-files")
async def get_config_files():
    return {"files": list_config_files(), "current": app_state.get_current_config_file()}


@app.post("/config-files")
async def create_config_file_action(req: ConfigFileRequest):
    filename = req.filename
    if not filename.endswith(".json"):
        filename += ".json"
    filepath = get_config_path(filename)
    if os.path.exists(filepath):
        raise HTTPException(status_code=400, detail="Config file already exists.")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump({}, f)
    return {"message": f"Config file '{filename}' created.", "files": list_config_files()}


@app.post("/config-files/switch")
async def switch_config_file(req: ConfigFileRequest):
    filename = req.filename if req.filename.endswith(".json") else req.filename + ".json"
    if not os.path.exists(get_config_path(filename)):
        raise HTTPException(status_code=404, detail="Config file not found.")
    app_state.set_current_config_file(filename)
    return {"current_config_file": filename, "guns": read_configs(filename)}


@app.delete("/config-files/{filename}")
async def delete_config_file_action(filename: str):
    if filename == DEFAULT_CONFIG_FILE:
        raise HTTPException(status_code=400, detail="Cannot delete default config.")
    filepath = get_config_path(filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Config file not found.")
    os.remove(filepath)
    return {"message": "Config file deleted.", "files": list_config_files()}


@app.get("/configs")
async def get_configs():
    return read_configs(app_state.get_current_config_file())


@app.post("/configs")
async def create_config(config: GunConfig):
    current_file = app_state.get_current_config_file()
    configs = read_configs(current_file)
    configs[config.gun_name] = {
        "pull_down": config.pull_down_value,
        "horizontal": config.horizontal_value,
        "horizontal_delay_ms": config.horizontal_delay_ms,
        "horizontal_duration_ms": config.horizontal_duration_ms,
    }
    write_configs(configs, current_file)
    return {"message": "Config saved successfully."}


@app.delete("/configs/{gun_name}")
async def delete_config(gun_name: str):
    current_file = app_state.get_current_config_file()
    configs = read_configs(current_file)
    if gun_name not in configs:
        raise HTTPException(status_code=404, detail="Config not found.")
    del configs[gun_name]
    write_configs(configs, current_file)
    return {"message": "Config deleted successfully."}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    ip = get_local_ip()
    print("\n  PulseMotion Input Calibration Suite")
    print(f"  This PC:     http://localhost:{port}")
    print(f"  Phone/LAN:   http://{ip}:{port}")
    print("  Hold M4 + M5 (interlock) while firing for full compensation.\n")
    uvicorn.run(app, host="0.0.0.0", port=port)
