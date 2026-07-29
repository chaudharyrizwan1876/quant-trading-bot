# ============================================================
#  strategies — signal generators (Gold is first-class citizen)
# ============================================================

from .gold_hybrid import generate_gold_signal
from .amd import generate_amd_signal
from .silver_bullet import generate_silver_bullet_signal, is_silver_bullet_window
from .scalper_ict import generate_scalp_ict_signal
from .scalper_momentum import generate_scalp_momentum_signal

__all__ = [
    "generate_gold_signal",
    "generate_amd_signal",
    "generate_silver_bullet_signal",
    "is_silver_bullet_window",
    "generate_scalp_ict_signal",
    "generate_scalp_momentum_signal",
]
