"""小样本评测统计库（标注/judge 校准/质量报告共用，无第三方依赖）。

设计依据：
- 小样本（N<100）比例置信区间用 Wilson / Clopper-Pearson，不默认 bootstrap
  （evalstats：bootstrap CI 在 N<100 时不可靠，见 https://arxiv.org/html/2609.35815v1 ）。
- judge 分数不能当作人工真值直接做推断：用人工校准子集做 PPI 校正。
- 配对比较用 McNemar；多指标同时检验用 Holm 校正。
- 跨 run 的 pass^k / 质量分按场景（cluster）重采样，不把同场景 trial 当独立样本。
"""

from __future__ import annotations

import math
import random
from typing import Sequence


# ---------------------------------------------------------------------------
# Beta 分布 / 精确二项区间（Clopper-Pearson）
# ---------------------------------------------------------------------------


def _betacf(a: float, b: float, x: float) -> float:
    """不完全 Beta 函数的连分式（Numerical Recipes betacf）。"""
    tiny = 1e-30
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-12:
            break
    return h


def _betai(a: float, b: float, x: float) -> float:
    """正则化不完全 Beta 函数 I_x(a, b)。"""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    front = math.exp(lbeta + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def _beta_ppf(q: float, a: float, b: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Beta 分位数（二分法；评测样本量下足够快、足够稳）。"""
    if q <= 0.0:
        return 0.0
    if q >= 1.0:
        return 1.0
    for _ in range(120):
        mid = (lo + hi) / 2.0
        if _betai(a, b, mid) < q:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-12:
            break
    return (lo + hi) / 2.0


def wilson_ci(successes: float, n: int, z: float = 1.96) -> dict:
    """Wilson score 区间（比例/胜率的默认区间）。"""
    if n <= 0:
        return {"n": 0, "mean": None, "lo": None, "hi": None, "method": "wilson"}
    p = successes / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2.0 * n)) / denom
    half = z * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n)) / denom
    return {"n": n, "mean": round(p, 4), "lo": round(max(0.0, centre - half), 4),
            "hi": round(min(1.0, centre + half), 4), "method": "wilson"}


def clopper_pearson_ci(successes: float, n: int, alpha: float = 0.05) -> dict:
    """Clopper-Pearson 精确区间（保守，小样本报告首选）。"""
    if n <= 0:
        return {"n": 0, "mean": None, "lo": None, "hi": None, "method": "clopper-pearson"}
    lo = 0.0 if successes <= 0 else _beta_ppf(alpha / 2.0, successes, n - successes + 1)
    hi = 1.0 if successes >= n else _beta_ppf(1.0 - alpha / 2.0, successes + 1, n - successes)
    return {"n": n, "mean": round(successes / n, 4), "lo": round(lo, 4), "hi": round(hi, 4),
            "method": "clopper-pearson"}


# ---------------------------------------------------------------------------
# 一致性 / 排序相关
# ---------------------------------------------------------------------------


def agreement_rate(a: Sequence, b: Sequence) -> float:
    if not a or len(a) != len(b):
        raise ValueError("agreement_rate 需要等长非空序列")
    return sum(1 for x, y in zip(a, b) if x == y) / len(a)


def cohen_kappa(a: Sequence, b: Sequence) -> float:
    """未加权 Cohen's kappa（分类标签）。"""
    if not a or len(a) != len(b):
        raise ValueError("cohen_kappa 需要等长非空序列")
    n = len(a)
    observed = agreement_rate(a, b)
    labels = sorted(set(a) | set(b), key=str)
    expected = 0.0
    for label in labels:
        pa = sum(1 for x in a if x == label) / n
        pb = sum(1 for y in b if y == label) / n
        expected += pa * pb
    if expected >= 1.0:
        # 两边都是同一个恒定标签：kappa 无定义，按完美一致处理（否则会把纯净样本判死）
        return 1.0 if observed >= 0.999 else 0.0
    return (observed - expected) / (1.0 - expected)


def weighted_kappa(a: Sequence[float], b: Sequence[float], weights: str = "quadratic") -> float:
    """有序评分的加权 kappa（linear/quadratic），用于 1-5 分 rubric。"""
    if not a or len(a) != len(b):
        raise ValueError("weighted_kappa 需要等长非空序列")
    values = sorted({float(x) for x in a} | {float(y) for y in b})
    index = {value: i for i, value in enumerate(values)}
    k = len(values)
    if k <= 1:
        return 1.0
    n = len(a)
    matrix = [[0.0] * k for _ in range(k)]
    for x, y in zip(a, b):
        matrix[index[float(x)]][index[float(y)]] += 1.0
    rows = [sum(row) for row in matrix]
    cols = [sum(matrix[i][j] for i in range(k)) for j in range(k)]
    total = float(n)

    def distance(i: int, j: int) -> float:
        raw = abs(i - j) / (k - 1)
        return raw * raw if weights == "quadratic" else raw

    observed = sum(matrix[i][j] * distance(i, j) for i in range(k) for j in range(k)) / total
    expected = sum(rows[i] * cols[j] * distance(i, j) for i in range(k) for j in range(k)) / (total * total)
    if expected <= 0:
        return 1.0
    return 1.0 - observed / expected


def _average_ranks(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        average = (i + j) / 2.0 + 1.0
        for index in order[i:j + 1]:
            ranks[index] = average
        i = j + 1
    return ranks


def spearman(x: Sequence[float], y: Sequence[float]) -> float:
    """Spearman 秩相关（处理并列值）。"""
    if len(x) != len(y) or len(x) < 2:
        raise ValueError("spearman 需要等长且至少 2 个点")
    return pearson(_average_ranks([float(v) for v in x]), _average_ranks([float(v) for v in y]))


def pearson(x: Sequence[float], y: Sequence[float]) -> float:
    if len(x) != len(y) or len(x) < 2:
        raise ValueError("pearson 需要等长且至少 2 个点")
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(x, y))
    vx = sum((a - mx) ** 2 for a in x)
    vy = sum((b - my) ** 2 for b in y)
    if vx <= 0 or vy <= 0:
        return 0.0
    return cov / math.sqrt(vx * vy)


# ---------------------------------------------------------------------------
# 检验 / 多重比较 / 样本量
# ---------------------------------------------------------------------------


def _binom_two_sided_p(k: int, n: int, p: float = 0.5) -> float:
    """精确二项检验双侧 p 值（直接求和）。"""
    if n <= 0:
        return 1.0
    pmf = [math.comb(n, i) * (p ** i) * ((1 - p) ** (n - i)) for i in range(n + 1)]
    observed = pmf[k]
    return min(1.0, sum(value for value in pmf if value <= observed * (1 + 1e-12)))


def mcnemar_test(b: int, c: int) -> dict:
    """配对二元比较的 McNemar 精确检验（b/c 为两种方向的不一致计数）。"""
    n = b + c
    p = _binom_two_sided_p(min(b, c), n) if n > 0 else 1.0
    return {"b": b, "c": c, "n": n, "p_value": round(p, 6)}


def holm(pvalues: Sequence[float]) -> list[float]:
    """Holm-Bonferroni 校正后的 p 值（保持输入顺序）。"""
    m = len(pvalues)
    if m == 0:
        return []
    indexed = sorted(range(m), key=lambda i: pvalues[i])
    adjusted = [1.0] * m
    running = 0.0
    for rank, index in enumerate(indexed):
        value = min(1.0, (m - rank) * pvalues[index])
        running = max(running, value)
        adjusted[index] = running
    return adjusted


def sample_size_proportion(p0: float, p1: float, alpha: float = 0.05,
                           power: float = 0.8) -> int:
    """单比例 vs 基准的两侧检验样本量（正态近似；用于设计而不是报告）。"""
    if not 0 < p0 < 1 or not 0 < p1 < 1:
        raise ValueError("p0/p1 必须在 (0,1) 内")
    z_alpha = _z_for_alpha(alpha)
    z_beta = _z_for_power(power)
    delta = abs(p1 - p0)
    numerator = (z_alpha * math.sqrt(p0 * (1 - p0))
                 + z_beta * math.sqrt(p1 * (1 - p1))) ** 2
    return int(math.ceil(numerator / (delta * delta)))


def mde_proportion(n: int, p0: float = 0.5, alpha: float = 0.05,
                   power: float = 0.8) -> float:
    """给定 n 时能检出的最小比例差（近似解）。"""
    if n <= 0:
        raise ValueError("n 必须为正")
    z = _z_for_alpha(alpha) + _z_for_power(power)
    return round(z * math.sqrt(2 * p0 * (1 - p0) / n), 4)


def _z_for_alpha(alpha: float) -> float:
    table = {0.1: 1.6449, 0.05: 1.96, 0.01: 2.5758}
    return table.get(round(alpha, 3), 1.96)


def _z_for_power(power: float) -> float:
    table = {0.8: 0.8416, 0.9: 1.2816, 0.95: 1.6449}
    return table.get(round(power, 2), 0.8416)


# ---------------------------------------------------------------------------
# 聚类 bootstrap / PPI / Bradley-Terry
# ---------------------------------------------------------------------------


def cluster_bootstrap_mean(values: Sequence[float], clusters: Sequence,
                           iterations: int = 2000, level: float = 0.95,
                           seed: int = 20261106) -> dict:
    """按 cluster 重采样的均值 CI（同场景多 trial 不能当独立样本）。"""
    if len(values) != len(clusters) or not values:
        raise ValueError("values/clusters 需要等长非空")
    grouped: dict = {}
    for value, cluster in zip(values, clusters):
        grouped.setdefault(cluster, []).append(float(value))
    cluster_ids = sorted(grouped, key=str)
    if len(cluster_ids) < 2:
        mean = sum(values) / len(values)
        return {"n": len(values), "clusters": len(cluster_ids), "mean": round(mean, 4),
                "lo": None, "hi": None, "iterations": 0, "method": "cluster-bootstrap"}
    rng = random.Random(seed)
    means = []
    for _ in range(iterations):
        picks = [rng.choice(cluster_ids) for _ in cluster_ids]
        sample = [value for cluster in picks for value in grouped[cluster]]
        means.append(sum(sample) / len(sample))
    means.sort()
    alpha = (1.0 - level) / 2.0
    lo = means[int(alpha * len(means))]
    hi = means[min(len(means) - 1, int((1 - alpha) * len(means)))]
    mean = sum(values) / len(values)
    return {"n": len(values), "clusters": len(cluster_ids), "mean": round(mean, 4),
            "lo": round(lo, 4), "hi": round(hi, 4), "iterations": iterations,
            "method": "cluster-bootstrap",
            "warning": None if len(cluster_ids) >= 5 else "cluster<5，区间不可靠，只作探索"}


def bootstrap_mean(values: Sequence[float], iterations: int = 2000, level: float = 0.95,
                   seed: int = 20261106) -> dict:
    """普通 bootstrap 均值 CI（仅探索；小样本对外用 Wilson/CP）。"""
    if not values:
        raise ValueError("values 不能为空")
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(rng.choice(values) for _ in range(n)) / n for _ in range(iterations))
    alpha = (1.0 - level) / 2.0
    return {"n": n, "mean": round(sum(values) / n, 4),
            "lo": round(means[int(alpha * iterations)], 4),
            "hi": round(means[min(iterations - 1, int((1 - alpha) * iterations))], 4),
            "iterations": iterations, "method": "bootstrap"}


def ppi_mean(y_labeled: Sequence[float], f_labeled: Sequence[float],
             f_unlabeled: Sequence[float], level: float = 0.95) -> dict:
    """judge 偏差校正的均值估计（PPI，Angelopoulos et al. 2023）。

    theta = mean(f_unlabeled) + mean(y_labeled - f_labeled)
    方差 = var(f_unlabeled)/n_unlabeled + var(y-f)/n_labeled
    """
    if not y_labeled or len(y_labeled) != len(f_labeled):
        raise ValueError("PPI 需要等长的人工/judge 标签")
    if not f_unlabeled:
        raise ValueError("PPI 需要无人工标签的 judge 预测")
    n_lab = len(y_labeled)
    n_unlab = len(f_unlabeled)
    diffs = [float(y) - float(f) for y, f in zip(y_labeled, f_labeled)]
    mean_diff = sum(diffs) / n_lab
    mean_unlab = sum(float(f) for f in f_unlabeled) / n_unlab
    theta = mean_unlab + mean_diff
    var_diff = sum((d - mean_diff) ** 2 for d in diffs) / max(1, n_lab - 1)
    var_f = sum((float(f) - mean_unlab) ** 2 for f in f_unlabeled) / max(1, n_unlab - 1)
    se = math.sqrt(max(0.0, var_diff / n_lab + var_f / n_unlab))
    z = 1.96 if abs(level - 0.95) < 1e-9 else 1.96
    return {"n_labeled": n_lab, "n_unlabeled": n_unlab,
            "raw_judge_mean": round(mean_unlab, 4),
            "corrected_mean": round(theta, 4),
            "lo": round(theta - z * se, 4), "hi": round(theta + z * se, 4),
            "se": round(se, 4), "method": "ppi"}


def ppi_proportion(y_labeled: Sequence[int], f_labeled: Sequence[int],
                   f_unlabeled: Sequence[int]) -> dict:
    """二元 judge 的 PPI 校正比例（y 为人工真值 0/1）。"""
    if not y_labeled or len(y_labeled) != len(f_labeled):
        raise ValueError("PPI 需要等长的人工/judge 标签")
    if not f_unlabeled:
        raise ValueError("PPI 需要无人工标签的 judge 预测")
    n_lab = len(y_labeled)
    diffs = [float(y) - float(f) for y, f in zip(y_labeled, f_labeled)]
    mean_diff = sum(diffs) / n_lab
    mean_unlab = sum(float(f) for f in f_unlabeled) / len(f_unlabeled)
    theta = mean_unlab + mean_diff
    var = sum((d - mean_diff) ** 2 for d in diffs) / max(1, n_lab - 1) / n_lab
    se = math.sqrt(max(0.0, var))
    return {"n_labeled": n_lab, "n_unlabeled": len(f_unlabeled),
            "raw_judge_rate": round(mean_unlab, 4),
            "corrected_rate": round(theta, 4),
            "lo": round(theta - 1.96 * se, 4), "hi": round(theta + 1.96 * se, 4),
            "se": round(se, 4), "method": "ppi"}


def bradley_terry(wins: dict, max_iter: int = 200, tol: float = 1e-8,
                  prior: float = 0.5) -> dict:
    """由成对胜场估计 Bradley-Terry 强度（MM 算法，几何均值归一）。

    wins: {"A": {"B": 2.0, ...}, "B": {"A": 1.0, ...}}；平局按 0.5 拆分。
    prior 为每对对手的伪胜场（各 0.5），避免全胜/全负选手强度发散。
    """
    players = sorted({p for p, row in wins.items()} | {q for row in wins.values() for q in row})
    if not players:
        return {"strengths": {}, "iterations": 0}
    strength = {p: 1.0 for p in players}
    for iteration in range(1, max_iter + 1):
        new_strength = {}
        for p in players:
            numer = 0.0
            denom = 0.0
            for q in players:
                if p == q:
                    continue
                w = float(wins.get(p, {}).get(q, 0.0))
                total = w + float(wins.get(q, {}).get(p, 0.0))
                if total <= 0:
                    continue
                numer += w + prior
                denom += (total + 2.0 * prior) / (strength[p] + strength[q])
            new_strength[p] = numer / denom if denom > 0 else 1e-12
        log_mean = sum(math.log(max(v, 1e-12)) for v in new_strength.values()) / len(players)
        scale = math.exp(log_mean)
        strength = {p: max(v, 1e-12) / scale for p, v in new_strength.items()}
        if max(abs(strength[p] - 1.0) for p in players) < tol:
            return {"strengths": {p: round(v, 4) for p, v in strength.items()},
                    "iterations": iteration}
    return {"strengths": {p: round(v, 4) for p, v in strength.items()},
            "iterations": max_iter}


def format_ci(bucket: dict) -> str:
    """把区间 dict 格式化成 '52.3% (wilson 95%CI 41.1%–63.2%)'。"""
    if not bucket or bucket.get("mean") is None:
        return "n/a"
    def pct(value):
        return f"{100 * value:.1f}%"
    if bucket.get("lo") is None:
        return pct(bucket["mean"])
    return f"{pct(bucket['mean'])} ({bucket.get('method', '')} 95%CI {pct(bucket['lo'])}–{pct(bucket['hi'])})"
