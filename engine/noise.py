"""Seeded Simplex noise and Ornstein-Uhlenbeck processes — no uniform random."""

import math


class SeededSimplex1D:
    """1D Simplex noise with deterministic seed (temporally coherent)."""

    GRAD = (1, -1)

    def __init__(self, seed: int = 0):
        self.seed = seed & 0xFFFFFFFF
        self._perm = self._build_perm(self.seed)

    @staticmethod
    def _build_perm(seed: int) -> list[int]:
        p = list(range(256))
        state = seed
        for i in range(255, 0, -1):
            state = (state * 1664525 + 1013904223) & 0xFFFFFFFF
            j = state % (i + 1)
            p[i], p[j] = p[j], p[i]
        return p + p

    def _hash(self, i: int) -> float:
        return self._perm[i & 255] / 255.0

    def sample(self, t: float) -> float:
        i0 = int(math.floor(t))
        i1 = i0 + 1
        f = t - i0
        u = f * f * (3.0 - 2.0 * f)
        g0 = self.GRAD[int(self._hash(i0) * 2) & 1]
        g1 = self.GRAD[int(self._hash(i1) * 2) & 1]
        return (1.0 - u) * g0 * (t - i0) + u * g1 * (t - i1)


class SeededSimplex2D:
    """2D Simplex noise for macro drift."""

    def __init__(self, seed: int = 0):
        self.seed = seed & 0xFFFFFFFF
        self._perm = SeededSimplex1D._build_perm(self.seed)

    def _hash2(self, x: int, y: int) -> float:
        h = self._perm[(x + self._perm[y & 255]) & 255]
        return h / 255.0

    def sample(self, x: float, y: float) -> float:
        xi = int(math.floor(x))
        yi = int(math.floor(y))
        xf = x - xi
        yf = y - yi
        u = xf * xf * (3.0 - 2.0 * xf)
        v = yf * yf * (3.0 - 2.0 * yf)
        n00 = (self._hash2(xi, yi) * 2 - 1) * xf
        n10 = (self._hash2(xi + 1, yi) * 2 - 1) * (xf - 1)
        n01 = (self._hash2(xi, yi + 1) * 2 - 1) * xf
        n11 = (self._hash2(xi + 1, yi + 1) * 2 - 1) * (xf - 1)
        nx0 = n00 * (1 - u) + n10 * u
        nx1 = n01 * (1 - u) + n11 * u
        return nx0 * (1 - v) + nx1 * v


class OrnsteinUhlenbeck:
    """Temporally correlated noise via OU process (pink-ish when chained)."""

    def __init__(self, seed: int, theta: float, sigma: float, mu: float = 0.0, x0: float = 0.0):
        self.theta = theta
        self.sigma = sigma
        self.mu = mu
        self.x = x0
        self._step_idx = 0
        self._simplex = SeededSimplex1D(seed)

    def step(self, dt: float) -> float:
        self._step_idx += 1
        dw = self._simplex.sample(self._step_idx * 0.137 + dt * 50.0)
        self.x += self.theta * (self.mu - self.x) * dt + self.sigma * math.sqrt(max(dt, 1e-6)) * dw
        return self.x

    def reset(self, x0: float = 0.0) -> None:
        self.x = x0
        self._step_idx = 0


class BandLimitedTremor:
    """8–12 Hz physiological tremor via seeded oscillation + OU modulation."""

    def __init__(self, seed: int, frequency_hz: float = 10.0):
        self.frequency = frequency_hz
        self.phase = (seed % 628) / 100.0
        self._ou = OrnsteinUhlenbeck(seed + 3, theta=2.0, sigma=0.15, mu=0.0, x0=0.01)
        self._simplex = SeededSimplex1D(seed + 7919)
        self._time_offset = (seed % 1000) / 500.0

    def sample(self, t: float, intensity: float = 1.0) -> float:
        tt = t + self._time_offset
        base = math.sin(2 * math.pi * self.frequency * tt + self.phase)
        harmonics = math.sin(2 * math.pi * self.frequency * 1.7 * tt + self.phase * 0.6) * 0.35
        mod = self._simplex.sample(tt * 3.7) * 0.35
        ou = self._ou.step(0.001)
        amp = (0.12 + abs(ou) * 0.06) * intensity
        return (base + harmonics + mod) * amp + 0.015 * intensity


class HumanTickScheduler:
    """Variable inter-tick intervals and micro-pauses — seeded, not uniform."""

    def __init__(self, seed: int):
        self._simplex = SeededSimplex1D(seed + 4201)
        self._pause_ou = OrnsteinUhlenbeck(seed + 4202, theta=2.5, sigma=0.6, mu=0.0)
        self._tick = 0

    def next_delay(self, base_ms: float = 10.0, variance: float = 0.35) -> tuple[float, bool]:
        """
        Returns (delay_seconds, skip_tick).
        skip_tick=True simulates brief hand hesitation / missed motor frame.
        """
        self._tick += 1
        t = self._tick * 0.083
        jitter = self._simplex.sample(t) * variance
        delay_ms = base_ms * (1.0 + jitter * 0.45)
        delay_ms = max(6.0, min(18.0, delay_ms))
        pause_signal = self._pause_ou.step(delay_ms / 1000.0)
        skip = pause_signal > 0.72 and self._simplex.sample(t + 17.3) > 0.55
        return delay_ms / 1000.0, skip
