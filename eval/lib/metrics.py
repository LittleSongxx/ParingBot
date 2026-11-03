#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线评测指标（纯标准库）。

四个指标分别回答四个问题：

* delivery_stats：每轮要了几人、交了几人、跑没跑完 —— 交付是否达标；
* agreement：交付名单和冻结 gold 的重合度，Precision 分母用 requested（短交付直接扣分）、
  Recall 分母用 min(requested, gold)；
* ndcg_penalized：交付排序质量；交付不足 K 人时补 0 收益到 K，短交付按未交付算 0 分，
  所以 1/8 交付不可能拿到 NDCG=1.0；
* bootstrap_ci / paired_diff_ci / mde：小样本下的均值置信区间、配对差置信区间与
  最小可检测效应，用来判断「提升」是不是噪声。

输入结构沿用 quality bundle / matrix 报告的两套字段，读到哪个用哪个，
避免评测工具之间为字段名再分叉。
"""
from __future__ import annotations

import math
import random
import statistics
from typing import Iterable, Sequence

DEFAULT_SEED = 20261104
DEFAULT_ITERATIONS = 10000
DEFAULT_K = 8

# matrix / bundle 里表示「跑完了」与「跑失败」的状态取值
DONE_STATUSES = {"已完成", "完成", "completed", "Completed", "done", "DONE"}
FAILED_STATUSES = {"运行失败", "失败", "failed", "Failed", "error", "ERROR"}


def _as_count(value) -> int | None:
    """把交付数统一成整数：int / list 长度 / None。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, (list, tuple, set)):
        return len(value)
    return None


def _applicant_of(run: dict) -> dict:
    if isinstance(run.get("applicant"), dict):
        return run["applicant"]
    return {}


def _requested_of(run: dict, default: int = DEFAULT_K) -> int:
    """这一轮要求交付几人：bundle 看 task.deliver_count，matrix 看 requested。"""
    for value in (run.get("requested"), run.get("deliver_count"),
                  (run.get("task") or {}).get("deliver_count")):
        count = _as_count(value)
        if count:
            return count
    return default


def _delivered_of(run: dict) -> int:
    """这一轮实际交付几人。交付数优先看汇总字段，其次数 candidates 里的 delivered。"""
    for value in (run.get("delivered"), run.get("delivered_to_user")):
        count = _as_count(value)
        if count is not None:
            return count
    candidates = run.get("candidates") or []
    return len([item for item in candidates if isinstance(item, dict) and item.get("delivered")])


def _delivered_ids(run: dict, k: int) -> list:
    """按 delivered_rank 取前 k 个交付候选的 id（bundle 口径）。"""
    candidates = [item for item in (run.get("candidates") or [])
                  if isinstance(item, dict) and item.get("delivered")]
    candidates.sort(key=lambda item: (item.get("delivered_rank")
                                      if item.get("delivered_rank") is not None else 10 ** 9,
                                      item.get("id") if item.get("id") is not None else 10 ** 9))
    return [item.get("id") for item in candidates[:max(0, k)]]


def _status_of(run: dict) -> str | None:
    for value in (run.get("status"), run.get("run_status"),
                  (run.get("run") or {}).get("status"),
                  (run.get("task") or {}).get("status")):
        if value:
            return str(value)
    return None


def _key_of(run: dict) -> str:
    run_meta = run.get("run") or {}
    for value in (run.get("key"), run.get("scenario"), run.get("account"),
                  run_meta.get("run_no"), run_meta.get("id"), run.get("run_id")):
        if value not in (None, ""):
            return str(value)
    return ""


def _iter_runs(runs: Iterable[dict]):
    """兼容两种输入：扁平 run 列表，或带 runs 子列表的场景矩阵记录。"""
    for item in runs or []:
        if not isinstance(item, dict):
            continue
        nested = item.get("runs")
        if isinstance(nested, list):
            # 场景矩阵记录：负向/未跑的 runs 为空，不产生任何运行行
            for sub in nested:
                if not isinstance(sub, dict):
                    continue
                merged = dict(sub)
                merged.setdefault("key", item.get("key") or item.get("scenario"))
                merged.setdefault("account", item.get("account"))
                yield merged
        else:
            yield item


def delivery_stats(runs: Iterable[dict]) -> dict:
    """逐轮统计「要求交付 / 实际交付 / 运行状态」，并给出总体交付率与完成率。"""
    rows = []
    for index, run in enumerate(_iter_runs(runs)):
        if not isinstance(run, dict):
            continue
        requested = _requested_of(run)
        delivered = _delivered_of(run)
        status = _status_of(run)
        rows.append({
            "index": index,
            "key": _key_of(run),
            "requested": requested,
            "delivered": delivered,
            "status": status,
            "delivered_ratio": round(delivered / requested, 4) if requested else 0.0,
            "short": delivered < requested,
        })
    total = len(rows)
    requested_total = sum(row["requested"] for row in rows)
    delivered_total = sum(row["delivered"] for row in rows)
    completed = len([row for row in rows if row["status"] in DONE_STATUSES])
    failed = len([row for row in rows if row["status"] in FAILED_STATUSES])
    aggregate = {
        "runs": total,
        "requested_total": requested_total,
        "delivered_total": delivered_total,
        "avg_requested": round(requested_total / total, 4) if total else 0.0,
        "avg_delivered": round(delivered_total / total, 4) if total else 0.0,
        "delivery_rate": round(delivered_total / requested_total, 4) if requested_total else 0.0,
        "completed": completed,
        "failed": failed,
        "completion_rate": round(completed / total, 4) if total else 0.0,
        "short_runs": len([row for row in rows if row["short"]]),
    }
    return {"runs": rows, "aggregate": aggregate}


