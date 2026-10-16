#!/usr/bin/env python3
"""support-eval：客服线评测（mewhelp 式五指标记分卡，quality-v2 客服线的继任）。

五个指标（全部面试标准词汇，每个一句话说得清）：
  1. Recall@5     确定性。该题金标文档进入最后一次真实检索前 5 的比例（多金标部分分）。
  2. MRR          确定性。金标文档排名倒数的平均（多金标先平均；缺席记 0）。
  3. Relevancy   judge+embedding。反向问题生成与原问题的相似度均值（RAGAS answer_relevancy 同构）。
  4. Faithfulness judge。答案事实主张全部有证据支撑的比例（二值）。
  5. 库外诚实率   确定性。L6 库外桶：answer_status ∈ {insufficient, needs_human} 即诚实拒答。

纪律：judge 调用失败记 None 并从该指标分母剔除——「没评上」不是「零分」。
报告：分层 × 指标矩阵 + 总体 + 逐题 CSV + 该拒没拒/不忠实个案（带证据与理由）。

用法：
  collect（需活栈，venv python）:
    assistant/.venv/bin/python scripts/eval_support_eval.py collect --output artifacts/support-eval/<日期>-r1
  score（需 judge 密钥，系统 python3，无第三方新依赖之外的要求）:
    python3 scripts/eval_support_eval.py score --input artifacts/support-eval/<日期>-r1[,<日期>-r2,...]
  官方数字 = 双跑均值：两次独立 collect（-r1/-r2）后 score 传两目录，逐题取均值再聚合
  （judge 指标单试验 ±2–4pt 方差，双跑把读数稳定在带内；scorecard 注明 n=R×题）。
"""
import argparse
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from runtime import ROOT, model_env  # noqa: E402

CORPUS_DIR = ROOT / 'evals/support-eval/corpus'
QUESTIONS = ROOT / 'evals/support-eval/questions.jsonl'
ARTIFACT = ROOT / 'artifacts/support-eval'
LAYERS = ('L1', 'L2', 'L3', 'L4', 'L5', 'L6_absent')
LAYER_LABEL = {'L1': '单跳事实', 'L2': '条件判断', 'L3': '数值清单', 'L4': '跨文档',
               'L5': '边界干扰', 'L6_absent': '库外拒答'}
RECALL_K = 5
HONEST_REFUSE_STATUS = {'insufficient', 'needs_human'}
HONEST_MARKERS = ('未提及', '未查询到', '没有找到', '未找到', '未包含', '未发布', '无法确认',
                  '未明确说明', '未明确提及', '没有明确说明')

COVERAGE_SYS = """你是答案覆盖度评审员。给定用户问题、标准答案要点清单、客服答案。
对每一条要点单独判定：该要点信息在客服答案中有正确体现记 true，遗漏、答错或仅在答案中部分体现该要点时记 false。
改述算体现，但一条要点含多个事实时必须全部体现才记 true。
返回 JSON：{"verdicts": [true/false, ...]（长度必须等于要点总数）, "reason": 一句话依据}。"""

FAITH_SYS = """你是回答忠实度评审员。给定检索证据和客服回答，判断回答里的具体事实主张
（政策规则、金额、时限、条件等）是否都能被证据支撑。忠实度只查「资料里没有、模型自己编」的杜撰，
合理改述算支撑。返回 JSON：{"faithful": true/false, "reason": 一句话依据}。"""


RELEVANCY_GEN_SYS = """你是问题反向生成器（RAGAS answer_relevancy 同构）。给定一段客服回答，
生成 3 个该回答最能回应的用户问题：每个问题一句、独立完整、贴合回答实际内容，
不要编号或前缀。返回 JSON：{"questions": ["问题1", "问题2", "问题3"]}。"""


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def now():
    return datetime.now(timezone.utc).isoformat()


def corpus():
    return {path.stem: path.read_text() for path in sorted(CORPUS_DIR.glob('*.md'))}


def questions():
    return [json.loads(line) for line in QUESTIONS.read_text().splitlines() if line.strip()]


