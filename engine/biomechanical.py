"""Integrated biomechanical motion engine for human-grade mouse compensation."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

from engine.noise import (
    BandLimitedTremor,
    HumanTickScheduler,
    OrnsteinUhlenbeck,
    SeededSimplex1D,
    SeededSimplex2D,
)
from engine.trajectory import SpringDamper, fitts_timing_variance


@dataclass
class ProfileFingerprint:
    seed: int = 42
    tremor_hz: float = 10.0
    fatigue_rate: float = 0.025
    phenotype: str = "Conservative"
    vertical_asymmetry: float = 1.2
    humanization_intensity: float = 1.5
    timing_variance: float = 0.35

    @property
    def aggressive(self) -> bool:
        return self.phenotype.lower() == "aggressive"


class BiomechanicalEngine:
    """Human hand simulation layered on per-tick compensation deltas."""

    def __init__(self, fingerprint: ProfileFingerprint | None = None):
        self.fp = fingerprint or ProfileFingerprint()
        self._session_seed = self.fp.seed
        self._activation_idx = 0
        self._engaged = False
        self._start_time = time.perf_counter()
        self._init_subsystems(self._session_seed)

    def _init_subsystems(self, seed: int) -> None:
        aggressive = self.fp.aggressive
        self.spring_x = SpringDamper(stiffness=320.0, damping_ratio=0.72, aggressive=aggressive)
        self.spring_y = SpringDamper(stiffness=320.0, damping_ratio=0.72, aggressive=aggressive)
        self.macro = SeededSimplex2D(seed)
        self.macro_y = SeededSimplex2D(seed + 997)
        self.micro_x = OrnsteinUhlenbeck(seed + 11, theta=5.0, sigma=0.55, mu=0.0)
        self.micro_y = OrnsteinUhlenbeck(seed + 12, theta=5.0, sigma=0.55, mu=0.0)
        self.spray_wobble_x = OrnsteinUhlenbeck(seed + 13, theta=3.0, sigma=0.25, mu=0.0)
        self.spray_wobble_y = OrnsteinUhlenbeck(seed + 14, theta=3.0, sigma=0.22, mu=0.0)
        self.tremor_x = BandLimitedTremor(seed + 1, self.fp.tremor_hz)
        self.tremor_y = BandLimitedTremor(seed + 2, self.fp.tremor_hz + 0.35)
        self._ou_overcorrect = OrnsteinUhlenbeck(seed + 15, theta=1.5, sigma=0.55, mu=0.0)
        self._breath = SeededSimplex1D(seed + 16)
        self._tick_scheduler = HumanTickScheduler(seed + 17)
        self._accum_x = 0.0
        self._accum_y = 0.0
        self._engage_time: float | None = None
        self._activation_start: float = 0.0
        self._last_dir_change = 0.0
        self._prev_target_x = 0.0
        self._prev_target_y = 0.0
        self._fatigue = 0.0
        self._gain = 1.0
        self._sustained_error = 0.0
        self._latency_buffer: list[tuple[float, float, float]] = []
        self._spray_drift_h = 0.0
        self.last_move = (0, 0)
        self.last_raw_target = (0.0, 0.0)

    def set_fingerprint(self, fp: ProfileFingerprint) -> None:
        self.fp = fp
        self.tremor_x = BandLimitedTremor(self._session_seed + 1, fp.tremor_hz)
        self.tremor_y = BandLimitedTremor(self._session_seed + 2, fp.tremor_hz + 0.35)
        self._tick_scheduler = HumanTickScheduler(self._session_seed + 17)

    def begin_activation(self) -> None:
        self._activation_idx += 1
        t_ns = time.perf_counter_ns()
        mix = (self.fp.seed * 7919 + self._activation_idx * 104729 + (t_ns % 1_000_000_007)) & 0xFFFFFFFF
        self._session_seed = mix
        self._init_subsystems(mix)
        self._activation_start = self._elapsed()
        self._spray_drift_h = 0.0
        self._engage_time = time.perf_counter()
        self._engaged = True
        self._fatigue = 0.0
        self._gain = 1.0

    def end_activation(self) -> None:
        self._engaged = False
        self._engage_time = None
        self.spring_x.set_target(0.0)
        self.spring_y.set_target(0.0)

    def next_interval(self) -> tuple[float, bool]:
        return self._tick_scheduler.next_delay(
            base_ms=10.0,
            variance=self.fp.timing_variance * self.fp.humanization_intensity * 0.5,
        )

    def _elapsed(self) -> float:
        return time.perf_counter() - self._start_time

    def _intensity(self) -> float:
        return max(0.5, min(3.0, self.fp.humanization_intensity))

    def _activation_factor(self) -> float:
        if not self._engaged or self._engage_time is None:
            return 1.0
        ms = (time.perf_counter() - self._engage_time) * 1000
        hi = self._intensity()
        if ms < 200:
            return 0.75 + 0.25 * (ms / 200.0) + self._breath.sample(ms * 0.003) * 0.02 * hi
        return 1.0 + self._breath.sample(self._elapsed() * 0.08) * 0.02 * hi

    def compute_strength(
        self,
        hold_ms: float,
        tap_threshold_ms: float,
        tap_strength: float,
        hold_ramp_ms: float,
        spray_ramp_ms: float = 300.0,
    ) -> float:
        if hold_ms <= 0:
            return 0.0
        hi = self._intensity()
        breath = 1.0 + self._breath.sample(hold_ms * 0.002 + self._activation_start) * 0.03 * hi
        if hold_ms < tap_threshold_ms:
            return min(1.0, tap_strength * breath)
        if hold_ramp_ms <= 0:
            base = 1.0
        else:
            ramp_t = min(1.0, (hold_ms - tap_threshold_ms) / hold_ramp_ms)
            s = ramp_t * ramp_t * (3.0 - 2.0 * ramp_t)
            base = tap_strength + (1.0 - tap_strength) * s
        if spray_ramp_ms > 0 and hold_ms > tap_threshold_ms + hold_ramp_ms:
            spray_t = min(1.0, (hold_ms - tap_threshold_ms - hold_ramp_ms) / spray_ramp_ms)
            s = spray_t * spray_t * (3.0 - 2.0 * spray_t)
            base *= 0.92 + 0.08 * s
        fatigue_dip = 1.0 - self._fatigue * 0.04 * hi
        return min(1.0, max(0.0, base * breath * fatigue_dip))

    def _neural_latency_delay(self, tx: float, ty: float, now: float, dt: float) -> tuple[float, float]:
        self._latency_buffer.append((now, tx, ty))
        delay_s = 0.012 + abs(self._ou_overcorrect.step(dt)) * 0.025
        cutoff = now - delay_s
        out_x, out_y = tx, ty
        while self._latency_buffer and self._latency_buffer[0][0] < cutoff:
            _, out_x, out_y = self._latency_buffer.pop(0)
        if len(self._latency_buffer) > 6:
            self._latency_buffer.pop(0)
        return out_x, out_y

    def step(
        self,
        target_dx: float,
        target_dy: float,
        strength: float,
        engaged: bool,
        dt: float = 0.01,
    ) -> tuple[int, int]:
        """target_dx/dy = desired pixels this tick (already strength-scaled)."""
        if strength <= 0 or not engaged:
            return 0, 0

        now = self._elapsed()
        hi = self._intensity()
        act = self._activation_factor()
        eff = strength * act

        self.last_raw_target = (target_dx, target_dy)

        wx = self.spray_wobble_x.step(dt) * 0.04 * hi
        wy = self.spray_wobble_y.step(dt) * 0.035 * hi
        tx = target_dx * (1.0 + wx) * eff
        ty = target_dy * (1.0 + wy) * eff * self.fp.vertical_asymmetry

        if abs(tx - self._prev_target_x) > 0.4 or abs(ty - self._prev_target_y) > 0.4:
            self._last_dir_change = now
            err = math.hypot(tx - self._prev_target_x, ty - self._prev_target_y)
            if err > 1.5 and abs(self._ou_overcorrect.step(dt)) > 0.32:
                boost = 1.06 + abs(self._ou_overcorrect.step(dt)) * 0.05
                tx *= boost
                ty *= boost
        self._prev_target_x = tx
        self._prev_target_y = ty

        self._fatigue = min(1.0, self._fatigue + self.fp.fatigue_rate * dt)
        self._spray_drift_h += self.micro_x.step(dt) * 0.0015 * hi

        jitter = fitts_timing_variance(math.hypot(tx, ty)) * hi * 0.5
        tx += self._spray_drift_h
        delayed_x, delayed_y = self._neural_latency_delay(tx, ty, now, dt)

        self.spring_x.set_target(delayed_x)
        self.spring_y.set_target(delayed_y)
        sx = self.spring_x.step(dt)
        sy = self.spring_y.step(dt)

        blend = 0.35
        base_x = delayed_x * (1.0 - blend) + sx * blend
        base_y = delayed_y * (1.0 - blend) + sy * blend

        macro_x = self.macro.sample(now * 0.12, self._fatigue * 8.0) * (0.25 + self._fatigue * 0.5)
        macro_y = self.macro_y.sample(now * 0.11, self._fatigue * 7.0) * (0.22 + self._fatigue * 0.45)

        post_change = now - self._last_dir_change
        micro_scale = (0.2 + max(0.0, 1.0 - post_change / 0.2) * 0.8) * max(abs(delayed_x), abs(delayed_y), 0.5)
        mx = self.micro_x.step(dt) * micro_scale * 0.08 * hi
        my = self.micro_y.step(dt) * micro_scale * 0.07 * hi

        power = max(abs(delayed_x), abs(delayed_y), 0.2) ** 0.55
        tremor_x = self.tremor_x.sample(now, hi) * power
        tremor_y = self.tremor_y.sample(now, hi) * power

        err_mag = abs(delayed_x - base_x) + abs(delayed_y - base_y)
        if err_mag > 0.4:
            self._sustained_error += dt
            if self._sustained_error > 0.07:
                self._gain = min(1.25, self._gain + dt * 0.4)
        else:
            self._sustained_error = 0.0
            self._gain = max(1.0, self._gain - dt * 0.3)

        total_x = (base_x + macro_x * 0.12 + mx + tremor_x) * self._gain
        total_y = (base_y + macro_y * 0.10 + my + tremor_y) * self._gain

        coupling = 0.18 + hi * 0.06
        shared = (macro_x + macro_y) * coupling * 0.15
        total_x += shared + sy * coupling * 0.25
        total_y += shared + sx * coupling * 0.22

        if abs(target_dy) > 0.05:
            floor_y = target_dy * eff * 0.88
            if abs(total_y) < abs(floor_y):
                total_y = floor_y + tremor_y * 0.5
        if abs(target_dx) > 0.05:
            floor_x = target_dx * eff * 0.88
            if abs(total_x) < abs(floor_x):
                total_x = floor_x + tremor_x * 0.5

        self._accum_x += total_x
        self._accum_y += total_y

        ix = int(self._accum_x) if abs(self._accum_x) >= 0.5 else 0
        iy = int(self._accum_y) if abs(self._accum_y) >= 0.5 else 0
        if ix:
            self._accum_x -= ix
        if iy:
            self._accum_y -= iy

        if ix == 0 and iy == 0 and (abs(target_dx) >= 0.5 or abs(target_dy) >= 0.5):
            if abs(self._accum_y) >= 0.25 and abs(target_dy) >= 0.5:
                iy = 1 if self._accum_y > 0 else -1
                self._accum_y -= iy
            elif abs(self._accum_x) >= 0.25 and abs(target_dx) >= 0.5:
                ix = 1 if self._accum_x > 0 else -1
                self._accum_x -= ix

        self.last_move = (ix, iy)
        return ix, iy
