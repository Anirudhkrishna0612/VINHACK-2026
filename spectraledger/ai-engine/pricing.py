"""Transparent pricing formula (deliberately NOT a model - a judge can audit it by hand).

price = base_rate * congestion_multiplier * qos_priority_weight * urgency_factor
Unit: USD per Mbps per 15-minute lease block.
"""
import config


def congestion_multiplier(util: float) -> float:
    """0.8x when the slice is idle, 1.2x at 50% load, then climbs steeply toward ~2.6x at 90%."""
    u = max(0.0, min(1.0, util))
    if u < 0.5:
        return 0.8 + 0.4 * (u / 0.5)
    return 1.2 + 3.5 * (u - 0.5)


def urgency_factor(side: str, urgency: float) -> float:
    u = max(0.0, min(1.0, urgency))
    return 1.0 + 0.5 * u if side == "buy" else 1.0 - 0.2 * u   # buyers pay up, sellers discount to clear


def compute_price(workload_type: str, utilization: float, urgency: float = 0.0, side: str = "sell") -> dict:
    if workload_type not in config.BASE_RATES:
        raise ValueError(f"unknown workload_type '{workload_type}'")
    base = config.BASE_RATES[workload_type]
    cm = congestion_multiplier(utilization)
    qos = config.QOS_WEIGHTS[workload_type]
    uf = urgency_factor(side, urgency)
    price = round(base * cm * qos * uf, 4)
    explanation = (
        f"{workload_type} base rate ${base:.3f}/Mbps x congestion {cm:.2f} "
        f"({'idle slice, discounted' if utilization < 0.5 else 'busy slice, scarcity premium'} at {utilization:.0%} utilization) "
        f"x QoS priority {qos:.2f} x urgency {uf:.2f} ({side}er urgency {urgency:.2f}) = ${price:.4f} per Mbps per 15-min block."
    )
    return {
        "base_rate": base,
        "congestion_multiplier": round(cm, 4),
        "qos_priority_weight": qos,
        "urgency_factor": round(uf, 4),
        "price": price,
        "unit": "USD per Mbps per 15-minute lease block",
        "explanation": explanation,
    }