# ---------- collect：活栈采集（与旧 support-ragas 同链路） ----------
def assistant_up():
    try:
        import httpx
        from runtime import ENV_FILE, parse_env
        port = parse_env(ENV_FILE)['SMARTLECT_ASSISTANT_PORT']
        with httpx.Client(timeout=2, trust_env=False) as client:
            return client.get('http://127.0.0.1:' + port + '/health').status_code == 200
    except Exception:
        return False


def last_search_candidates(observation):
    from quality_v2 import last_real_search
    search = last_real_search(observation.get('tool_calls') or [])
    ranked = []
    for row in (search or {}).get('candidates') or []:
        doc_id = row.get('doc_id') if isinstance(row, dict) else row
        if doc_id and doc_id not in ranked:
            ranked.append(doc_id)
    return ranked


def load_corpus_documents(docs):
    return [{
        'doc_id': doc_id, 'version': 1, 'title': body.splitlines()[0].lstrip('# '),
        'source_uri': 'evals/support-eval/corpus/' + doc_id + '.md', 'body': body,
        'acl': 'PUBLIC', 'lifecycle': 'publish_before_question',
        'checksum_sha256': sha256(body.encode()).hexdigest()}
        for doc_id, body in sorted(docs.items())]


def cmd_collect(args):
    if not assistant_up():
        raise SystemExit('assistant_not_healthy; start the isolated stack first (scripts/dev.sh up)')
    from eval_support import setup_knowledge
    from eval_quality_v2 import collect_tools
    from scenario_client import ScenarioClient
    docs = corpus()
    rag_case = {'knowledge_setup': {'additional_documents': load_corpus_documents(docs)}}
    empty_manifest = {'base_corpus': {'documents': []}}
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    rows = questions()
    if args.case:
        wanted = {item.strip() for chunk in args.case for item in chunk.split(',')}
        rows = [row for row in rows if row['id'] in wanted]
    (output / 'collect-meta.json').write_text(json.dumps(
        {'schema_version': 'support-eval-collect-v1', 'collected_at': now(),
         'question_count': len(rows),
         'corpus_sha256': {doc_id: sha256(body.encode()).hexdigest()
                           for doc_id, body in sorted(docs.items())}}, ensure_ascii=False, indent=2))
    for index, row in enumerate(rows, start=1):
        path = output / (row['id'] + '.json')
        evidence = {'id': row['id'], 'layer': row['layer'], 'status': 'SETUP_RUNNING',
                    'line': 'support', 'scenario': 'support-eval', 'seed': 42, 'documents': [],
                    'run_id': 'se-' + uuid.uuid4().hex, 'question': row['question'],
                    'gold_docs': row['gold_docs'], 'points': row['points']}
        save = lambda: path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, default=str) + '\n')
        save()
        client = None
        try:
            client = ScenarioClient(evidence, save, requested_mode='live')
            client.setup(actor_ref='user_a')
            setup_knowledge(client, evidence, save, empty_manifest, rag_case)
            conversation = client.conversation()
            reply = client.message(conversation, row['question'], label=row['question'][:40])
            evidence['answer'] = str((reply or {}).get('answer') or '')
            evidence['answer_status'] = (reply or {}).get('answer_status')
            run_id = client.evidence['model_runs'][-1]['agent_run_id']
            tool_rows = collect_tools(client, run_id)
            evidence['tool_names'] = [row['tool_name'] for row in tool_rows]
            evidence['tool_receipts'] = [
                {'tool_name': row['tool_name'], 'receipt': str(row.get('receipt_json') or '')[:600]}
                for row in tool_rows if row['tool_name'] != 'search_knowledge']
            evidence['retrieved_doc_ids'] = last_search_candidates({'tool_calls': tool_rows}) or None
            evidence['status'] = 'COLLECTED'
        except Exception as error:
            evidence['status'] = 'FAILED'
            evidence['error'] = type(error).__name__
            evidence['error_text'] = str(error)[:500]
        finally:
            if client is not None:
                client.close()
            evidence['finished_at'] = now()
            save()
        print('%d/%d %s %s' % (index, len(rows), row['id'], evidence['status']))
    print(json.dumps({'collected_to': str(output)}, ensure_ascii=False))


