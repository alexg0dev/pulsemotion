"""Tap vs hold strength — used by Truly-style recoil loop."""


def compute_strength(
    hold_ms: float,
    tap_threshold_ms: float,
    tap_strength: float,
    hold_ramp_ms: float,
    spray_ramp_ms: float = 300.0,
) -> float:
    if hold_ms <= 0:
        return 0.0
    if hold_ms < tap_threshold_ms:
        return tap_strength
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
    return min(1.0, max(0.0, base))
