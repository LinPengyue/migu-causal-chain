"""causal_chain8：PDF 选片(A) + 因果链(B，含 chain6 A/B/C 算法独立副本)。

不修改 causal_chain4/5/6/7。
"""

__all__ = ["__version__", "select_moments", "run_build_highlights"]

__version__ = "0.8.0"


def select_moments(*args, **kwargs):
    from causal_chain8.select_moments import select_moments as _fn

    return _fn(*args, **kwargs)


def run_build_highlights(*args, **kwargs):
    from causal_chain8.build_highlights import run_build_highlights as _fn

    return _fn(*args, **kwargs)
