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
from engine.trajectory import SpringDamper, fitts_timing_variance, minimum_jerk_position


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
    """Human hand simulation: jerk paths, spring-damper, layered seeded noise."""

    def __init__(self, fingerprint: ProfileFingerprint | None = None):
        self.fp = fingerprint or ProfileFingerprint()
        self._session_seed = self.fp.seed
        self._activation_idx = 0
        self._engaged = False
        self._start_time = time.perf_counter()
        self._init_subsystems(self._session_seed)

    def _init_subsystems(self, seed: int) -> None:
        aggressive = self.fp.aggressive
        self.spring_x = SpringDamper(aggressive=aggressive)
        self.spring_y = SpringDamper(aggressive=aggressive)
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

    def set_fingerprint(self, fp: ProfileFingerprint) -> None:
        seed_changed = self.fp.seed != fp.seed
        self.fp = fp
        if seed_changed or self._session_seed == fp.seed:
            self._init_subsystems(self._session_seed)
        self.tremor_x = BandLimitedTremor(self._session_seed + 1, fp.tremor_hz)
        self.tremor_y = BandLimitedTremor(self._session_seed + 2, fp.tremor_hz + 0.35)
        self._tick_scheduler = HumanTickScheduler(self._session_seed + 17)

    def begin_activation(self) -> None:
        """New LMB press → unique session noise so no two sprays match."""
        self._activation_idx += 1
        t_ns = time.perf_counter_ns()
        mix = (
            self.fp.seed * 7919
            + self._activation_idx * 104729
            + (t_ns % 1_000_000_007)
        ) & 0xFFFFFFFF
        self._session_seed = mix
        self._init_subsystems(mix)
        self._activation_start = self._elapsed()
        self._spray_drift_h = 0.0
        self._engage_time = time.perf_counter()
        self._engaged = True

    def end_activation(self) -> None:
        self._engaged = False
        self._engage_time = None
        self.spring_x.set_target(0.0)
        self.spring_y.set_target(0.0)

    def next_interval(self) -> tuple[float, bool]:
        return self._tick_scheduler.next_delay(
            base_ms=10.0,
            variance=self.fp.timing_variance * self.fp.humanization_intensity,
        )

    def _elapsed(self) -> float:
        return time.perf_counter() - self._start_time

    def _intensity(self) -> float:
        return max(0.5, min(3.0, self.fp.humanization_intensity))

    def _activation_factor(self) -> float:
        if not self._engaged or self._engage_time is None:
            return 0.0
        ms = (time.perf_counter() - self._engage_time) * 1000
        hi = self._intensity()
        if ms < 200:
            base = 0.62 + 0.38 * (ms / 200.0)
            jitter = self._breath.sample(self._activation_start + ms * 0.003) * 0.04 * hi
            return base + jitter
        return 1.0 + self._breath.sample(self._elapsed() * 0.08) * 0.025 * hi

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
            base *= 0.9 + 0.1 * s
        fatigue_dip = 1.0 - self._fatigue * 0.06 * hi
        return min(1.0, max(0.0, base * breath * fatigue_dip))

    def _neural_latency_delay(self, tx: float, ty: float, now: float, dt: float) -> tuple[float, float]:
        self._latency_buffer.append((now, tx, ty))
        delay_s = 0.015 + abs(self._ou_overcorrect.step(dt)) * 0.03
        cutoff = now - delay_s
        out_x, out_y = tx, ty
        while self._latency_buffer and self._latency_buffer[0][0] < cutoff:
            _, out_x, out_y = self._latency_buffer.pop(0)
        if len(self._latency_buffer) > 8:
            self._latency_buffer.pop(0)
        return out_x, out_y

    def _humanize_targets(self, tx: float, ty: float, dt: float) -> tuple[float, float]:
        """Spray wobble — hand never holds perfectly steady."""
        hi = self._intensity()
        wx = self.spray_wobble_x.step(dt) * 0.06 * hi
        wy = self.spray_wobble_y.step(dt) * 0.05 * hi
        mag = math.hypot(tx, ty)
        if mag > 0.01:
            return tx * (1.0 + wx), ty * (1.0 + wy)
        return tx, ty

    def step(
        self,
        target_dx: float,
        target_dy: float,
        strength: float,
        engaged: bool,
        dt: float = 0.01,
    ) -> tuple[int, int]:
        if strength <= 0 or not engaged:
            return 0, 0

        now = self._elapsed()
        hi = self._intensity()
        act = self._activation_factor()
        eff_strength = strength * act

        target_dx, target_dy = self._humanize_targets(target_dx, target_dy, dt)

        disp = math.hypot(target_dx, target_dy)
        if abs(target_dx - self._prev_target_x) > 0.35 or abs(target_dy - self._prev_target_y) > 0.35:
            self._last_dir_change = now
            err = math.hypot(target_dx - self._prev_target_x, target_dy - self._prev_target_y)
            if err > 1.5 and abs(self._ou_overcorrect.step(dt)) > 0.32:
                oc = 1.08 + abs(self._ou_overcorrect.step(dt)) * 0.07
                target_dx *= oc
                target_dy *= oc

        self._prev_target_x = target_dx
        self._prev_target_y = target_dy

        self._fatigue = min(1.0, self._fatigue + self.fp.fatigue_rate * dt)
        self._spray_drift_h += self.micro_x.step(dt) * 0.002 * hi * dt * 60

        jitter = fitts_timing_variance(disp) * (1.0 + hi * 0.3)
        jerk_t = min(1.0, dt / max(0.04 + jitter, 0.015))
        scaled_x = minimum_jerk_position(jerk_t, 1.0, target_dx) * eff_strength
        scaled_y = (
            minimum_jerk_position(jerk_t, 1.0, target_dy)
            * eff_strength
            * self.fp.vertical_asymmetry
        )
        scaled_x += self._spray_drift_h

        delayed_x, delayed_y = self._neural_latency_delay(scaled_x, scaled_y, now, dt)

        self.spring_x.set_target(delayed_x)
        self.spring_y.set_target(delayed_y)
        sx = self.spring_x.step(dt)
        sy = self.spring_y.step(dt)

        macro_x = self.macro.sample(now * 0.12, self._fatigue * 8.0) * (0.35 + self._fatigue * 0.65)
        macro_y = self.macro_y.sample(now * 0.11, self._fatigue * 7.0) * (0.3 + self._fatigue * 0.6)

        post_change = now - self._last_dir_change
        micro_scale = (0.15 + max(0.0, 1.0 - post_change / 0.2) * 0.85) * math.hypot(delayed_x, delayed_y)
        mx = self.micro_x.step(dt) * micro_scale * 0.12 * hi
        my = self.micro_y.step(dt) * micro_scale * 0.11 * hi

        power = max(abs(delayed_x), abs(delayed_y), 0.08) ** 0.62
        tremor_x = self.tremor_x.sample(now, hi) * power
        tremor_y = self.tremor_y.sample(now, hi) * power

        err_mag = abs(self.spring_x.target - sx) + abs(self.spring_y.target - sy)
        if err_mag > 0.4:
            self._sustained_error += dt
            if self._sustained_error > 0.07:
                self._gain = min(1.4, self._gain + dt * 0.55)
        else:
            self._sustained_error = 0.0
            self._gain = max(1.0, self._gain - dt * 0.35)

        total_x = (sx + macro_x * 0.28 + mx + tremor_x) * self._gain
        total_y = (sy + macro_y * 0.24 + my + tremor_y) * self._gain

        coupling = 0.35 + hi * 0.12
        shared = (macro_x + macro_y + tremor_x * 0.5 + tremor_y * 0.5) * coupling * 0.25
        total_x += shared + sy * coupling * 0.42
        total_y += shared + sx * coupling * 0.38

        self._accum_x += total_x
        self._accum_y += total_y

        ix = int(self._accum_x) if abs(self._accum_x) >= 0.5 else 0
        iy = int(self._accum_y) if abs(self._accum_y) >= 0.5 else 0
        if ix:
            self._accum_x -= ix
        if iy:
            self._accum_y -= iy
        return ix, iy
