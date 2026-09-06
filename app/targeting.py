# -*- coding: utf-8 -*-
"""统计检验原语（零依赖）：二项检验、卡方检验、连败概率、p 值→指数映射。

DESIGN §3.5「你被针对了吗」的方法论基础。所有检验为单侧：
p 值小 = 观测朝着"被针对"方向偏离期望。
"""
from __future__ import annotations

import math

LOG10_P_MIN = -4.0  # p ≤ 1e-4 视为满分 100


# ---------- 二项分布 ----------

def _log_binom_pmf(k: int, n: int, p: float) -> float:
    if k < 0 or k > n:
        return -math.inf
    if p <= 0.0:
        return 0.0 if k == 0 else -math.inf
    if p >= 1.0:
        return 0.0 if k == n else -math.inf
    logc = math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
    return logc + k * math.log(p) + (n - k) * math.log(1 - p)


def binom_cdf(k: int, n: int, p: float) -> float:
    """P(X <= k)。

    用对称性把累加范围压到 min(k, n-k)，n 大时也很快。
    """
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    if k > n - k - 1:  # 右半：1 - P(X >= k+1)
        return 1.0 - binom_sf(k + 1, n, p)
    return sum(math.exp(_log_binom_pmf(i, n, p)) for i in range(k + 1))


def binom_sf(k: int, n: int, p: float) -> float:
    """P(X >= k)（含 k）。"""
    if k <= 0:
        return 1.0
    if k > n:
        return 0.0
    if k > n / 2:  # 右半直接累加
        return sum(math.exp(_log_binom_pmf(i, n, p)) for i in range(k, n + 1))
    return 1.0 - binom_cdf(k - 1, n, p)


# ---------- 卡方分布（正则化不完全 Gamma）----------

def _lower_gamma(a: float, x: float) -> float:
    """正则化下不完全 Gamma P(a,x)（级数法，Numerical Recipes gser）。"""
    if x <= 0:
        return 0.0
    ap, s, d = a, 1.0 / a, 1.0 / a
    for _ in range(500):
        ap += 1.0
        d *= x / ap
        s += d
        if abs(d) < abs(s) * 1e-10:
            break
    return s * math.exp(-x + a * math.log(x) - math.lgamma(a))


def _upper_gamma(a: float, x: float) -> float:
    """正则化上不完全 Gamma Q(a,x)（连分式法，Numerical Recipes gcf）。"""
    b = x + 1.0 - a
    c = 1e300
    d = 1.0 / b
    h = d
    for i in range(1, 500):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < 1e-300:
            d = 1e-300
        c = b + an / c
        if abs(c) < 1e-300:
            c = 1e-300
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-10:
            break
    return math.exp(-x + a * math.log(x) - math.lgamma(a)) * h


def chi2_sf(x: float, df: int) -> float:
    """卡方分布生存函数 P(X >= x)。x<=0 → 1。"""
    if x <= 0:
        return 1.0
    a = df / 2.0
    hx = x / 2.0
    if hx < a + 1.0:
        return max(0.0, 1.0 - _lower_gamma(a, hx))
    return max(0.0, min(1.0, _upper_gamma(a, hx)))


# ---------- 连败（Feller 长游程近似）----------

def max_loss_streak(results: list[str]) -> int:
    """按时间序的对局结果中最大连败长度（'loss' 计败）。"""
    best = cur = 0
    for r in results:
        if r == "loss":
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def streak_sf(streak: int, n: int, win_rate: float) -> float:
    """P(最大连败 >= streak) — Feller 近似 1 - exp(-N·p·q^L)。

    期望"长度 ≥ L 的连败次数" ≈ N·(胜率)·(败率)^L（连败段起点前必是胜局或开局）。
    泊松化后 P(至少一次) = 1 - exp(-期望)。streak<=1 或 n=0 → 1。
    """
    if streak <= 1 or n <= 0:
        return 1.0
    q = 1.0 - win_rate
    if q <= 0:
        return 0.0
    expected = n * win_rate * (q ** streak)
    return 1.0 - math.exp(-expected)


# ---------- p 值 → 0-100 指数 ----------

def p_to_score(p: float, p_normal: float = 0.10) -> float:
    """p 值映射为 0-100（"邪门程度"）。

    p >= p_normal（统计上正常）→ 50；p 越小分越高，log 刻度，
    p ≤ 1e-4 → 100。0-50 区间不启用（正常运统一给 50，避免把
    "特别正常"误读成"欧皇"）。
    """
    if not (p == p):  # NaN
        return 50.0
    if p >= p_normal:
        return 50.0
    if p <= 10 ** LOG10_P_MIN:
        return 100.0
    lr = (math.log10(p) - math.log10(p_normal)) / (LOG10_P_MIN - math.log10(p_normal))
    return round(50.0 + 50.0 * lr, 1)


def luck_label(score: float) -> str:
    """综合指数 → 分段评语（DESIGN §3.5）。"""
    if score < 30:
        return "欧皇"
    if score < 50:
        return "手气不错"
    if score < 70:
        return "正常人"
    if score < 85:
        return "有点邪门"
    return "建议卸载重装"