# ---------- score：确定性三指标 + judge 两指标 ----------
def judge_call(client, model, system, user, timeout_note):
    """温度 0 的 JSON 判分；失败重试一次，仍失败返回 None（不落零分）。"""
    for attempt in (1, 2):
        try:
            response = client.chat.completions.create(
                model=model, temperature=0, response_format={'type': 'json_object'},
                messages=[{'role': 'system', 'content': system}, {'role': 'user', 'content': user}],
                timeout=60)
            return json.loads(response.choices[0].message.content)
        except Exception as error:
            if attempt == 2:
                print('  judge_miss %s: %s' % (timeout_note, type(error).__name__))
                return None
            time.sleep(2)


def recall_at_5(gold, retrieved):
    if not gold:
        return None
    top = retrieved[:RECALL_K]
    return sum(1 for doc in gold if doc in top) / len(gold)


def mrr(gold, retrieved):
    if not gold:
        return None
    total = 0.0
    for doc in gold:
        total += 1.0 / (retrieved.index(doc) + 1) if doc in retrieved else 0.0
    return total / len(gold)


def cmd_score(input_dirs):
    env = model_env()
    if not env.get('SMARTLECT_JUDGE_API_KEY'):
        raise SystemExit('missing judge keys in run/model.env')
    from openai import OpenAI
    judge = OpenAI(api_key=env['SMARTLECT_JUDGE_API_KEY'],
                   base_url=env['SMARTLECT_JUDGE_BASE_URL'])
    model = env['SMARTLECT_JUDGE_MODEL']
    embedder = OpenAI(api_key=env['SMARTLECT_EMBEDDING_API_KEY'],
                      base_url=env['SMARTLECT_EMBEDDING_BASE_URL'])
    embedding_model = env['SMARTLECT_EMBEDDING_MODEL']
    docs = corpus()
    question_rows = {row['id']: row for row in questions()}
    repeats = []
    for repeat_index, input_dir in enumerate(input_dirs, start=1):
        skipped = []
        for path in sorted(input_dir.glob('*.json')):
            if path.name in ('collect-meta.json', 'scorecard.json'):
                continue
            row = json.loads(path.read_text())
            if not isinstance(row, dict) or 'question' not in row:
                continue
            if row.get('status') != 'COLLECTED':
                skipped.append((row.get('id'), row.get('status')))
                continue
            entry = score_one_sample(row, question_rows, docs, judge, model,
                                     embedder, embedding_model)
            entry['repeat'] = repeat_index
            entry['source_dir'] = input_dir.name
            repeats.append(entry)
        if skipped:
            print('repeat %d skipped_not_collected: %s' % (
                repeat_index, json.dumps(skipped, ensure_ascii=False)))
    if not repeats:
        raise SystemExit('no_collected_samples')
    # Judge metrics swing ±2–4pt per single collect; official numbers average every
    # question over independent repeats first, then aggregate layers (n=R×N).
    by_question = {}
    for entry in repeats:
        by_question.setdefault(entry['id'], []).append(entry)
    results = []
    for qid, entries in sorted(by_question.items()):
        aggregated = {key: entries[0].get(key) for key in (
            'id', 'layer', 'question', 'answer_head')}
        aggregated['repeat_n'] = len(entries)
        for key in ('recall@5', 'mrr', 'relevancy', 'faithful', 'refused'):
            aggregated[key] = mean([e.get(key) for e in entries])
        aggregated['faith_reason'] = next(
            (e['faith_reason'] for e in entries if e.get('faith_reason')), None)
        results.append(aggregated)
    write_scorecard(results, input_dirs[0], model, repeats=repeats)


