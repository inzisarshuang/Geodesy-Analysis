"""GAMMA quad_fit/quad_sub phase detrending."""

from .plan import build_gamma_quad_detrend_plan
from .runner import run_gamma_quad_detrend

__all__ = ["build_gamma_quad_detrend_plan", "run_gamma_quad_detrend"]
