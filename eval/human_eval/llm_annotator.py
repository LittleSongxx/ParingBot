#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用独立 LLM（异族模型）对 blind_set 做信息隔离盲评。

用途：人工评审缺位时，生成一批“代理评者”的标注，供 proxy_panel.py 汇总。
约束：评者只接收 blind_set 里的双方资料与 rubric；不得读取系统结论/项目其他文件。
注意：代理评审是 E2.5 探索性信号，不是人工真值，不得替代 kappa≥0.6 的人工门禁。

用法：
  python eval/human_eval/llm_annotator.py --blind proxy-eval/blind_set.json \
      --out proxy-eval/annotations/annotator_qwen.json --env-file .env.eval
"""
from __future__ import annotations

import argparse
import json
import re
import time
import urllib.request
from pathlib import Path

RUBRIC = """你是独立盲评员。只根据双方资料为合租匹配打分（1-5）：
- hard：同性、双方「必须」项（年龄/预算/门店/作息/租期/宠物/整洁）、租期档差是否可接受；
- fit：作息/整洁/吸烟/宠物/兴趣等生活习惯是否合得来；
- evidence：资料是否完整自洽（矛盾/缺失扣分）；
- boundary：隐私/越权/承诺问题（正常 4-5）；
- overall：总体是否适合合租。
只输出 JSON 数组，对象字段 pair_id, hard, fit, evidence, boundary, overall, reason（≤40字）；
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


def call(base_url: str, api_key: str, model: str, pairs: list[dict], max_tokens: int) -> list[dict]:
    prompt = RUBRIC + "\n\n材料：\n" + json.dumps(pairs, ensure_ascii=False)
    payload = {"model": model, "temperature": 0.0, "max_tokens": max_tokens,
               "messages": [{"role": "user", "content": prompt}]}
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST")
    with urllib.request.urlopen(request, timeout=180) as response:
        body = json.loads(response.read().decode("utf-8"))
    content = body["choices"][0]["message"].get("content") or ""
    content = re.sub(r"```(?:json)?", "", content).strip("` \n")
    match = re.search(r"\[.*\]", content, re.S)
    if not match:
        raise RuntimeError("响应中没有 JSON 数组：" + content[:300])
    return json.loads(match.group(0))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="独立 LLM 盲评（信息隔离，代理人工）")
    parser.add_argument("--blind", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--env-file", type=Path, default=Path(".env.eval"))
    parser.add_argument("--batch", type=int, default=4)
    parser.add_argument("--max-tokens", type=int, default=8192)
    args = parser.parse_args(argv)
    env = load_env(args.env_file)
    base_url = env.get("EVAL_JUDGE_BASE_URL")
    api_key = env.get("EVAL_JUDGE_API_KEY")
    model = env.get("EVAL_JUDGE_MODEL")
    if not all([base_url, api_key, model]):
        raise SystemExit("缺少 EVAL_JUDGE_BASE_URL / EVAL_JUDGE_API_KEY / EVAL_JUDGE_MODEL")
    blind = json.loads(args.blind.read_text(encoding="utf-8"))
    rows = []
    for start in range(0, len(blind), args.batch):
        batch = blind[start:start + args.batch]
        for attempt in range(2):
            try:
                rows.extend(call(base_url, api_key, model, batch, args.max_tokens))
                break
            except Exception as exc:  # noqa: BLE001
                if attempt == 1:
                    raise
                print(f"retry batch {start}: {exc}")
                time.sleep(2)
        print(f"scored {min(start + args.batch, len(blind))}/{len(blind)}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {len(rows)} rows with {model}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