def score_one_sample(row, question_rows, docs, judge, model, embedder=None, embedding_model=None):
    retrieved = row.get('retrieved_doc_ids') or []
    gold = row.get('gold_docs') or []
    layer = (question_rows.get(row['id']) or {}).get('layer') or row['layer']
    entry = {'id': row['id'], 'layer': layer, 'question': row['question'],
             'recall@5': recall_at_5(gold, retrieved),
             'mrr': mrr(gold, retrieved),
             'relevancy': None, 'faithful': None, 'refused': None,
             'answer_head': (row.get('answer') or '')[:80]}
    hedged = None
    if layer == 'L6_absent':
        answer = row.get('answer') or ''
        hedged = (row.get('answer_status') in HONEST_REFUSE_STATUS
                  or any(marker in answer for marker in HONEST_MARKERS))
    else:
        # Answer relevancy, RAGAS answer_relevancy-isomorphic: reverse-generate
        # questions from the answer, then average cosine similarity between each
        # generated question and the user's question. Reference-free; the L6
        # absent bucket stays out of this denominator (a refusal does not
        # "answer" the question by construction).
        answer = row.get('answer') or ''
        if answer.strip():
            verdict = judge_call(judge, model, RELEVANCY_GEN_SYS,
                                 '客服回答:\n%s' % answer, 'rel:' + row['id'])
            generated = (verdict or {}).get('questions')
            if isinstance(generated, list):
                generated = [str(q).strip() for q in generated if str(q).strip()][:4]
                if generated and embedder is not None:
                    try:
                        vectors = embedder.embeddings.create(
                            model=embedding_model, input=[row['question']] + generated)
                        origin = vectors.data[0].embedding
                        # Max over reverse-generated questions: the answer is relevant
                        # if it thoroughly addresses what the user asked; averaging
                        # punishes answers whose phrasing spawns diverse questions
                        # under text-embedding-v4's compressed cosine scale.
                        entry['relevancy'] = max(
                            cosine(origin, item.embedding) for item in vectors.data[1:])
                    except Exception as error:
                        print('  embed_miss %s: %s' % (row['id'], type(error).__name__))
    # Faithfulness 对全部层判（L6 的编造同样要露头）；证据面=用户问题+检索文档+工具观测
    evidence_text = '用户问题:' + row['question'] + '\n检索证据:\n' + '\n'.join(
        '[%d] %s' % (i + 1, docs[doc_id])
        for i, doc_id in enumerate(retrieved) if doc_id in docs)
    for receipt in row.get('tool_receipts') or []:
        evidence_text += '\n[工具观测] %s -> %s' % (receipt.get('tool_name'), receipt.get('receipt') or '(空)')
    verdict = judge_call(judge, model, FAITH_SYS,
                         '检索证据:\n%s\n\n客服回答:\n%s' % (
                             evidence_text or '(本轮无检索证据)',
                             row.get('answer') or '(空)'),
                         'faith:' + row['id'])
    if verdict is not None and isinstance(verdict.get('faithful'), bool):
        entry['faithful'] = 1 if verdict['faithful'] else 0
        if not verdict['faithful']:
            entry['faith_reason'] = str(verdict.get('reason') or '')[:120]
    if layer == 'L6_absent':
        # 诚实 = 声明了未命中/不足收口 ∧ 没有编造（judge 失败时退回声明面，不因没评上落零）
        entry['refused'] = 1 if hedged and entry['faithful'] != 0 else 0
    return entry


def mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def fmt(value):
    return '未评上' if value is None else '%.4f' % value


