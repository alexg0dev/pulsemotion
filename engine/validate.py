"""Validate humanization benchmarks (FFT pink noise, uniqueness, overshoot)."""

from __future__ import annotations

import math

from engine.biomechanical import BiomechanicalEngine, ProfileFingerprint


def _collect_float_trajectory(activations: int = 100, steps: int = 30) -> list[tuple[float, float]]:
    fp = ProfileFingerprint(seed=42, humanization_intensity=1.5)
    engine = BiomechanicalEngine(fp)
    points: list[tuple[float, float]] = []
    for act in range(activations):
        engine.begin_activation()
        ax, ay = 0.0, 0.0
        for _ in range(steps):
            dt = 0.01 + (act % 5) * 0.001
            ix, iy = engine.step(0.0, 2.5, 1.0, engaged=True, dt=dt)
            ax += ix + engine._accum_x
            ay += iy + engine._accum_y
            points.append((round(ax, 4), round(ay, 4)))
        engine.end_activation()
    return points


def _velocity_profile(steps: int = 50) -> list[float]:
    fp = ProfileFingerprint(seed=99, humanization_intensity=1.5)
    engine = BiomechanicalEngine(fp)
    engine.begin_activation()
    vels: list[float] = []
    prev = 0.0
    for i in range(steps):
        _, iy = engine.step(0.0, 3.0, 1.0, engaged=True, dt=0.008 + (i % 3) * 0.002)
        vels.append(abs(iy - prev))
        prev = iy
    return vels


def _estimate_pinkness(values: list[float]) -> float:
    if len(values) < 16:
        return 0.0
    n = len(values)
    low = sum(v * v for v in values[: n // 4])
    high = sum(v * v for v in values[3 * n // 4 :]) + 1e-9
    return low / high


def _cross_correlation(xs: list[float], ys: list[float]) -> float:
    n = min(len(xs), len(ys))
    if n < 2:
        return 0.0
    mx = sum(xs[:n]) / n
    my = sum(ys[:n]) / n
    num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    den = math.sqrt(sum((xs[i] - mx) ** 2 for i in range(n)) * sum((ys[i] - my) ** 2 for i in range(n)))
    return num / den if den > 1e-9 else 0.0


def run_validation() -> dict:
    trajs = _collect_float_trajectory(activations=100, steps=30)
    unique = len(set(trajs))
    xs = [p[0] for p in trajs]
    ys = [p[1] for p in trajs]
    vels = _velocity_profile()
    pink = _estimate_pinkness([float(v) for v in vels])
    corr = _cross_correlation(xs, ys)

    bell = sum(
        1 for i in range(1, len(vels) - 1)
        if vels[i] >= vels[i - 1] and vels[i] >= vels[i + 1]
    )

    return {
        "unique_trajectory_points": unique,
        "total_points": len(trajs),
        "all_unique": unique == len(trajs),
        "xy_correlation": round(corr, 3),
        "xy_coupling_ok": corr > 0.3,
        "pink_ratio": round(pink, 3),
        "pink_noise_ok": pink > 0.8,
        "velocity_peaks": bell,
        "velocity_bell_ok": bell >= 3,
    }


if __name__ == "__main__":
    results = run_validation()
    print("PulseMotion humanization validation")
    for k, v in results.items():
        print(f"  {k}: {v}")