def _label_list(labels) -> list[dict]:
    """labels 支持 {"labels": [...]}、list、或按 username 索引的 dict 三种形态。"""
    if labels is None:
        return []
    if isinstance(labels, dict):
        items = labels.get("labels")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
        return [dict(value, username=key) if isinstance(value, dict) else {}
                for key, value in labels.items()]
    if isinstance(labels, (list, tuple)):
        return [item for item in labels if isinstance(item, dict)]
    return []


def _label_index(labels) -> tuple[dict, dict]:
    """返回 (按 username, 按 id) 两份标签索引。"""
    by_name: dict = {}
    by_id: dict = {}
    for item in _label_list(labels):
        name = item.get("username")
        if name:
            by_name[name] = item
        member_id = item.get("member_id") or item.get("applicant_id") or item.get("id")
        if member_id is not None:
            by_id[member_id] = item
    return by_name, by_id


def _label_for(run: dict, by_name: dict, by_id: dict) -> dict | None:
    applicant = _applicant_of(run)
    name = applicant.get("username")
    if name and name in by_name:
        return by_name[name]
    member_id = applicant.get("id")
    if member_id is not None and member_id in by_id:
        return by_id[member_id]
    return None


def agreement(bundle, labels, k: int = DEFAULT_K) -> dict:
    """交付名单与冻结 gold 的 Precision / Recall。

    * Precision 分母固定为 requested：交付不足时按缺额扣分，不会被「少交几个都命中」抬高；
    * Recall 分母为 min(requested, gold 数)：与旧口径一致，gold 不足 K 时不会虚低。
    """
    data = bundle or {}
    runs = data.get("runs") if isinstance(data, dict) else data
    by_name, by_id = _label_index(labels)
    rows = []
    for run in runs or []:
        if not isinstance(run, dict):
            continue
        label = _label_for(run, by_name, by_id)
        if label is None:
            rows.append({"key": _key_of(run), "skipped": True,
                         "reason": "该申请人在冻结标签里没有记录"})
            continue
        requested = _requested_of(run, k)
        delivered = _delivered_ids(run, requested)
        gold_ids = set(label.get("gold_ids") or [])
        hits = [candidate_id for candidate_id in delivered if candidate_id in gold_ids]
        precision = len(hits) / requested if requested else 0.0
        denominator = min(requested, len(gold_ids))
        recall = len(hits) / denominator if denominator else 0.0
        rows.append({
            "key": _key_of(run),
            "applicant": _applicant_of(run).get("nickname"),
            "requested": requested,
            "delivered": len(delivered),
            "gold": len(gold_ids),
            "hits": len(hits),
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "hit_ids": hits,
            "miss_gold_ids": sorted(gold_ids - set(hits), key=lambda value: str(value)),
            "extra_ids": [candidate_id for candidate_id in delivered
                          if candidate_id not in gold_ids],
        })
    valid = [row for row in rows if not row.get("skipped")]
    aggregate = {
        "runs": len(valid),
        "skipped": len(rows) - len(valid),
        "avg_precision": round(sum(row["precision"] for row in valid) / len(valid), 4) if valid else 0.0,
        "avg_recall": round(sum(row["recall"] for row in valid) / len(valid), 4) if valid else 0.0,
        "hits_total": sum(row["hits"] for row in valid),
        "delivered_total": sum(row["delivered"] for row in valid),
    }
    if aggregate["delivered_total"]:
        aggregate["micro_precision"] = round(aggregate["hits_total"] / aggregate["delivered_total"], 4)
    else:
        aggregate["micro_precision"] = 0.0
    return {"rows": rows, "aggregate": aggregate}


def _grades_of(label: dict, k: int = DEFAULT_K) -> dict:
    """冻结标签的分级收益：ranked 第 1-2 名=3，3-5 名=2，6-8 名=1，其余=0。"""
    grades: dict = {}
    for rank, item in enumerate((label.get("ranked") or [])[:k], 1):
        if not isinstance(item, dict):
            continue
        identifier = item.get("id")
        if identifier is None:
            continue
        grades[identifier] = 3 if rank <= 2 else (2 if rank <= 5 else 1)
    return grades


