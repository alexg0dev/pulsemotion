"""Local profile storage — 40 portable JSON presets, no cloud."""

from __future__ import annotations

import json
import os
import shutil
from typing import Any

PROFILES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "profiles")
DEFAULT_PROFILE_COUNT = 40

DEFAULT_PROFILE_TEMPLATE = {
    "name": "Profile",
    "seed": 1000,
    "tremor_hz": 10.0,
    "fatigue_rate": 0.025,
    "phenotype": "Conservative",
    "vertical_asymmetry": 1.2,
    "humanization_intensity": 1.5,
    "timing_variance": 0.35,
    "pull_down": 50.0,
    "horizontal": 0.0,
    "horizontal_delay_ms": 500,
    "horizontal_duration_ms": 2000,
    "tap_strength": 0.5,
    "tap_threshold_ms": 180,
    "hold_ramp_ms": 200,
    "spray_ramp_ms": 300,
    "interlock_primary": "M4",
    "interlock_secondary": "M5",
    "interlock_required": False,
    "scroll_up_action": "primary",
    "scroll_down_action": "secondary",
    "primary_slot": 1,
    "secondary_slot": 2,
    "enabled": False,
}


def ensure_profiles_dir() -> str:
    os.makedirs(PROFILES_DIR, exist_ok=True)
    return PROFILES_DIR


def profile_path(slot: int) -> str:
    ensure_profiles_dir()
    return os.path.join(PROFILES_DIR, f"profile_{slot:02d}.json")


def default_profile(slot: int) -> dict[str, Any]:
    p = dict(DEFAULT_PROFILE_TEMPLATE)
    p["name"] = f"Profile {slot:02d}"
    p["seed"] = 1000 + slot * 137
    p["tremor_hz"] = 8.5 + (slot % 12) * 0.2
    p["fatigue_rate"] = 0.015 + (slot % 10) * 0.002
    p["phenotype"] = "Aggressive" if slot % 3 == 0 else "Conservative"
    p["primary_slot"] = slot
    p["secondary_slot"] = min(slot + 1, DEFAULT_PROFILE_COUNT)
    p["pull_down"] = 30.0 + (slot % 20) * 4
    p["horizontal"] = ((slot % 7) - 3) * 2.0
    return p


def init_default_profiles(force: bool = False) -> None:
    ensure_profiles_dir()
    for i in range(1, DEFAULT_PROFILE_COUNT + 1):
        path = profile_path(i)
        if force or not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                json.dump(default_profile(i), f, indent=2)


def list_profiles() -> list[dict[str, Any]]:
    init_default_profiles()
    out = []
    for i in range(1, DEFAULT_PROFILE_COUNT + 1):
        out.append(read_profile(i))
    return out


def read_profile(slot: int) -> dict[str, Any]:
    path = profile_path(slot)
    if not os.path.exists(path):
        data = default_profile(slot)
        write_profile(slot, data)
        return data
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        merged = default_profile(slot)
        merged.update(data)
        return merged
    except (json.JSONDecodeError, OSError):
        return default_profile(slot)


def write_profile(slot: int, data: dict[str, Any]) -> None:
    if slot < 1 or slot > DEFAULT_PROFILE_COUNT:
        raise ValueError(f"Profile slot must be 1–{DEFAULT_PROFILE_COUNT}")
    path = profile_path(slot)
    base = default_profile(slot)
    base.update(data)
    base["name"] = base.get("name") or f"Profile {slot:02d}"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(base, f, indent=2)


def duplicate_profile(src_slot: int, dst_slot: int) -> dict[str, Any]:
    data = read_profile(src_slot)
    data["name"] = f"{data.get('name', 'Profile')} (copy)"
    write_profile(dst_slot, data)
    return read_profile(dst_slot)


def export_profile(slot: int, dest_path: str) -> None:
    data = read_profile(slot)
    with open(dest_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def import_profile(slot: int, src_path: str) -> dict[str, Any]:
    with open(src_path, encoding="utf-8") as f:
        data = json.load(f)
    write_profile(slot, data)
    return read_profile(slot)


def backup_all(dest_dir: str) -> None:
    os.makedirs(dest_dir, exist_ok=True)
    for i in range(1, DEFAULT_PROFILE_COUNT + 1):
        shutil.copy2(profile_path(i), os.path.join(dest_dir, f"profile_{i:02d}.json"))
