#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""内容质量（画像/解释文本）rubric：用异族模型给 bundle 里的 content 打分。

当前质量指标主要覆盖“交付/匹配”，内容（画像 summary、标签、解释）没有独立口径；
本脚本补这一维：faithful / coherent / readable / respectful / overall（1-5）。
注意：这是代理评审（E2.5），不是人工真值；结果只能作为内容质量的探索性信号。

审计修正（2026-11-05，A3）：
* 抽样改为确定性随机抽样（random.Random(SAMPLE_SEED)）：先收集 applicants + delivered
  candidates 的全部 portrait 非空条目，再 shuffle 取 limit。旧实现“先 applicant 后
  candidate 顺序截断”会让样本不可核、且总是偏向 run 头部；
* 输出 JSON 记录实际 n / sample_ids / roles / 均值 bootstrap 95% CI / bundle_meta /
  judge_model，不再只报“样本 20 条、均值 4.875”这种不可复核的数字；
* 新增 --min-items（默认 1）：样本数低于阈值直接 exit 1，避免空样本也打出均值。

用法：
  python eval/content_quality.py --bundle quality-bundle.json --limit 20 \
      --env-file .env.eval --out content-report.md --json content-report.json
"""
from __future__ import annotations

import argparse
import json
import random
import re
import statistics
import sys
import urllib.request
from pathlib import Path

EVAL = Path(__file__).resolve().parent
if str(EVAL) not in sys.path:
    sys.path.insert(0, str(EVAL))

# 均值 bootstrap：优先用 eval/lib/metrics.py 的统一实现（纯标准库），缺失时本地兜底。
try:  # pragma: no cover - 正常路径
    from lib.metrics import bootstrap_ci as _metrics_bootstrap_ci
except ImportError:  # pragma: no cover
    _metrics_bootstrap_ci = None

SAMPLE_SEED = 20261104
DEFAULT_ITERATIONS = 2000

RUBRIC = """你是内容质量评审员。对每条租客画像（portrait summary + tags）按 1-5 打分：
- faithful：陈述是否与档案字段一致（年龄/性别/预算/作息/宠物/吸烟/整洁/租期），无编造；
- coherent：标签与 summary 是否自洽，不互相矛盾；
- readable：表达通顺、简洁、可读；
- respectful：无歧视/冒犯/越权判断；
- overall：综合质量。
只输出 JSON 数组，对象字段 item_id, faithful, coherent, readable, respectful, overall, reason（<=40字）。
不要 markdown、不要解释。
"""


def load_env(path: Path) -> dict:
    values = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def collect_items(bundle: dict) -> list[dict]:
    """收集所有 portrait 非空的条目（applicant + delivered candidate），item_id 稳定。"""
    items = []
    applicant_count = 0
    candidate_count = 0
    for run in bundle.get("runs", []) or []:
        applicant = run.get("applicant") or {}
        if applicant.get("portrait"):
            applicant_count += 1
            items.append({"item_id": f"A{applicant_count}", "role": "applicant",
                          "profile": applicant, "portrait": applicant.get("portrait")})
        for candidate in run.get("candidates", []) or []:
            if not isinstance(candidate, dict) or not candidate.get("delivered"):
                continue
            if not candidate.get("portrait"):
                continue
            candidate_count += 1
            items.append({"item_id": f"C{candidate_count}", "role": "candidate",
                          "profile": candidate, "portrait": candidate.get("portrait")})
    return items


def sample_items(bundle: dict, limit: int) -> list[dict]:
    """确定性随机抽样：先收集全部 portrait 非空条目，再用固定种子 shuffle 取 limit。

    返回的每条 item 都带 item_id / role；同样的 bundle+limit 每次抽到同一批样本。
    """
    items = collect_items(bundle)
    random.Random(SAMPLE_SEED).shuffle(items)
    return items[:max(0, int(limit))]


def _local_bootstrap_mean_ci(values: list[float], iterations: int = DEFAULT_ITERATIONS,
                             seed: int = SAMPLE_SEED) -> dict:
    """均值的 bootstrap 百分位 95% CI（纯标准库兜底实现）。"""
    sample = [float(value) for value in values or []]
    total = max(1, int(iterations))
    if not sample:
        return {"n": 0, "mean": 0.0, "lo": 0.0, "hi": 0.0, "iterations": total, "seed": seed}
    rng = random.Random(seed)
    size = len(sample)
    means = [sum(sample[rng.randrange(size)] for _ in range(size)) / size for _ in range(total)]
    means.sort()
    return {"n": size, "mean": round(sum(sample) / size, 3),
            "lo": round(means[int(0.025 * total)], 3),
            "hi": round(means[min(total - 1, int(0.975 * total))], 3),
            "iterations": total, "seed": seed}


def mean_ci(values: list[float], iterations: int = DEFAULT_ITERATIONS,
            seed: int = SAMPLE_SEED) -> dict:
    """均值 bootstrap 95% CI：优先 lib.metrics.bootstrap_ci，缺失时本地兜底。"""
    sample = [float(value) for value in values or []]
    if _metrics_bootstrap_ci is not None:
        try:
            result = _metrics_bootstrap_ci(sample, iterations=iterations, seed=seed)
            return {"n": int(result.get("n", len(sample)) or 0),
                    "mean": round(float(result.get("mean", 0.0) or 0.0), 3),
                    "lo": round(float(result.get("lo", 0.0) or 0.0), 3),
                    "hi": round(float(result.get("hi", 0.0) or 0.0), 3),
                    "iterations": int(result.get("iterations", iterations) or iterations),
                    "seed": int(result.get("seed", seed) or seed)}
        except Exception:  # noqa: BLE001 - fallback 兜底优先于崩溃
            pass
    return _local_bootstrap_mean_ci(sample, iterations, seed)


def profile_text(profile: dict) -> str:
    fields = ("gender", "birth_date", "rent_budget", "lease_term", "schedule_type", "tidiness",
              "has_pet", "smoking", "occupation", "store_id", "store_area")
    return "；".join(f"{key}={profile.get(key)}" for key in fields if profile.get(key) is not None)


def call_judge(env: dict, items: list[dict], max_tokens: int = 4096) -> list[dict]:
    base_url = env["EVAL_JUDGE_BASE_URL"].rstrip("/")
    api_key = env["EVAL_JUDGE_API_KEY"]
    model = env["EVAL_JUDGE_MODEL"]
    materials = [{"item_id": item["item_id"], "profile": profile_text(item["profile"]),
                  "portrait": item["portrait"]} for item in items]
    prompt = RUBRIC + "\n\n材料：\n" + json.dumps(materials, ensure_ascii=False)
    payload = {"model": model, "temperature": 0.0, "max_tokens": max_tokens,
               "messages": [{"role": "user", "content": prompt}]}
    request = urllib.request.Request(
        base_url + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST")
    with urllib.request.urlopen(request, timeout=180) as response:
        body = json.loads(response.read().decode("utf-8"))
    content = body["choices"][0]["message"].get("content") or ""
    content = re.sub(r"```(?:json)?", "", content).strip("` \n")
    match = re.search(r"\[.*\]", content, re.S)
    if not match:
        raise RuntimeError("judge 响应中没有 JSON 数组：" + content[:300])
    return json.loads(match.group(0))


def rule_warnings(items: list[dict]) -> list[dict]:
    warnings = []
    for item in items:
        profile = item["profile"]
        portrait = item["portrait"] or {}
        text = str(portrait.get("summary") or "") + " " + str(portrait.get("lifestyle_tags") or "")
        no_pet_phrase = any(phrase in text for phrase in ("不养宠物", "不养猫", "不养狗", "不养仓鼠", "无宠物"))
        if profile.get("has_pet") == "无" and not no_pet_phrase and re.search(r"养(猫|狗|仓鼠|鱼|宠物)|有宠物", text):
            warnings.append({"item_id": item["item_id"], "reason": "portrait 提到养宠但档案 has_pet=无"})
        if profile.get("smoking") == "不吸烟" and "吸烟" in text and "不吸烟" not in text:
            warnings.append({"item_id": item["item_id"], "reason": "portrait 提到吸烟但档案不吸烟"})
    return warnings


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="内容质量 rubric（代理评审）")
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--env-file", type=Path, default=Path(".env.eval"))
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--min-items", type=int, default=1,
                        help="实际可抽样本数低于该值直接失败（exit 1），默认 1")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)
    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    items = sample_items(bundle, args.limit)
    if len(items) < args.min_items:
        print(f"内容质量样本不足：实际 {len(items)} 条 < --min-items {args.min_items}"
              "（只取 portrait 非空的 applicant/delivered candidate）", file=sys.stderr)
        return 1
    env = load_env(args.env_file)
    if not all(env.get(key) for key in ("EVAL_JUDGE_BASE_URL", "EVAL_JUDGE_API_KEY", "EVAL_JUDGE_MODEL")):
        raise SystemExit("缺少 EVAL_JUDGE_* 配置")
    rows = []
    for start in range(0, len(items), 4):
        rows.extend(call_judge(env, items[start:start + 4]))
    by_id = {row.get("item_id"): row for row in rows}
    dims = ("faithful", "coherent", "readable", "respectful", "overall")
    values = {dim: [float(by_id[item["item_id"]][dim]) for item in items
                    if item["item_id"] in by_id and dim in by_id[item["item_id"]]]
              for dim in dims}
    summary = {dim: round(statistics.mean(vals), 3) if vals else None for dim, vals in values.items()}
    ci95 = {dim: mean_ci(vals) for dim, vals in values.items() if vals}
    result = {"items": len(items), "n": len(items), "scored": len(rows), "means": summary,
              "ci95": ci95,
              "sample_ids": [item["item_id"] for item in items],
              "roles": {item["item_id"]: item["role"] for item in items},
              "bundle_meta": bundle.get("meta") or {},
              "judge_model": env.get("EVAL_JUDGE_MODEL"),
              "rule_warnings": rule_warnings(items), "rows": rows,
              "note": "内容质量代理评审（E2.5），不是人工真值；n=实际抽样条数，CI 为均值 bootstrap 95%。"}
    if args.json:
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = ["# 内容质量代理评审（不是人工真值）", "",
             f"- 实际样本：{len(items)} 条（sample_ids: {', '.join(result['sample_ids'])}）；"
             f"评分：{len(rows)} 条；judge：{result['judge_model']}"]
    for dim, value in summary.items():
        ci = ci95.get(dim)
        ci_text = f"（95% CI {ci['lo']}–{ci['hi']}）" if ci else ""
        lines.append(f"- {dim}: {value}{ci_text}")
    lines += [f"- 规则 warning：{len(result['rule_warnings'])} 条"]
    if args.out:
        args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"n": len(items), "means": summary,
                      "warnings": len(result["rule_warnings"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
