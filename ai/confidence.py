# ============================================================
#  ai/confidence.py — Setup Quality / Confidence Engine
# ============================================================
#
#  WHY THIS EXISTS
#  ---------------
#  Purana system do jagah ad-hoc integer points add karta tha:
#    * risk_manager.score_signal()  (XAU +50, RR*10, keyword hits)
#    * gold_hybrid._calc_score()    (0..~20 integer)
#  ...phir ek magic threshold (MIN_SCORE=6) se compare. Yeh
#  numbers ka koi bounded/interpretable meaning nahi tha — na
#  "92% confidence" jaisa kuch, na structured reasons.
#
#  Yeh module us jagah ek proper DECISION-SUPPORT LAYER deta hai
#  (mission ke "AI as evaluator, not signal generator" spec ke
#  mutabiq):
#    1. Rule-engine (strategies/*) candidate setup + FACTORS deta hai
#    2. Yeh engine un factors ko weight kar ke ek BOUNDED
#       confidence % (0..99) nikalta hai
#    3. Har active factor ek human-readable REASON banta hai
#    4. Ek configurable threshold (config.MIN_CONFIDENCE) upar hi
#       trade execute hoti hai
#
#  Yeh deterministic aur explainable hai — koi black box nahi.
#  Phase 5 mein isi jagah ek trained ML win-probability model
#  plug ho sakta hai (extension point neeche documented hai).
# ============================================================

from dataclasses import dataclass, field
import config


# ── Base + factor weights ──────────────────────────────────
# Calibration target:
#   minimal valid setup (trend+zone)          ~ 55%
#   solid setup (trend+OB+retest+m5+session)  ~ 75%
#   A+ institutional (sweep+displacement+...) ~ 90%+
_BASE = 20.0

# Each entry: factor_key -> (weight, human_reason)
_POSITIVE = {
    "htf_trend_aligned":     (12.0, "HTF trend aligned (multi-timeframe agreement)"),
    "m15_structure_aligned": (6.0,  "M15 structure confirms bias"),
    "institutional_sweep":   (22.0, "Institutional liquidity sweep + displacement"),
    "order_block":           (11.0, "Price reacting from fresh Order Block"),
    "fair_value_gap":        (7.0,  "Fair Value Gap entry"),
    "liquidity_sweep":       (9.0,  "Liquidity sweep completed"),
    "break_retest":          (8.0,  "Break-and-retest confirmed"),
    "m5_confirmation":       (6.0,  "M5 confirmation present"),
    "m1_trigger":            (5.0,  "M1 entry trigger fired"),
    "amd_pattern":           (10.0, "AMD (Power-of-3) pattern confirmed"),
    "confirmed_pattern":     (10.0, "Complete confirmed setup pattern"),
    "volume_confirmation":   (6.0,  "Volume confirms institutional participation"),
    "pivot_confluence":      (4.0,  "Confluence with daily pivot level"),
    "prime_session":         (7.0,  "Inside prime session (London/NY)"),
    "silver_bullet_window":  (5.0,  "Inside Silver Bullet window"),
    "judas_window":          (4.0,  "Session-open Judas swing window"),
    "news_aligned":          (8.0,  "High-impact news bias aligned"),
}

# Penalties (subtracted). news_blackout is effectively a hard veto.
_PENALTY = {
    "atr_abnormal":  (12.0, "Abnormal volatility spike (caution)"),
    "news_blackout": (100.0, "High-impact news imminent (blackout)"),
}

# RR contributes up to this many points, scaled from RR 1.0..3.0
_RR_MAX_POINTS = 10.0
_RR_FLOOR      = 1.0
_RR_CEIL       = 3.0

_CONF_CEIL = 99.0


@dataclass
class ConfidenceResult:
    confidence: float               # 0..99
    grade: str                      # A+ / A / B / C / D
    reasons: list = field(default_factory=list)
    penalties: list = field(default_factory=list)
    passed: bool = False            # >= config.MIN_CONFIDENCE

    def as_comment_suffix(self) -> str:
        return f"C{int(round(self.confidence))}"


def _grade(conf: float) -> str:
    if conf >= 88: return "A+"
    if conf >= 78: return "A"
    if conf >= 68: return "B"
    if conf >= 58: return "C"
    return "D"


def _rr_points(rr: float) -> float:
    if rr <= _RR_FLOOR:
        return 0.0
    span = _RR_CEIL - _RR_FLOOR
    frac = min(max((rr - _RR_FLOOR) / span, 0.0), 1.0)
    return frac * _RR_MAX_POINTS


def evaluate(factors: dict, rr: float = 0.0,
             memory_adj: float = 0.0) -> ConfidenceResult:
    """
    factors:    normalized bool/flag dict from a strategy (keys ⊆ _POSITIVE/_PENALTY)
    rr:         reward:risk of the proposed trade (TP3 vs SL)
    memory_adj: adaptive learning delta from trade_memory (win-rate history);
                yeh already points-based hai (-25..+30 range), directly add hota hai.

    Returns ConfidenceResult (bounded, explainable).
    """
    factors = factors or {}
    score = _BASE
    reasons, penalties = [], []

    for key, (weight, text) in _POSITIVE.items():
        if factors.get(key):
            score += weight
            reasons.append((weight, text))

    rr_pts = _rr_points(rr)
    if rr_pts > 0:
        score += rr_pts
        reasons.append((rr_pts, f"Favorable RR {rr:.1f}:1"))

    for key, (weight, text) in _PENALTY.items():
        if factors.get(key):
            score -= weight
            penalties.append((weight, text))

    # Adaptive memory (learning) — nudges confidence up/down based on
    # this pattern's historical win-rate on this symbol.
    if memory_adj:
        score += memory_adj
        if memory_adj > 0:
            reasons.append((memory_adj, f"Pattern historically profitable (+{memory_adj:.0f})"))
        else:
            penalties.append((abs(memory_adj), f"Pattern historically weak ({memory_adj:.0f})"))

    conf = max(0.0, min(score, _CONF_CEIL))

    reasons.sort(key=lambda x: x[0], reverse=True)
    penalties.sort(key=lambda x: x[0], reverse=True)

    threshold = getattr(config, "MIN_CONFIDENCE", 68.0)
    return ConfidenceResult(
        confidence=round(conf, 1),
        grade=_grade(conf),
        reasons=[t for _, t in reasons],
        penalties=[t for _, t in penalties],
        passed=conf >= threshold,
    )


# ────────────────────────────────────────────────────────────
#  PHASE 5 EXTENSION POINT (documented, not yet implemented)
# ────────────────────────────────────────────────────────────
#  A trained ML model (e.g. gradient-boosted trees on engineered
#  features from trade_memory history) could REPLACE or BLEND with
#  the deterministic score above:
#
#      p_win = _ml_model.predict_proba(feature_vector)   # 0..1
#      conf  = 0.5 * deterministic_conf + 0.5 * (p_win * 100)
#
#  Prerequisite: a meaningful labelled dataset. Current live history
#  is ~37 trades — nowhere near enough (severe overfit risk). The
#  Phase 3 backtesting engine is the intended way to accumulate and
#  validate that data BEFORE any model is trusted with real gating.
#  Until then this stays deterministic and fully explainable.
def ml_confidence(feature_vector) -> float:  # pragma: no cover - placeholder
    raise NotImplementedError(
        "ML confidence model not trained yet — accumulate/validate data "
        "via the backtesting engine first (see Phase 5 notes)."
    )
