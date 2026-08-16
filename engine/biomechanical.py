"""Integrated biomechanical motion engine for human-grade mouse compensation."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

from engine.noise import BandLimitedTremor, OrnsteinUhlenbeck, SeededSimplex2D
from engine.trajectory import SpringDamper, fitts_timing_variance, minimum_jerk_position


@dataclass
class ProfileFingerprint:
    seed: int = 42
    tremor_hz: float = 10.0
    fatigue_rate: float = 0.025
    phenotype: str = "Conservative"  # Aggressive | Conservative
    vertical_asymmetry: float = 1.2

    @property
    def aggressive(self) -> bool:
        return self.phenotype.lower() == "aggressive"


@dataclass
class MotionOutput:
    dx: float
    dy: float
    strength: float


class BiomechanicalEngine:
    """
    Five-subsystem motion model:
    - Minimum jerk + spring-damper trajectories
    - Macro drift, micro correction, physiological tremor
    - State-aware variance, closed-loop feedback simulation
    """

    def __init__(self, fingerprint: ProfileFingerprint | None = None):
        self.fp = fingerprint or ProfileFingerprint()
        aggressive = self.fp.aggressive
        self.spring_x = SpringDamper(aggressive=aggressive)
        self.spring_y = SpringDamper(aggressive=aggressive)
        self.macro = SeededSimplex2D(self.fp.seed)
        self.micro_x = OrnsteinUhlenbeck(theta=4.0, sigma=0.4, mu=0.0, x0=0.0)
        self.micro_y = OrnsteinUhlenbeck(theta=4.0, sigma=0.4, mu=0.0, x0=0.0)
        self.tremor_x = BandLimitedTremor(self.fp.seed + 1, self.fp.tremor_hz)
        self.tremor_y = BandLimitedTremor(self.fp.seed + 2, self.fp.tremor_hz + 0.3)
        self._accum_x = 0.0
        self._accum_y = 0.0
        self._engage_time: float | None = None
        self._last_dir_change = 0.0
        self._prev_target_x = 0.0
        self._prev_target_y = 0.0
        self._fatigue = 0.0
        self._gain = 1.0
        self._sustained_error = 0.0
        self._latency_buffer: list[tuple[float, float, float]] = []
        self._activation_idx = 0
        self._ou_overcorrect = OrnsteinUhlenbeck(theta=1.5, sigma=0.5, mu=0.0, x0=0.0)
        self._start_time = time.perf_counter()

    def reset_accumulators(self) -> None:
        self._accum_x = 0.0
        self._accum_y = 0.0

    def set_fingerprint(self, fp: ProfileFingerprint) -> None:
        self.fp = fp
        aggressive = fp.aggressive
        self.spring_x = SpringDamper(aggressive=aggressive)
        self.spring_y = SpringDamper(aggressive=aggressive)
        self.macro = SeededSimplex2D(fp.seed)
        self.tremor_x = BandLimitedTremor(fp.seed + 1, fp.tremor_hz)
        self.tremor_y = BandLimitedTremor(fp.seed + 2, fp.tremor_hz + 0.3)

    def _elapsed(self) -> float:
        return time.perf_counter() - self._start_time

    def _activation_factor(self, engaged: bool) -> float:
        if not engaged:
            self._engage_time = None
            return 0.0
        now = time.perf_counter()
        if self._engage_time is None:
            self._engage_time = now
            self._activation_idx += 1
        ms = (now - self._engage_time) * 1000
        if ms < 200:
            return 0.65 + 0.35 * (ms / 200.0)  # activation transient
        return 1.0

    def compute_strength(
        self,
        hold_ms: float,
        tap_threshold_ms: float,
        tap_strength: float,
        hold_ramp_ms: float,
        spray_ramp_ms: float = 300.0,
    ) -> float:
        """
        Tap = partial strength (default 50%).
        Hold ramps tap_strength → 1.0, then spray ramp adds fine control.
        """
        if hold_ms <= 0:
            return 0.0
        if hold_ms < tap_threshold_ms:
            return tap_strength
        if hold_ramp_ms <= 0:
            base = 1.0
        else:
            ramp_t = min(1.0, (hold_ms - tap_threshold_ms) / hold_ramp_ms)
            base = tap_strength + (1.0 - tap_strength) * self._smoothstep(ramp_t)
        if spray_ramp_ms > 0 and hold_ms > tap_threshold_ms + hold_ramp_ms:
            spray_t = min(1.0, (hold_ms - tap_threshold_ms - hold_ramp_ms) / spray_ramp_ms)
            spray_boost = 0.92 + 0.08 * self._smoothstep(spray_t)
            base *= spray_boost
        return min(1.0, base)

    @staticmethod
    def _smoothstep(t: float) -> float:
        t = max(0.0, min(1.0, t))
        return t * t * (3.0 - 2.0 * t)

    def _neural_latency_delay(self, tx: float, ty: float, now: float) -> tuple[float, float]:
        """15–45ms reactive delay via seeded OU threshold."""
        self._latency_buffer.append((now, tx, ty))
        delay_s = 0.015 + abs(self._ou_overcorrect.step(0.001)) * 0.03
        cutoff = now - delay_s
        out_x, out_y = tx, ty
        while self._latency_buffer and self._latency_buffer[0][0] < cutoff:
            _, out_x, out_y = self._latency_buffer.pop(0)
        return out_x, out_y

    def step(
        self,
        target_dx: float,
        target_dy: float,
        strength: float,
        engaged: bool,
        dt: float = 0.01,
    ) -> tuple[int, int]:
        """Returns integer pixel move with sub-pixel accumulation."""
        if strength <= 0 or not engaged:
            self.spring_x.set_target(0.0)
            self.spring_y.set_target(0.0)
            self._engage_time = None
            return 0, 0

        now = self._elapsed()
        act = self._activation_factor(engaged)
        eff_strength = strength * act

        disp = math.hypot(target_dx, target_dy)
        if abs(target_dx - self._prev_target_x) > 0.5 or abs(target_dy - self._prev_target_y) > 0.5:
            self._last_dir_change = now
            err = math.hypot(target_dx - self._prev_target_x, target_dy - self._prev_target_y)
            if err > 2.0 and abs(self._ou_overcorrect.step(dt)) > 0.35:
                target_dx *= 1.12
                target_dy *= 1.12

        self._prev_target_x = target_dx
        self._prev_target_y = target_dy

        jitter = fitts_timing_variance(disp)
        jerk_t = min(1.0, dt / max(0.05 + jitter, 0.02))
        scaled_x = minimum_jerk_position(jerk_t, 1.0, target_dx) * eff_strength
        scaled_y = minimum_jerk_position(jerk_t, 1.0, target_dy) * eff_strength * self.fp.vertical_asymmetry

        delayed_x, delayed_y = self._neural_latency_delay(scaled_x, scaled_y, now)

        self.spring_x.set_target(delayed_x)
        self.spring_y.set_target(delayed_y)
        sx = self.spring_x.step(dt)
        sy = self.spring_y.step(dt)

        self._fatigue = min(1.0, self._fatigue + self.fp.fatigue_rate * dt * (1 if engaged else -2))
        macro = self.macro.sample(now * 0.15, self._fatigue * 10.0) * (0.3 + self._fatigue * 0.7)

        post_change = now - self._last_dir_change
        micro_scale = 0.0
        if post_change < 0.15:
            micro_scale = (1.0 - post_change / 0.15) * math.hypot(delayed_x, delayed_y) * 0.08
        mx = self.micro_x.step(dt) * micro_scale
        my = self.micro_y.step(dt) * micro_scale

        power = max(abs(delayed_x), abs(delayed_y), 0.1) ** 0.65
        tremor_x = self.tremor_x.sample(now) * power
        tremor_y = self.tremor_y.sample(now) * power

        err_mag = abs(self.spring_x.target - sx) + abs(self.spring_y.target - sy)
        if err_mag > 0.5:
            self._sustained_error += dt
            if self._sustained_error > 0.08:
                self._gain = min(1.35, self._gain + dt * 0.5)
        else:
            self._sustained_error = 0.0
            self._gain = max(1.0, self._gain - dt * 0.3)

        total_x = (sx + macro * 0.15 + mx + tremor_x) * self._gain
        total_y = (sy + macro * 0.12 + my + tremor_y) * self._gain

        self._accum_x += total_x
        self._accum_y += total_y

        ix = int(self._accum_x) if abs(self._accum_x) >= 0.5 else 0
        iy = int(self._accum_y) if abs(self._accum_y) >= 0.5 else 0
        if ix:
            self._accum_x -= ix
        if iy:
            self._accum_y -= iy
        return ix, iy
