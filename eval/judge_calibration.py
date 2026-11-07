"""judge 校准与仪器校验：把 LLM-as-judge 从"探索性"变成"可申报"。

输入：
- judge 输出（eval/quality_pairwise.py / eval/content_faithfulness.py 的 JSON）
- 人工盲评标签（adjudicated CSV；pairwise: pair_id,final_winner(A/B/tie)；claim: claim_id,human_label）
- 可选：密钥映射 key.json（pair_id -> delivered_side）、双人一致性 agreement.json、锚点 anchors.json

输出（calibration.json）：
- human：人工标注者之间一致性（双人 kappa）
- judge_human：judge 与人工（裁决后）的一致性、kappa、Spearman/MAE
- position_consistency / anchors / cross_family / self_consistency
- ppi：用人工校准子集对 judge 全量结果做偏差校正后的点估计与 95%CI
- usable + reasons：只有全部仪器门禁通过才 usable=true（fail-closed）

统计口径：
- 分类/胜率用 Cohen's kappa；评分类用 Spearman + MAE；
- 校正用 PPI（prediction-powered inference，Angelopoulos et al. 2023）；
- 小样本比例区间用 Clopper-Pearson/Wilson（eval/lib/stats.py）。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib import stats  # noqa: E402
import quality_spec as spec  # noqa: E402

PROTOCOL = spec.PROTOCOL_VERSION
JUDGE_VERSION = spec.JUDGE_VERSION


def read_json(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _read_csv(path) -> list[dict]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _norm(value) -> str:
    return str(value or "").strip().lower()


def _pair_outcome(row: dict) -> str | None:
    """把 pair 明细归一成 delivered/control/tie/None。

    兼容三种来源：
    1) quality_pairwise 新版：majority_choice / choice 已归一成 delivered/control/tie；
    2) 旧版 judge.py：delivered_win/control_win/tie 布尔字段；
    3) 最旧版：verdicts 两个字符串（A/B）。
    """
    choice = _norm(row.get("majority_choice") or row.get("choice"))
    if choice in ("delivered", "control", "tie"):
        return choice
    if row.get("delivered_win") is True:
        return "delivered"
    if row.get("control_win") is True:
        return "control"
    if row.get("tie") is True:
        return "tie"
    verdicts = row.get("verdicts")
    if isinstance(verdicts, list) and len(verdicts) == 2:
        first, second = _norm(verdicts[0]), _norm(verdicts[1])
        if first in ("a", "b") and second in ("a", "b"):
            # 未交换时 A=delivered；交换后 A=control。双向都指 delivered 才算 delivered 胜。
            if first == "a" and second == "b":
                return "delivered"
            if first == "b" and second == "a":
                return "control"
        if first == "tie" and second == "tie":
            return "tie"
    return None


def _load_key(path) -> dict:
    if not path:
        return {}
    data = read_json(path)
    return data.get("key") or data


def _human_pair_labels(path, key: dict) -> dict:
    """读人工裁决 CSV：pair_id -> delivered/control/tie。"""
    labels = {}
    for row in _read_csv(path):
        pair_id = str(row.get("pair_id") or "").strip()
        winner = _norm(row.get("final_winner") or row.get("winner"))
        if not pair_id or winner not in ("a", "b", "tie", "delivered", "control"):
            continue
        if winner == "tie":
            labels[pair_id] = "tie"
        elif winner in ("delivered", "control"):
            labels[pair_id] = winner
        else:
            side = str((key.get(pair_id) or {}).get("delivered_side") or "").strip().upper()
            labels[pair_id] = "delivered" if winner.upper() == side else "control"
    return labels


def _pair_consistency(payload: dict, pairs: list[dict]) -> float | None:
    aggregate = payload.get("position_consistency")
    if aggregate is not None:
        return float(aggregate)
    consistent = 0
    total = 0
    for row in pairs:
        if "consistent_after_swap" in row:
            total += 1
            consistent += 1 if row["consistent_after_swap"] else 0
    return round(consistent / total, 4) if total else None


def _anchors(payload: dict, path) -> dict:
    if not path:
        return {"provided": False, "passed": None,
                "note": "未提供锚点集；pairwise 指标可跳过，评分类指标建议提供"}
    data = read_json(path)
    items = data.get("items") or []
    clean = [float(item["judge"]) for item in items if _norm(item.get("kind")) == "clean"]
    bad = [float(item["judge"]) for item in items if _norm(item.get("kind")) == "bad"]
    if not clean or not bad:
        return {"provided": True, "passed": False, "note": "锚点集缺少 clean/bad 样本"}
    delta = sum(clean) / len(clean) - sum(bad) / len(bad)
    return {"provided": True, "delta": round(delta, 3),
            "passed": delta >= spec.JUDGE_GATES["anchor_delta_min"],
            "n_clean": len(clean), "n_bad": len(bad)}


def _content_claims(payload: dict) -> list[dict]:
    """兼容 content_faithfulness 的两种输出：顶层 claims 或 by_item[].claims。"""
    claims = payload.get("claims")
    if isinstance(claims, list) and claims:
        return claims
    flattened = []
    for item in payload.get("by_item") or []:
        for claim in item.get("claims") or []:
            if isinstance(claim, dict):
                flattened.append(claim)
    return flattened


def _cross_family(payload: dict) -> dict:
    by_judge = payload.get("by_judge") or {}
    models = sorted(by_judge)
    # 新版 quality_pairwise：pairs[].judges{model: {...}}，按 pair 对齐各 judge 的 choice
    if models and payload.get("pairs"):
        pair_maps = {}
        for model in models:
            mapping = {}
            for row in payload.get("pairs") or []:
                judge_block = (row.get("judges") or {}).get(model) or {}
                choice = _norm(judge_block.get("choice") or judge_block.get("majority_choice"))
                if choice in ("delivered", "control", "tie"):
                    mapping[str(row.get("pair_id"))] = choice
            if mapping:
                pair_maps[model] = mapping
        if len(pair_maps) >= 2:
            common = sorted(set.intersection(*[set(m) for m in pair_maps.values()]))
            if common:
                agree = sum(1 for pair_id in common
                            if len({pair_maps[m].get(pair_id) for m in models}) == 1) / len(common)
                return {"n_judges": len(models), "n_common": len(common),
                        "agreement": round(agree, 4),
                        "passed": agree >= spec.JUDGE_GATES["cross_family_spearman_min"],
                        "note": "二元结果一致率（>=0.7 通过）"}
    if len(models) < 2:
        return {"n_judges": len(models), "agreement": None, "spearman": None,
                "passed": None, "note": "单 judge，无法做跨族一致性"}
    # 退化为胜率层面比较
    pair_maps = {}
    for model in models:
        block = by_judge[model] or {}
        pairs = block.get("pairs") if isinstance(block.get("pairs"), list) else None
        if pairs:
            pair_maps[model] = {str(row.get("pair_id")): _pair_outcome(row) for row in pairs}
    if len(pair_maps) < 2:
        rates = [float((by_judge[m] or {}).get("win_rate") or 0.0) for m in models]
        spread = max(rates) - min(rates)
        return {"n_judges": len(models), "agreement": None, "spearman": None,
                "rate_spread": round(spread, 4),
                "passed": spread <= 0.15,
                "note": "仅有胜率层面，按胜率差 <=15pp 判定"}
    common = sorted(set.intersection(*[set(m) for m in pair_maps.values()]))
    if not common:
        return {"n_judges": len(models), "agreement": None, "passed": False,
                "note": "跨 judge 没有共同 pair"}
    agree = sum(1 for pair_id in common
                if len({pair_maps[m].get(pair_id) for m in models}) == 1) / len(common)
    return {"n_judges": len(models), "n_common": len(common),
            "agreement": round(agree, 4),
            "passed": agree >= spec.JUDGE_GATES["cross_family_spearman_min"],
            "note": "二元结果一致率（>=0.7 通过）"}


def _self_consistency(payload: dict, rerun_path) -> dict:
    if not rerun_path:
        return {"provided": False, "passed": None}
    rerun = read_json(rerun_path)
    first = {str(row.get("pair_id")): _pair_outcome(row) for row in payload.get("pairs") or []}
    second = {str(row.get("pair_id")): _pair_outcome(row) for row in rerun.get("pairs") or []}
    common = sorted(set(first) & set(second))
    if not common:
        return {"provided": True, "passed": False, "note": "重跑没有共同 pair"}
    agree = sum(1 for pair_id in common if first[pair_id] == second[pair_id]) / len(common)
    return {"provided": True, "n": len(common), "agreement": round(agree, 4),
            "passed": agree >= spec.JUDGE_GATES["self_consistency_min"]}


def _human_agreement(path, fallback: dict | None) -> dict:
    if fallback:
        return {"source": "provided", **fallback}
    if not path:
        return {"source": None, "n": 0, "kappa": None, "agreement": None,
                "note": "缺少双人标注一致性（agreement.json）；质量结论不能申报"}
    data = read_json(path)
    return {"source": "agreement.json", **{key: data.get(key) for key in
                                           ("n", "kappa", "agreement", "usable", "by_stratum")}}


def _ppi_pairwise(payload_pairs: list[dict], human: dict) -> dict:
    labeled_y: list[int] = []
    labeled_f: list[int] = []
    unlabeled_f: list[int] = []
    for row in payload_pairs:
        pair_id = str(row.get("pair_id") or "")
        judge_outcome = _pair_outcome(row)
        if judge_outcome is None:
            continue
        judge_delivered = 1 if judge_outcome == "delivered" else 0
        human_outcome = human.get(pair_id)
        if human_outcome is None:
            unlabeled_f.append(judge_delivered)
        else:
            labeled_f.append(judge_delivered)
            labeled_y.append(1 if human_outcome == "delivered" else 0)
    if not labeled_y:
        return {"available": False, "note": "没有人工标签与 judge 结果重合的 pair"}
    result = stats.ppi_proportion(labeled_y, labeled_f, unlabeled_f or labeled_f)
    result["available"] = True
    result["human_labeled_win_rate"] = round(sum(labeled_y) / len(labeled_y), 4)
    return result


def _ppi_claims(payload: dict, human: dict) -> dict:
    claims = _content_claims(payload)
    labeled_y, labeled_f, unlabeled_f = [], [], []
    for row in claims:
        claim_id = str(row.get("claim_id") or row.get("id") or "")
        judge_label = _norm(row.get("label") or row.get("judge_label"))
        if judge_label not in ("supported", "contradicted", "not_supported"):
            continue
        judge_ok = 1 if judge_label == "supported" else 0
        human_label = _norm(human.get(claim_id))
        if human_label in ("supported", "contradicted", "not_supported"):
            labeled_y.append(1 if human_label == "supported" else 0)
            labeled_f.append(judge_ok)
        else:
            unlabeled_f.append(judge_ok)
    if not labeled_y:
        return {"available": False, "note": "没有人工标签与 judge claim 重合"}
    result = stats.ppi_proportion(labeled_y, labeled_f, unlabeled_f or labeled_f)
    result["available"] = True
    return result


def _human_claims(path) -> dict:
    labels = {}
    for row in _read_csv(path):
        claim_id = str(row.get("claim_id") or "").strip()
        label = _norm(row.get("human_label") or row.get("label"))
        if claim_id and label in ("supported", "contradicted", "not_supported"):
            labels[claim_id] = label
    return labels


def _human_reject_labels(path) -> dict:
    labels = {}
    for row in _read_csv(path):
        item_id = str(row.get("item_id") or row.get("reject_id") or "").strip()
        label = _norm(row.get("human_label") or row.get("label"))
        if item_id and label in ("reasonable_reject", "should_pass", "needs_info"):
            labels[item_id] = label
    return labels


def load_human_labels(path, metric: str, key: dict | None = None) -> dict:
    """按指标读取人工标签：CSV（协议产物）或 JSON（键值映射，便于离线复算）。"""
    path = Path(path)
    if path.suffix.lower() == ".json":
        data = read_json(path)
        if isinstance(data, dict) and isinstance(data.get("labels"), dict):
            data = data["labels"]
        return {str(key_): _norm(value) for key_, value in (data or {}).items()}
    if metric == "content_faithfulness":
        return _human_claims(path)
    if metric == "false_reject":
        return _human_reject_labels(path)
    return _human_pair_labels(path, key or {})


def calibrate(judge_payload: dict, human_labels, metric: str = "match_quality",
              key: dict | None = None, anchors_path=None, rerun_path=None,
              human_agreement: dict | None = None) -> dict:
    """主入口：返回 calibration dict（usable 为 fail-closed 门禁）。"""
    spec.get(metric)  # 校验 metric 合法
    key = key or {}
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    reasons: list[str] = []
    human_info = _human_agreement(None, human_agreement)

    if metric == "match_quality":
        pairs = judge_payload.get("pairs") or []
        labels = human_labels if isinstance(human_labels, dict) else _human_pair_labels(human_labels, key)
        judged = [(str(row.get("pair_id")), _pair_outcome(row)) for row in pairs]
        judged = [(pair_id, outcome) for pair_id, outcome in judged if outcome is not None]
        common = [(pair_id, outcome) for pair_id, outcome in judged if pair_id in labels]
        judge_human = {"n": len(common), "agreement": None, "kappa": None, "spearman": None}
        if common:
            judge_series = [1 if outcome == "delivered" else 0 for _, outcome in common]
            human_series = [1 if labels[pair_id] == "delivered" else 0 for pair_id, _ in common]
            judge_human = {
                "n": len(common),
                "agreement": round(stats.agreement_rate(judge_series, human_series), 4),
                "kappa": round(stats.cohen_kappa(judge_series, human_series), 4),
                "spearman": round(stats.spearman(judge_series, human_series), 4)
                if len(set(human_series)) > 1 else None,
                "confusion": {
                    "both_delivered": sum(1 for a, b in zip(judge_series, human_series) if a == 1 and b == 1),
                    "judge_only": sum(1 for a, b in zip(judge_series, human_series) if a == 1 and b == 0),
                    "human_only": sum(1 for a, b in zip(judge_series, human_series) if a == 0 and b == 1),
                    "neither": sum(1 for a, b in zip(judge_series, human_series) if a == 0 and b == 0),
                },
            }
        position = _pair_consistency(judge_payload, pairs)
        ppi = _ppi_pairwise(pairs, labels)
        n_total = int(judge_payload.get("n_pairs_judged") or len(judged))
        if judge_human["n"] < 50:
            reasons.append(f"人工校准样本 {judge_human['n']} < 50")
        if judge_human["kappa"] is None:
            reasons.append("缺少 judge-human 一致率（人工/ judge pair 未对齐）")
        elif judge_human["kappa"] < spec.JUDGE_GATES["human_kappa_min"]:
            reasons.append(f"judge-human kappa={judge_human['kappa']} < {spec.JUDGE_GATES['human_kappa_min']}")
        if position is None:
            reasons.append("缺少 position consistency（未做双向交换）")
        elif position < spec.JUDGE_GATES["position_consistency_min"]:
            reasons.append(f"position consistency={position} < {spec.JUDGE_GATES['position_consistency_min']}")
        anchor = _anchors(judge_payload, anchors_path)
        if anchor.get("passed") is False:
            reasons.append(f"锚点校验失败：{anchor.get('note') or anchor.get('delta')}")
    elif metric == "content_faithfulness":
        labels = human_labels if isinstance(human_labels, dict) else _human_claims(human_labels)
        claims = _content_claims(judge_payload)
        judged = [(str(row.get("claim_id") or row.get("id")), _norm(row.get("label")))
                  for row in claims]
        judged = [(claim_id, label) for claim_id, label in judged
                  if label in ("supported", "contradicted", "not_supported")]
        common = [(claim_id, label) for claim_id, label in judged if claim_id in labels]
        judge_human = {"n": len(common), "agreement": None, "kappa": None, "spearman": None}
        if common:
            judge_series = [1 if label == "supported" else 0 for _, label in common]
            human_series = [1 if labels[claim_id] == "supported" else 0 for claim_id, _ in common]
            judge_human = {
                "n": len(common),
                "agreement": round(stats.agreement_rate(judge_series, human_series), 4),
                "kappa": round(stats.cohen_kappa(judge_series, human_series), 4),
            }
        position = None
        ppi = _ppi_claims(judge_payload, labels)
        n_total = int(judge_payload.get("n_claims") or len(judged))
        if judge_human["n"] < 50:
            reasons.append(f"人工校准 claim {judge_human['n']} < 50")
        if judge_human["kappa"] is None:
            reasons.append("缺少 judge-human 一致率（claim id 未对齐）")
        elif judge_human["kappa"] < spec.JUDGE_GATES["human_kappa_min"]:
            reasons.append(f"judge-human kappa={judge_human['kappa']} < {spec.JUDGE_GATES['human_kappa_min']}")
        anchor = _anchors(judge_payload, anchors_path)
        if anchor.get("passed") is False:
            reasons.append(f"锚点校验失败：{anchor.get('note') or anchor.get('delta')}")
    elif metric == "false_reject":
        labels = human_labels if isinstance(human_labels, dict) else _human_reject_labels(human_labels)
        soft = judge_payload.get("soft") or {}
        items = soft.get("items") or []
        judged = [(str(row.get("item_id") or row.get("reject_id") or ""), _norm(row.get("label")))
                  for row in items]
        judged = [(item_id, label) for item_id, label in judged
                  if label in ("reasonable_reject", "should_pass", "needs_info")]
        common = [(item_id, label) for item_id, label in judged if item_id in labels]
        judge_human = {"n": len(common), "agreement": None, "kappa": None, "spearman": None}
        if common:
            judge_series = [1 if label == "should_pass" else 0 for _, label in common]
            human_series = [1 if labels[item_id] == "should_pass" else 0 for item_id, _ in common]
            judge_human = {
                "n": len(common),
                "agreement": round(stats.agreement_rate(judge_series, human_series), 4),
                "kappa": round(stats.cohen_kappa(judge_series, human_series), 4),
            }
        labeled_y, labeled_f, unlabeled_f = [], [], []
        for item_id, label in judged:
            judge_should_pass = 1 if label == "should_pass" else 0
            if item_id in labels:
                labeled_y.append(1 if labels[item_id] == "should_pass" else 0)
                labeled_f.append(judge_should_pass)
            else:
                unlabeled_f.append(judge_should_pass)
        if labeled_y:
            ppi = stats.ppi_proportion(labeled_y, labeled_f, unlabeled_f or labeled_f)
            ppi["available"] = True
        else:
            ppi = {"available": False, "note": "没有人工标签与 judge 软冲突结果重合"}
        position = None
        anchor = {"provided": False, "passed": None, "note": "误拒率不需要 1-5 分锚点"}
        n_total = int(soft.get("n") or len(judged))
        if judge_human["n"] < 50:
            reasons.append(f"人工校准样本 {judge_human['n']} < 50")
        if judge_human["kappa"] is None:
            reasons.append("缺少 judge-human 一致率（人工/ judge 软冲突 item 未对齐）")
        elif judge_human["kappa"] < spec.JUDGE_GATES["human_kappa_min"]:
            reasons.append(f"judge-human kappa={judge_human['kappa']} < {spec.JUDGE_GATES['human_kappa_min']}")
    else:
        raise ValueError(f"calibrate 暂不支持 metric={metric}"
                         "（支持 match_quality/content_faithfulness/false_reject）")

    # 人工标注者之间的一致性（双人 kappa）是质量结论的硬前提
    if human_info.get("kappa") is None:
        reasons.append("缺少双人标注一致性（agreement.json 的 kappa）")
    elif float(human_info["kappa"]) < spec.JUDGE_GATES["human_kappa_min"]:
        reasons.append(f"双人 kappa={human_info['kappa']} < {spec.JUDGE_GATES['human_kappa_min']}")

    cross = _cross_family(judge_payload)
    if cross.get("passed") is False:
        reasons.append(f"跨族一致性未通过：{cross.get('note')}")
    consistency = _self_consistency(judge_payload, rerun_path)
    if consistency.get("passed") is False:
        reasons.append(f"judge 自一致性未通过：{consistency.get('note')}")

    usable = not reasons
    return {
        "metric": metric,
        "protocol": PROTOCOL,
        "judge_version": JUDGE_VERSION,
        "generated_at": generated_at,
        "n_judged": n_total,
        "n_labeled": judge_human["n"],
        "human": human_info,
        "judge_human": judge_human,
        "position_consistency": position,
        "anchors": anchor,
        "cross_family": cross,
        "self_consistency": consistency,
        "ppi": ppi,
        "usable": usable,
        "reasons": reasons,
        "gates": dict(spec.JUDGE_GATES),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="judge 校准与仪器校验（fail-closed）")
    parser.add_argument("--judge", required=True, type=Path, help="judge 输出 JSON")
    parser.add_argument("--human", required=True, type=Path, help="人工标注 CSV")
    parser.add_argument("--metric", default="match_quality",
                        choices=("match_quality", "content_faithfulness", "false_reject"))
    parser.add_argument("--key", type=Path, default=None, help="materials 的 key.json")
    parser.add_argument("--human-agreement", type=Path, default=None,
                        help="agreement.py 产出的 agreement.json（双人 kappa）")
    parser.add_argument("--anchors", type=Path, default=None, help="锚点集 JSON")
    parser.add_argument("--rerun", type=Path, default=None, help="judge 重跑输出（自一致性）")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)

    payload = read_json(args.judge)
    key = _load_key(args.key)
    agreement = read_json(args.human_agreement) if args.human_agreement else None
    human = load_human_labels(args.human, args.metric, key)
    result = calibrate(payload, human, metric=args.metric, key=key,
                       anchors_path=args.anchors, rerun_path=args.rerun,
                       human_agreement=agreement)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: result[key] for key in
                      ("metric", "n_labeled", "usable", "reasons", "judge_human")},
                     ensure_ascii=False, indent=2))
    return 0 if result["usable"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
