# -*- coding: utf-8 -*-
"""stats.py 单测：Wilson 区间性质 + 口径约定（异常局排除、match 层分母）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.stats import overview, wr, wilson


# ---------- Wilson 区间性质 ----------

def test_wilson_basic():
    lo, hi = wilson(5, 10)
    assert 0.19 < lo < 0.5 < hi < 0.82  # 5/10=50%，区间约 [23%, 77%]


def test_wilson_never_exceeds_bounds():
    """小样本极端值不得越界（正态近似会算出 >100%）。"""
    lo, hi = wilson(1, 2)
    assert lo >= 0.0 and hi <= 1.0
    lo, hi = wilson(0, 3)
    assert lo == 0.0 and hi < 0.85
    lo, hi = wilson(10, 10)
    assert lo > 0.7 and hi == 1.0


def test_wilson_narrows_with_sample():
    lo5, hi5 = wilson(5, 10)
    lo50, hi50 = wilson(50, 100)
    assert (hi50 - lo50) < (hi5 - lo5)  # 样本越大区间越窄


def test_wr_object():
    r = wr(7, 10)
    assert r == {"n": 10, "wins": 7, "wr": 70.0, "lo": 39.7, "hi": 89.2}
    assert wr(0, 0)["wr"] is None