def ndcg_penalized(bundle, labels, k: int = DEFAULT_K) -> dict:
    """带短交付惩罚的 NDCG@K。

    交付列表按 delivered_rank 取前 min(k, requested) 个，然后补 0 收益到 K：
    少交的人按「本该有、但是没给」处理，直接拉低 DCG，而不是只对交付的人算平均。
    """
    data = bundle or {}
    runs = data.get("runs") if isinstance(data, dict) else data
    by_name, by_id = _label_index(labels)
    rows = []
    for run in runs or []:
        if not isinstance(run, dict):
            continue
        label = _label_for(run, by_name, by_id)
        if label is None:
            continue
        requested = _requested_of(run, k)
        limit = max(0, min(k, requested))
        delivered = _delivered_ids(run, limit)
        grades = _grades_of(label, k)
        gains = [(2 ** grades.get(identifier, 0)) - 1 for identifier in delivered]
        gains += [0] * (k - len(gains))  # 短交付补 0 收益到 K
        dcg = sum(gain / math.log2(index + 2) for index, gain in enumerate(gains))
        ideal = sorted(((2 ** grade) - 1 for grade in grades.values()), reverse=True)[:k]
        idcg = sum(gain / math.log2(index + 2) for index, gain in enumerate(ideal))
        rows.append({
            "key": _key_of(run),
            "applicant": _applicant_of(run).get("nickname"),
            "requested": requested,
            "delivered": len(delivered),
            "gold": len(grades),
            "ndcg": round(dcg / idcg, 4) if idcg else 0.0,
        })
    aggregate = {
        "runs": len(rows),
        "avg_ndcg": round(sum(row["ndcg"] for row in rows) / len(rows), 4) if rows else 0.0,
    }
    return {"rows": rows, "aggregate": aggregate}


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def bootstrap_ci(values: Iterable[float], iterations: int = DEFAULT_ITERATIONS,
                 seed: int = DEFAULT_SEED) -> dict:
    """均值的 bootstrap 百分位置信区间（2.5% / 97.5%）。

    样本很小（评测通常只有 8-10 个场景）时，均值差几十个百分点可能全是噪声，
    所以报均值的同一条线上必须带区间。
    """
    sample = [float(value) for value in values or []]
    total = max(1, int(iterations))
    if not sample:
        return {"n": 0, "mean": 0.0, "lo": 0.0, "hi": 0.0,
                "iterations": total, "seed": seed}
    rng = random.Random(seed)
    size = len(sample)
    means = []
    for _ in range(total):
        means.append(sum(sample[rng.randrange(size)] for _ in range(size)) / size)
    means.sort()
    low = means[int(0.025 * total)]
    high = means[min(total - 1, int(0.975 * total))]
    return {
        "n": size,
        "mean": round(_mean(sample), 6),
        "lo": round(low, 6),
        "hi": round(high, 6),
        "iterations": total,
        "seed": seed,
    }


def paired_diff_ci(left: Iterable[float], right: Iterable[float],
                   iterations: int = DEFAULT_ITERATIONS,
                   seed: int = DEFAULT_SEED) -> dict:
    """配对差（right - left）的 bootstrap 置信区间。

    同一批场景跑两版才有意义：逐场景求差再重采样，比两个独立均值区间更敏感。
    """
    left_values = [float(value) for value in left or []]
    right_values = [float(value) for value in right or []]
    if len(left_values) != len(right_values):
        raise ValueError(f"配对数不一致：left={len(left_values)} right={len(right_values)}")
    diffs = [b - a for a, b in zip(left_values, right_values)]
    total = max(1, int(iterations))
    if not diffs:
        return {"n": 0, "mean_diff": 0.0, "lo": 0.0, "hi": 0.0,
                "iterations": total, "seed": seed}
    rng = random.Random(seed)
    size = len(diffs)
    means = []
    for _ in range(total):
        means.append(sum(diffs[rng.randrange(size)] for _ in range(size)) / size)
    means.sort()
    return {
        "n": size,
        "mean_diff": round(_mean(diffs), 6),
        "lo": round(means[int(0.025 * total)], 6),
        "hi": round(means[min(total - 1, int(0.975 * total))], 6),
        "left_mean": round(_mean(left_values), 6),
        "right_mean": round(_mean(right_values), 6),
        "iterations": total,
        "seed": seed,
    }


def mde(sd: float, n: int, alpha: float = 0.05, power: float = 0.8) -> float:
    """最小可检测效应量（双侧 alpha、给定检验功效）。

    MDE = (z_(1-alpha/2) + z_power) * sd / sqrt(n)。样本越少、方差越大，
    能宣称的最小提升就越大；报告据此判断「提升」是否超出噪声水位。
    """
    if n is None or n <= 0:
        return float("inf")
    if sd is None or sd <= 0:
        return 0.0
    normal = statistics.NormalDist()
    z_alpha = normal.inv_cdf(1 - alpha / 2)
    z_power = normal.inv_cdf(power)
    return round((z_alpha + z_power) * sd / math.sqrt(n), 6)