def write_scorecard(results, input_dir, judge_model, repeats=None):
    repeat_n = max((r['repeat_n'] for r in results), default=1)
    repeat_note = '' if repeat_n <= 1 else '（n=%d×题，官方双跑逐题均值）' % repeat_n
    lines = ['# support-eval 记分卡', '',
             'judge=%s（温度 0，与主对话模型异源）| Relevancy=反向问题生成+embedding 相似度（RAGAS answer_relevancy 同构）'
             '| 检索面确定性计算 | 语料 %d 篇含干扰 | 分母随指标并排%s' % (
                 judge_model, len(corpus()), repeat_note), '',
             '| 层 | n | Recall@5 | MRR | Relevancy | Faithfulness | 库外诚实率 |', '|---|---|---|---|---|---|---|']
    for layer in LAYERS:
        rows = [r for r in results if r['layer'] == layer]
        if not rows:
            continue
        metrics = [mean([r['recall@5'] for r in rows]), mean([r['mrr'] for r in rows]),
                   mean([r['relevancy'] for r in rows]), mean([r['faithful'] for r in rows]),
                   mean([r['refused'] for r in rows])]
        lines.append('| %s | %d | %s | %s | %s | %s | %s |' % (
            LAYER_LABEL[layer], len(rows), *(fmt(v) for v in metrics)))
    metrics = [mean([r[k] for r in results]) for k in ('recall@5', 'mrr', 'relevancy', 'faithful')]
    refused = mean([r['refused'] for r in results if r['layer'] == 'L6_absent'])
    lines.append('| **总体** | %d | %s | %s | %s | %s | %s |' % (
        len(results), *(fmt(v) for v in metrics), fmt(refused)))
    miss_refusals = [r for r in results if r['layer'] == 'L6_absent' and r['refused'] == 0]
    if miss_refusals:
        lines += ['', '## 库外不诚实（%d 例）' % len(miss_refusals), '']
        for r in miss_refusals:
            lines.append('- %s「%s」答案开头：%s' % (r['id'], r.get('question', ''), r['answer_head']))
    low_relevancy = [r for r in results if r['relevancy'] is not None and r['relevancy'] < 0.6]
    if low_relevancy:
        lines += ['', '## 低相关性个案（Relevancy<0.6，%d 例）' % len(low_relevancy), '']
        for r in sorted(low_relevancy, key=lambda item: item['relevancy']):
            lines.append('- %s（%s）%.3f「%s」答案开头：%s' % (
                r['id'], LAYER_LABEL.get(r['layer'], r['layer']), r['relevancy'],
                r.get('question', '')[:30], r['answer_head']))
    unfaithful = [r for r in results if r['faithful'] == 0]
    if unfaithful:
        lines += ['', '## 不忠实个案（%d 例）' % len(unfaithful), '']
        for r in unfaithful:
            lines.append('- %s（%s）：%s' % (r['id'], LAYER_LABEL.get(r['layer'], r['layer']),
                                            r.get('faith_reason', '')))
    report = '\n'.join(lines) + '\n'
    (input_dir / 'scorecard.md').write_text(report)
    (input_dir / 'scorecard.json').write_text(json.dumps(
        {'generated_at': now(), 'judge_model': judge_model,
         'repeats': len({r['repeat'] for r in repeats}) if repeats else 1,
         'results': results, 'per_repeat': repeats or None},
        ensure_ascii=False, indent=2))
    import csv
    fieldnames = ['id', 'layer', 'recall@5', 'mrr', 'relevancy', 'faithful', 'refused',
                  'repeat_n', 'answer_head']
    with (input_dir / 'per-question.csv').open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(results)
    if repeats:
        detail_fields = ['id', 'layer', 'repeat', 'source_dir', 'recall@5', 'mrr',
                         'relevancy', 'faithful', 'refused', 'answer_head']
        with (input_dir / 'per-repeat.csv').open('w', newline='', encoding='utf-8') as handle:
            writer = csv.DictWriter(handle, fieldnames=detail_fields, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(repeats)
    print(report)


def main():
    parser = argparse.ArgumentParser(description='support-eval runner（五指标记分卡）')
    parser.add_argument('command', choices=('collect', 'score'))
    parser.add_argument('--output', default=None)
    parser.add_argument('--input', default=None)
    parser.add_argument('--case', action='append', default=[])
    args = parser.parse_args()
    if args.command == 'collect':
        cmd_collect(args)
        return
    input_spec = args.input or ''
    input_dirs = [Path(item.strip()) for item in input_spec.split(',') if item.strip()]
    if not input_dirs or not all(path.exists() for path in input_dirs):
        raise SystemExit('missing_input; score needs --input <collect dir>[,<dir2>...]')
    cmd_score(input_dirs)


if __name__ == '__main__':
    main()
