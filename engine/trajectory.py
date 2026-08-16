"""Minimum-jerk trajectories, spring-damper dynamics, Fitts's law scaling."""

import math


def minimum_jerk_position(t: float, duration: float, distance: float) -> float:
    """5th-order polynomial S-curve; t in [0, duration]."""
    if duration <= 0:
        return distance
    tau = max(0.0, min(1.0, t / duration))
    s = 10 * tau**3 - 15 * tau**4 + 6 * tau**5
    return distance * s


def minimum_jerk_velocity(t: float, duration: float, distance: float) -> float:
    if duration <= 0:
        return 0.0
    tau = max(0.0, min(1.0, t / duration))
    ds = 30 * tau**2 - 60 * tau**3 + 30 * tau**4
    return distance * ds / duration


class SpringDamper:
    """Second-order damped oscillator with 3–8% overshoot target."""

    def __init__(
        self,
        stiffness: float = 180.0,
        damping_ratio: float = 0.55,
        mass: float = 1.0,
        aggressive: bool = False,
    ):
        if aggressive:
            stiffness = 220.0
            damping_ratio = 0.48
        self.k = stiffness
        self.zeta = damping_ratio
        self.m = mass
        self.x = 0.0
        self.v = 0.0
        self.target = 0.0

    def set_target(self, target: float) -> None:
        self.target = target

    def step(self, dt: float) -> float:
        omega_n = math.sqrt(self.k / self.m)
        c = 2 * self.zeta * omega_n * self.m
        accel = (self.k * (self.target - self.x) - c * self.v) / self.m
        self.v += accel * dt
        self.x += self.v * dt
        return self.x

    def reset(self, value: float = 0.0) -> None:
        self.x = value
        self.v = 0.0
        self.target = value


def fitts_timing_variance(displacement: float, a: float = 0.12, b: float = 0.08) -> float:
    """Fitts's law: larger moves → more timing jitter (inverse accuracy-speed)."""
    d = max(abs(displacement), 0.5)
    mt = a + b * math.log2(d + 1)
    return mt * 0.015  # scale to seconds variance


def compute_overshoot_pct(spring: SpringDamper, target: float, settle_threshold: float = 0.02) -> float:
    """Estimate overshoot percentage for validation."""
    if abs(target) < 1e-6:
        return 0.0
    peak = abs(spring.x)
    return max(0.0, (peak - abs(target)) / abs(target) * 100.0)
