"""quality-v2 runner. Development only until holdout is frozen. No composite score."""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import sys
import time
import traceback
import uuid

from quality_v2 import (CONTRACT_JSON, FREEZE_MANIFEST, HOLDOUT_DIR, SHOPPING_CATALOG, SHOPPING_DEV, SUPPORT_DEV,
                        AnnotationError, append_rerun_ledger, catalog_overlay_plan, digest,
                        live_support_cases, load_json, load_jsonl, observation_from_agent, provenance,
                        refuse_holdout, score_shopping, score_support, self_check_scores,
                        validate_dev_sets, write_report)
from judge_quality_v2 import run_calibration, run_llm_judge, write_human_review
from runtime import ENV_FILE, ROOT, parse_env

ARTIFACT = ROOT / 'artifacts/quality-v2'


def now():
    return datetime.now(timezone.utc).isoformat()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + '\n')


def selected_cases(rows, wanted):
    if not wanted:
        return list(rows)
    keys = {item.strip() for chunk in wanted for item in chunk.split(',') if item.strip()}
    return [row for row in rows if row.get('case_id') in keys]


def growth_up():
    try:
        import httpx
        from runtime import ENV_FILE, parse_env
        port = parse_env(ENV_FILE)['SMARTLECT_ASSISTANT_PORT']
        with httpx.Client(timeout=2, trust_env=False) as client:
            return client.get('http://127.0.0.1:' + port + '/health').status_code == 200
    except Exception:
        return False


def collect_tools(client, agent_run_id):
    return client.rows('SELECT call_id,tool_name,arguments_json,outcome,receipt_json FROM tool_call '
                       'WHERE agent_run_id=%s ORDER BY started_at,call_id', (agent_run_id,))


def business_closeout_after_budget(record):
    """A completed rule-fallback closeout is a scored system outcome, not a channel fault.

    The model spent its own call budget; the controller then compiled a business
    closeout (legal empty / visible citations), possibly waiting on the user.
    Provider faults keep handoff_origin 'provider_fault' and stay setup_failed."""
    run = (record or {}).get('run') or {}
    result = run.get('result') or {}
    return (run.get('state') in {'COMPLETED', 'WAIT_USER'}
            and result.get('model_mode') == 'rule-fallback'
            and result.get('handoff_origin') != 'provider_fault')


def handoff_ends_conversation(previous_result, remaining_turns):
    """An open ticket puts the conversation under human control: further user
    turns are business-rejected (409 human_control_active), not an infra fault.
    True when a completed turn left a ticket and later turns remain unasked."""
    return bool(remaining_turns) and bool((previous_result or {}).get('ticket'))


def run_turns(client, texts):
    conversation = client.conversation()
    last = None
    tools = []
    for index, text in enumerate(texts):
        if index and handoff_ends_conversation(last, len(texts) - index):
            client.evidence['handoff_ended_conversation'] = {
                'after_turns': index, 'unasked': len(texts) - index}
            client.save()
            break
        try:
            last = client.message(conversation, text, label=text[:40])
        except AssertionError as error:
            if 'Run retains its actual requested model mode' not in str(error):
                raise
            record = client.evidence['model_runs'][-1]
            if not business_closeout_after_budget(record):
                raise
            last = (record.get('run') or {}).get('result')
        run_id = client.evidence['model_runs'][-1]['agent_run_id']
        tools.extend(collect_tools(client, run_id))
    result = (last or {})
    context = client.evidence['model_runs'][-1].get('run', {}).get('context') or {}
    failed = context.get('closeout') in {'provider_fault', 'budget_exceeded'} or result.get('handoff_origin') == 'provider_fault'
    return result, tools, failed


def commerce_mysql(config):
    import pymysql
    return pymysql.connect(host=config['SMARTLECT_MYSQL_HOST'], port=int(config['SMARTLECT_MYSQL_PORT']),
                           user=config['SMARTLECT_MYSQL_USER'], password=config['SMARTLECT_MYSQL_PASSWORD'],
                           database='smartlect_product', charset='utf8mb4',
                           cursorclass=pymysql.cursors.DictCursor, autocommit=False,
                           connect_timeout=5, read_timeout=10, write_timeout=10)


def snapshot_overlay_priors(connection, plan):
    """Capture every row the overlay will touch so it can be restored afterwards."""
    priors = {'products': [], 'specs': [], 'skus': []}
    with connection.cursor() as cursor:
        for row in plan['products']:
            cursor.execute("SELECT product_name,product_desc,category_id,p_category_id,status,min_price,max_price "
                           "FROM product_info WHERE product_id=%s", (row['product_id'],))
            current = cursor.fetchone()
            if current is None:
                raise ValueError('overlay_product_missing:' + row['product_id'])
            priors['products'].append({'product_id': row['product_id'], **current})
            cursor.execute("SELECT property_value FROM product_property_value "
                           "WHERE product_id=%s AND property_value_id=%s",
                           (row['product_id'], row['primary_value_id']))
            spec = cursor.fetchone()
            if spec is None:
                raise ValueError('overlay_spec_missing:' + row['product_id'])
            priors['specs'].append({'product_id': row['product_id'], 'property_value_id': row['primary_value_id'],
                                    'property_value': spec['property_value']})
            cursor.execute("SELECT price FROM product_sku WHERE product_id=%s AND property_value_id_hash=%s",
                           (row['product_id'], row['primary_hash']))
            sku = cursor.fetchone()
            if sku is None:
                raise ValueError('overlay_sku_missing:' + row['gold_sku_key'])
            priors['skus'].append({'product_id': row['product_id'], 'property_value_id_hash': row['primary_hash'],
                                   'price': sku['price']})
    return priors


def restore_overlay(client, plan, priors, stock_priors, inserted_categories):
    """Reverse the overlay: products, specs, sku prices, stocks and freshly inserted categories."""
    def run(evidence):
        status = {'status': 'restored', 'error': None}
        try:
            config = parse_env(ENV_FILE)
            connection = commerce_mysql(config)
            try:
                with connection.cursor() as cursor:
                    for row in priors['products']:
                        cursor.execute("UPDATE product_info SET product_name=%s,product_desc=%s,category_id=%s,"
                                       "p_category_id=%s,status=%s,min_price=%s,max_price=%s WHERE product_id=%s",
                                       (row['product_name'], row['product_desc'], row['category_id'],
                                        row['p_category_id'], row['status'], row['min_price'], row['max_price'],
                                        row['product_id']))
                    for row in priors['specs']:
                        cursor.execute("UPDATE product_property_value SET property_value=%s "
                                       "WHERE product_id=%s AND property_value_id=%s",
                                       (row['property_value'], row['product_id'], row['property_value_id']))
                    for row in priors['skus']:
                        cursor.execute("UPDATE product_sku SET price=%s WHERE product_id=%s AND property_value_id_hash=%s",
                                       (row['price'], row['product_id'], row['property_value_id_hash']))
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()
            for row, stock in zip(plan['products'], stock_priors['primary']):
                client.java.request('stock', '/internal/stock/set',
                                    data={'productId': row['product_id'], 'propertyValueIdHash': row['primary_hash'],
                                          'stock': stock})
            for row, stock in zip(plan['products'], stock_priors['extras']):
                for digest, value in stock:
                    client.java.request('stock', '/internal/stock/set',
                                        data={'productId': row['product_id'], 'propertyValueIdHash': digest,
                                              'stock': value})
            if inserted_categories:
                config = parse_env(ENV_FILE)
                connection = commerce_mysql(config)
                try:
                    with connection.cursor() as cursor:
                        for category in inserted_categories:
                            cursor.execute("DELETE FROM sys_category WHERE category_id=%s", (category,))
                    connection.commit()
                except Exception:
                    connection.rollback()
                finally:
                    connection.close()
        except Exception as error:  # restore is best effort but loudly recorded
            status = {'status': 'restore_failed', 'error': type(error).__name__ + ':' + str(error)[:200]}
        evidence.setdefault('catalog_overlay', {})['restore'] = status
        return status
    return run


def apply_shopping_catalog(client, evidence):
    catalog = load_json(SHOPPING_CATALOG)
    plan = catalog_overlay_plan(client.manifest, catalog)
    evidence['catalog_overlay'] = {'snapshot_id': catalog['snapshot_id'], 'plan': plan}
    config = parse_env(ENV_FILE)
    connection = commerce_mysql(config)
    priors = snapshot_overlay_priors(connection, plan)
    stock_priors = {'primary': [], 'extras': []}
    stock_query = ([{'productId': row['product_id'], 'propertyValueIdHash': row['primary_hash']}
                    for row in plan['products']]
                   + [{'productId': row['product_id'], 'propertyValueIdHash': digest}
                      for row in plan['products'] for digest in row['extra_hashes']])
    stock_rows = client.java.request('stock', '/internal/stock/getBatch', data=stock_query) if stock_query else []
    stock_map = {(row['productId'], row['propertyValueIdHash']): row.get('stock') for row in stock_rows}
    inserted_categories = []
    try:
        with connection.cursor() as cursor:
            for index, category in enumerate(plan['categories']):
                cursor.execute("INSERT INTO sys_category (category_id,category_name,p_category_id,sort) "
                               "VALUES (%s,%s,'0',%s) ON DUPLICATE KEY UPDATE category_id=category_id",
                               (category, category, 20 + index))
                if cursor.rowcount == 1:
                    inserted_categories.append(category)
            for row in plan['products']:
                price = Decimal(row['price_cents']).scaleb(-2)
                cursor.execute("UPDATE product_info SET product_name=%s,product_desc=%s,category_id=%s,"
                               "p_category_id='0',status=%s,min_price=%s,max_price=%s WHERE product_id=%s",
                               (row['productName'], row['productName'], row['live_category_id'],
                                row['status'], price, price, row['product_id']))
                if cursor.rowcount != 1:
                    raise ValueError('overlay_product_missing:' + row['product_id'])
                cursor.execute("UPDATE product_property_value SET property_value=%s "
                               "WHERE product_id=%s AND property_value_id=%s",
                               (row['specification'], row['product_id'], row['primary_value_id']))
                if cursor.rowcount != 1:
                    raise ValueError('overlay_spec_missing:' + row['product_id'])
                cursor.execute("UPDATE product_sku SET price=%s WHERE product_id=%s AND property_value_id_hash=%s",
                               (price, row['product_id'], row['primary_hash']))
                if cursor.rowcount != 1:
                    raise ValueError('overlay_sku_missing:' + row['gold_sku_key'])
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    restore = restore_overlay(client, plan, priors, stock_priors, inserted_categories)
    for row in plan['products']:
        stock_priors['primary'].append(stock_map.get((row['product_id'], row['primary_hash']), 0))
        stock_priors['extras'].append([(digest, stock_map.get((row['product_id'], digest), 0))
                                       for digest in row['extra_hashes']])
    try:
        for row in plan['products']:
            client.java.request('stock', '/internal/stock/set',
                                data={'productId': row['product_id'], 'propertyValueIdHash': row['primary_hash'],
                                      'stock': row['stock']})
            for extra in row['extra_hashes']:
                client.java.request('stock', '/internal/stock/set',
                                    data={'productId': row['product_id'], 'propertyValueIdHash': extra, 'stock': 0})
        client.catalog = client.java.request('product', '/internal/product/snapshotBatch',
                                             data={'productIds': client.manifest['products']})
        products = {row['productId']: row for row in client.catalog.get('products', [])}
        skus = {(row['productId'], row['propertyValueIdHash']): row for row in client.catalog.get('skus', [])}
        values = {(row['productId'], row['propertyValueId']): row
                  for row in client.catalog.get('propertyValues', [])}
        mapped = {}
        for row in plan['products']:
            product = products.get(row['product_id'])
            sku = skus.get((row['product_id'], row['primary_hash']))
            spec = values.get((row['product_id'], row['primary_value_id']))
            if (not product or product.get('productName') != row['productName']
                    or product.get('status') != row['status']
                    or product.get('categoryId') != row['live_category_id']
                    or not sku or Decimal(str(sku.get('price'))) != Decimal(row['price_cents']).scaleb(-2)
                    or not spec or spec.get('propertyValue') != row['specification']):
                raise ValueError('overlay_snapshot_mismatch:' + row['gold_sku_key'])
            mapped[row['gold_sku_key']] = row['product_id'] + ':' + row['primary_hash']
    except Exception:
        restore(evidence)  # commit already landed; undo before propagating
        raise
    evidence['catalog_overlay']['live_sku_keys'] = mapped
    evidence['catalogue'] = client.catalog
    return restore


def run_shopping_live(output, wanted=None, split='development', trials=1):
    from scenario_client import ScenarioClient
    from quality_v2 import dataset_paths
    catalog = load_json(SHOPPING_CATALOG)
    rows = []
    for case in selected_cases(load_jsonl(dataset_paths(split)['shopping']), wanted):
        for trial in range(1, trials + 1):
            evidence = {'case_id': case['case_id'], 'line': 'shopping', 'status': 'SETUP_RUNNING',
                        'run_id': 'qv2-shop-' + uuid.uuid4().hex, 'scenario': 'quality-v2-shopping', 'seed': 42}
            if trials > 1:
                evidence['trial'] = trial
            path = output / 'shopping' / (case['case_id'] + ('.t%d' % trial if trials > 1 else '') + '.json')
            save = lambda: write(path, evidence)
            save()
            client = None
            try:
                client = ScenarioClient(evidence, save, requested_mode='live')
                client.setup(actor_ref='user_a', product_count=len(catalog['skus']))
                restore = apply_shopping_catalog(client, evidence)
                try:
                    result, tools, channel_failed = run_turns(client, case['user_turns'])
                    observation = observation_from_agent(result, tools, model_channel_failed=channel_failed,
                                                         gold_mode='snapshot',
                                                         setup_failed=channel_failed, setup_reason='provider_or_budget' if channel_failed else None)
                    evidence['observation'] = observation
                    evidence['scores'] = score_shopping(case, observation)
                    evidence['status'] = 'SCORED'
                finally:
                    restore(evidence)
            except AnnotationError:
                raise
            except Exception as error:
                evidence['status'] = 'SETUP_FAILED'
                evidence['error'] = type(error).__name__
                evidence['error_text'] = str(error)[:500]
                evidence['scores'] = score_shopping(case, {'setup_failed': True, 'setup_reason': type(error).__name__})
            finally:
                if client is not None:
                    client.close()
                if trials > 1 and evidence.get('scores') is not None:
                    evidence['scores']['trial'] = trial
                evidence['finished_at'] = now()
                save()
            rows.append(evidence['scores'])
    return rows


def run_support_live(output, wanted=None, split='development', trials=1):
    from eval_support import setup_knowledge
    from scenario_client import ScenarioClient
    from judge_quality_v2 import (apply_judge_answer_side, apply_judge_faithfulness,
                                  judge_config)
    from quality_v2 import dataset_paths
    cases = live_support_cases(load_jsonl(dataset_paths(split)['support']))
    rows = []
    judge_targets = []  # {'case','result','row','path'}: one entry per scored trial
    for case in selected_cases(cases, wanted):
        for trial in range(1, trials + 1):
            evidence = {'case_id': case['case_id'], 'line': 'support', 'status': 'SETUP_RUNNING',
                        'run_id': 'qv2-sup-' + uuid.uuid4().hex, 'scenario': 'quality-v2-support', 'seed': 42, 'documents': []}
            if trials > 1:
                evidence['trial'] = trial
            path = output / 'support' / (case['case_id'] + ('.t%d' % trial if trials > 1 else '') + '.json')
            save = lambda: write(path, evidence)
            save()
            client = None
            try:
                client = ScenarioClient(evidence, save, requested_mode='live')
                client.setup(actor_ref=case.get('actor') or 'user_a')
                setup = case.get('knowledge_setup') or {}
                rag_case = {'knowledge_setup': {'additional_documents': []}}
                for doc_id in case.get('visible_doc_ids') or []:
                    body = (ROOT / 'fixtures/knowledge' / (doc_id + '.md')).read_text()
                    rag_case['knowledge_setup']['additional_documents'].append({
                        'doc_id': doc_id, 'version': 1, 'title': body.splitlines()[0].lstrip('# '),
                        'source_uri': 'fixtures/knowledge/' + doc_id + '.md', 'body': body, 'acl': 'PUBLIC',
                        'lifecycle': 'publish_before_question',
                        'checksum_sha256': __import__('hashlib').sha256(body.encode()).hexdigest()})
                for extra in setup.get('additional_documents') or []:
                    rag_case['knowledge_setup']['additional_documents'].append(extra)
                for extra in setup.get('documents') or []:
                    body = (ROOT / extra['source_uri']).read_text()
                    rag_case['knowledge_setup']['additional_documents'].append({
                        **extra, 'body': extra.get('body') or body,
                        'title': extra.get('title') or body.splitlines()[0].lstrip('# '),
                        'acl': extra.get('acl') or 'PUBLIC',
                        'checksum_sha256': extra.get('checksum_sha256') or __import__('hashlib').sha256(body.encode()).hexdigest()})
                empty_manifest = {'base_corpus': {'documents': []}}
                setup_knowledge(client, evidence, save, empty_manifest, rag_case)
                result, tools, channel_failed = run_turns(client, case['user_turns'])
                ticket = result.get('ticket')
                observation = {'result': result, 'tool_calls': [{'tool_name': row['tool_name'],
                               'arguments_json': row.get('arguments_json'), 'receipt_json': row.get('receipt_json')}
                              for row in tools], 'ticket': ticket,
                               'setup_failed': channel_failed, 'model_channel_failed': channel_failed}
                evidence['observation'] = observation
                evidence['scores'] = score_support(case, observation)
                evidence['status'] = 'SCORED'
                if not channel_failed and case.get('checkable_claims'):
                    judge_targets.append({'case': case, 'result': result, 'row': evidence['scores'],
                                          'path': path})
            except AnnotationError:
                raise
            except Exception as error:
                evidence['status'] = 'SETUP_FAILED'
                evidence['error'] = type(error).__name__
                evidence['error_text'] = str(error)[:800]
                evidence['scores'] = score_support(case, {'setup_failed': True})
            finally:
                if client is not None:
                    client.close()
                if trials > 1 and evidence.get('scores') is not None:
                    evidence['scores']['trial'] = trial
                evidence['finished_at'] = now()
                save()
            rows.append(evidence['scores'])
    if judge_targets:
        errors = []
        pairs = [(target['case'], target['result'], target['row']) for target in judge_targets]
        apply_judge_faithfulness(rows, pairs, judge_config(), errors=errors)
        apply_judge_answer_side(rows, pairs, judge_config(), errors=errors)
        for target in judge_targets:
            if not target['path'].exists():
                continue
            evidence = json.loads(target['path'].read_text())
            evidence['scores'] = target['row']
            if errors:
                evidence['judge_errors'] = [item for item in errors if item['case_id'] == target['case']['case_id']]
            write(target['path'], evidence)
        if errors:
            print('judge_errors:', json.dumps(errors, ensure_ascii=False))
        sampled = write_human_review(output, judge_targets)
        if sampled:
            print('judge_human_review_sampled:', sampled)
    return rows


def pick_live_sku(client, exclude_key=None):
    snapshot = client.catalog
    stocks = { (row['productId'], row['propertyValueIdHash']): row.get('stock')
               for row in client.java.request('stock', '/internal/stock/getBatch', data=[
                   {'productId': sku['productId'], 'propertyValueIdHash': sku['propertyValueIdHash']}
                   for sku in snapshot.get('skus', [])]) } if snapshot.get('skus') else {}
    for sku in snapshot.get('skus', []):
        product = next((row for row in snapshot.get('products', []) if row['productId'] == sku['productId']), None)
        key = sku['productId'] + ':' + sku['propertyValueIdHash']
        if (exclude_key is None or key != exclude_key) and product and product.get('status') == 1 \
                and stocks.get((sku['productId'], sku['propertyValueIdHash']), 0) >= 1:
            return {**sku, 'product_name': product.get('productName')}
    raise ValueError('no_sellable_sku_in_scenario')


def pay_sku(client, sku):
    conversation = client.conversation()
    proposal = client.propose(conversation, 'order', {
        'payMethod': 'mock', 'addressId': client.session['addressId'], 'orderFrom': 0,
        'orderList': [{'productId': sku['productId'],
                       'propertyValueIds': sku['propertyValueIds'], 'buyCount': 1}]})
    confirmed = client.confirm(proposal)
    paid = client.pay(confirmed)
    pay_id = (paid.get('payOrderId') or (confirmed.get('receipt') or {}).get('payOrderId'))
    if not pay_id:
        raise ValueError('confirm_missing_pay_order')
    return pay_id


# 指标↔设计↔归因层映射（P6，用户点名）：每个公开指标测的是哪层设计、失败时到哪里归因。
METRIC_DESIGN_MAP = [
    ('Pass@1（导购）',
     '硬约束编译链：购买帧/价格/类目抽取（shopping_mission）→ 溯源守卫 ground_tool_params → 资格门 sku_satisfies → 选择纪律（预算内/金标内）',
     'case 文件 scores（outcome/hits/selected）+ 检索回执 filter_report.applied_constraints'),
    ('Precision@4/ceiling（导购）',
     '检索两段排序（BM25+dense→RRF 合并→精排取 8、展示 4）与必含词完整性纪律',
     'per-case P@4 与 hits/selected 差集；required_terms 缺词看 filter_report.term_constraint'),
    ('Recall@8（客服）',
     '知识检索 FINAL_DEPTH=8 召回面（两段排序+空集放宽 recall_relaxed）',
     '检索回执 candidates vs 金标 relevant_doc_ids，逐 doc 核对'),
    ('Faithfulness（客服）',
     '答案引用纪律（quote 门控：supported 必须附答案原句）+ DeepSeek judge 独立判分（与主模型不同源，温度 0）',
     'scores.judge_verdicts/judge_quotes + judge/human-review 人审清单'),
    ('pass^k（双线）',
     '模型采样方差（不播种的 k 次独立试验）',
     'flip_cases 与 per_case_trials 逐题 k 次结局表'),
    ('Tier-1 诊断列（Recall@1 / MRR@8 / Context_Precision@8 / violation_free@1 / empty_set_honesty / 建单 F1）',
     '判别力在饱和指标之下的层：检索首位与排序质量（@8 已饱和）、导购首位资格门、空集收口诚实、建单边界',
     '全部确定性、试验级聚合、不进公开表头；失败归因到检索排序/资格门/收口纪律/建单编译终态'),
]


def _fmt_ci(value, ci):
    if value is None:
        return '—'
    low, high = (ci or [None, None])
    if low is None:
        return '%.4f' % value
    return '%.4f [%.3f, %.3f]' % (value, low, high)


def _latest_calibration():
    import glob
    reports = sorted(glob.glob(str(ARTIFACT / 'judge-calibrate*' / 'calibration-report.json')),
                     key=lambda p: __import__('os').path.getmtime(p))
    if not reports:
        return None
    try:
        return json.loads(Path(reports[-1]).read_text())
    except (OSError, json.JSONDecodeError):
        return None


def write_frozen_report(run_dir):
    """P6 冻结报告：把一个已完成 run 的 summary 渲染成人读 markdown。只读，不改数。"""
    run_dir = Path(run_dir)
    summary = json.loads((run_dir / 'summary.json').read_text())
    out = ['# quality-v2 冻结报告：%s' % run_dir.name, '']
    gen_at = datetime.now(timezone.utc).isoformat()
    prov = summary.get('provenance') or {}
    out += ['- 生成时间：%s' % gen_at,
            '- 官方：%s | partial：%s | 每题试验数：%s' % (summary.get('official'), summary.get('partial'), summary.get('trials')),
            '- git_head：`%s` | 合同 sha：`%s`' % (prov.get('git_head'), str(prov.get('contract_sha256'))[:16]),
            '- 判据：metrics-contract v6/v6.1；不合成总分；模拟 CTR/CVR 非因果（仅诊断）。', '']

    out += ['## 成绩总览（值 [Wilson 95% CI]，分母并排）', '',
            '| 线 | 指标 | 值 [CI] | 分母 |', '|---|---|---|---|']
    for line, metrics in (
            ('导购', [('Pass@1（公开）', 'Pass@1'), ('Precision@4/ceiling（公开）', 'Precision@4/ceiling'),
                      ('raw Precision@4（诊断）', 'Precision@4'), ('Precision@4_ceiling（诊断）', 'Precision@4_ceiling'),
                      ('violation_free@1（诊断，Tier-1）', 'violation_free@1'),
                      ('empty_set_honesty（诊断，Tier-1）', 'empty_set_honesty')]),
            ('客服', [('Recall@8（公开）', 'Recall@8'), ('Recall@4（诊断）', 'Recall@4_diagnostic'),
                      ('Recall@1（诊断，Tier-1）', 'Recall@1'), ('MRR@8（诊断，Tier-1）', 'MRR@8'),
                      ('Context_Precision@8（诊断，Tier-1）', 'Context_Precision@8'),
                      ('Faithfulness（公开，judge）', 'Faithfulness'), ('Faithfulness_rule（诊断）', 'Faithfulness_rule'),
                      ('Faithfulness_answer_side（诊断）', 'Faithfulness_answer_side'), ('Peripheral_coverage（诊断）', 'Peripheral_coverage')])):
        block = summary.get(line_key := {'导购': 'shopping', '客服': 'support'}[line]) or {}
        ci = block.get('ci95_wilson') or {}
        dens = block.get('denominators') or {}
        for label, key in metrics:
            if key in block:
                out.append('| %s | %s | %s | %s |' % (line, label, _fmt_ci(block.get(key), ci.get(key)), dens.get(key, '—')))
    handoff_block = (summary.get('support') or {}).get('handoff_f1') or {}
    if handoff_block:
        def _num(value):
            return '—' if value is None else '%.4f' % value
        out.append('')
        out.append('建单 F1（诊断，Tier-1）：P=%s R=%s F1=%s（分母 %s 试验；剔除 allow_handoff %s 试验；tp=%s fp=%s fn=%s）' % (
            _num(handoff_block.get('precision')), _num(handoff_block.get('recall')),
            _num(handoff_block.get('f1')), handoff_block.get('denominator'),
            handoff_block.get('excluded_allow_handoff'),
            handoff_block.get('tp'), handoff_block.get('fp'), handoff_block.get('fn')))
    out.append('')

    out += ['## 可靠性（k 次试验）', '']
    for line, key in (('导购', 'shopping'), ('客服', 'support')):
        block = summary.get(key) or {}
        pk = block.get('pass^k') or {}
        if pk:
            out.append('- %s：pass^%d = %.3f（%d/%d 题全过）；翻转题：%s' % (
                line, pk.get('k', 0), pk.get('value', 0), pk.get('n_all_pass', 0), pk.get('n_eligible', 0),
                ', '.join(block.get('flip_cases') or []) or '无'))
        out.append('- %s：计分 %s / setup_failed %s' % (line, block.get('n_scored'), block.get('n_setup_failed')))
    out.append('')

    out += ['## Judge 与校准', '']
    calib = _latest_calibration()
    if calib:
        out.append('- 判分模型：`%s`；prompt 版本：`%s`（校准执行时口径）' % (
            calib.get('judge_flash_model'), calib.get('judge_prompt_version')))
        out.append('- 校准一致率：flash 对金标 %.3f、deepseek-v4-pro 对金标 %.3f、双 judge 二元 Cohen\'s κ=%.3f（证据 %s）' % (
            calib.get('flash_agreement_with_gold') or 0, calib.get('pro_agreement_with_gold') or 0,
            calib.get('cohens_kappa_binary') or 0, calib.get('generated_at', '')[:10]))
    else:
        out.append('- 未找到 judge 校准报告（judge-calibrate-*）。')
    review = run_dir / 'judge' / 'human-review.md'
    try:
        review_label = '已生成 `%s`' % review.resolve().relative_to(ROOT) if review.exists() else '本 run 未生成'
    except ValueError:
        review_label = '已生成（run 目录在仓库外）' if review.exists() else '本 run 未生成'
    out.append('- 20 条判定人审清单：%s' % review_label)
    out.append('')

    out += ['## 失败结构（outcome != pass）', '']
    cases = summary.get('cases') or {}
    failures = {'shopping': [], 'support': []}
    for line, rows in cases.items():
        for row in rows or []:
            if row.get('outcome') == 'pass':
                continue
            reason = (row.get('reason')
                      or ('、'.join(row.get('failed_assertions') or []) or None)
                      or ('must_not_claim:' + '、'.join(row.get('must_not_claim_hit') or []) if row.get('must_not_claim_hit') else None)
                      or ('forbidden_leak' if row.get('forbidden_leak') else None))
            if not reason and line == 'shopping' and isinstance(row.get('selected'), list):
                selected, hits = row['selected'], row.get('hits')
                if isinstance(hits, int) and hits < len(selected):
                    reason = '选品越金标（hits %d/%d）' % (hits, len(selected))
                elif row.get('handoff'):
                    reason = '意外转人工'
                else:
                    reason = '收口纪律（约束回显/数量披露）'
            if not reason and row.get('handoff'):
                reason = 'handoff 与金标不符'
            if not reason:
                reason = row.get('outcome')
            failures[line].append((row.get('case_id'), row.get('trial'), row.get('outcome'), reason))
    names = {'shopping': '导购', 'support': '客服'}
    for line, rows in failures.items():
        out.append('**%s（%d 个失败试验）**' % (names[line], len(rows)))
        if rows:
            out.append('')
            out.append('| 题 | 试验 | 结局 | 归因 |')
            out.append('|---|---|---|---|')
            for cid, trial, outcome, reason in rows:
                out.append('| %s | %s | %s | %s |' % (cid, trial or '—', outcome, str(reason)[:80]))
        out.append('')
    pct = summary.get('per_case_trials') or {}
    out.append('**逐题 k 次方差（非满分题）**')
    out.append('')
    for line, block in pct.items():
        imperfect = [c for c in (block.get('cases') or [])
                     if (c.get('n_pass') if 'n_pass' in c else c.get('passes', 0)) < (c.get('n_scored') or c.get('scored') or 0)
                     or any(t.get('outcome') != 'pass' for t in c.get('trials') or [])]
        if imperfect:
            out.append('- %s：%s' % (names.get(line, line), ', '.join(
                '%s(%s)' % (c.get('case_id'), '/'.join(t.get('outcome', '?')[:4] for t in c.get('trials') or []))
                for c in imperfect)))
    out.append('')

    out += ['## 指标↔设计↔归因层映射表', '',
            '| 指标 | 测量的设计层 | 失败归因路径 |', '|---|---|---|']
    for metric, design, attribution in METRIC_DESIGN_MAP:
        out.append('| %s | %s | %s |' % (metric, design, attribution))
    out.append('')

    out += ['## Provenance', '']
    out += ['- ' + k + '：`' + str(v)[:64] + '`' for k, v in prov.items()]
    out.append('')
    report = '\n'.join(out)
    (run_dir / 'report.md').write_text(report)
    return report


def print_lines(report):
    print(json.dumps({
        'official': report['official'],
        'partial': report.get('partial'),
        'synthetic': report.get('synthetic'),
        'composite_score': report['composite_score'],
        'note': report['note'],
        'shopping': report['shopping'],
        'support': report['support'],
        'rerun_ledger': report.get('rerun_ledger'),
        'provenance': report['provenance'],
    }, ensure_ascii=False, indent=2))


def freeze_holdout():
    """Stamp dev-set digests. Authoring the holdout questions stays a human task."""
    if FREEZE_MANIFEST.exists():
        raise SystemExit('holdout_already_frozen:' + str(FREEZE_MANIFEST))
    manifest = {
        'schema_version': 'quality-v2-holdout-freeze-v1',
        'frozen_at': datetime.now(timezone.utc).isoformat(),
        'frozen_by': 'scripts/eval_quality_v2.py freeze',
        'note': '冻结开发集形态。留出题目尚未出；出题后以其自身 manifest 为准，禁止用留出调系统。',
        'dev_digests': {
            'shopping_dev_sha256': digest(SHOPPING_DEV),
            'support_dev_sha256': digest(SUPPORT_DEV),
            'catalog_snapshot_sha256': digest(SHOPPING_CATALOG),
            'metrics_contract_sha256': digest(CONTRACT_JSON),
        },
        'provenance': provenance(),
    }
    HOLDOUT_DIR.mkdir(parents=True, exist_ok=True)
    FREEZE_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description='quality-v2 development evaluation')
    parser.add_argument('command', choices=('self-check', 'validate', 'freeze', 'judge',
                                            'judge-calibrate', 'run', 'report', 'report-frozen', 'score',
                                            'gate', 'probes'))
    parser.add_argument('--line', choices=('shopping', 'support', 'all'), default='all')
    parser.add_argument('--split', default='development')
    parser.add_argument('--run-id', default=None)
    parser.add_argument('--output', default=None)
    parser.add_argument('--official', action='store_true')
    parser.add_argument('--trials', type=int, default=1,
                        help='每题独立试验次数（各自 fresh scenario）')
    parser.add_argument('--sample', type=int, default=None,
                        help='judge: sample N cases per line; default judges every claim case (dev only)')
    parser.add_argument('--pro-model', default='deepseek-v4-pro',
                        help='judge-calibrate: second judge model for cross-judging')
    parser.add_argument('--case', action='append', default=[],
                        help='optional case_id; repeat or comma-separate to rerun a subset')
    parser.add_argument('--baseline', default=None,
                        help='gate/probes: baseline run dir with summary.json (gate compares against it)')
    args = parser.parse_args()
    if args.trials < 1:
        raise SystemExit('--trials must be >= 1')
    refuse_holdout(args.split)
    if args.split == 'holdout':
        from quality_v2 import holdout_ready
        holdout_ready(() if args.line == 'all' else (args.line,))
    if args.split == 'holdout2':
        from quality_v2 import holdout2_ready
        holdout2_ready(() if args.line == 'all' else (args.line,))
    if args.split == 'holdout3':
        from quality_v2 import holdout3_ready
        holdout3_ready(() if args.line == 'all' else (args.line,))
    if args.split == 'holdout4':
        from quality_v2 import holdout4_ready
        holdout4_ready(() if args.line == 'all' else (args.line,))
    run_id = args.run_id or (args.command + '-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    output = Path(args.output) if args.output else ARTIFACT / run_id
    lines = ('shopping', 'support') if args.line == 'all' else (args.line,)

    if args.command == 'self-check':
        shopping, support = self_check_scores()
        report = write_report(output, shopping, support, official=False, synthetic=True)
        print_lines(report)
        return
    if args.command == 'validate':
        validate_dev_sets(lines, split=args.split)
        print(f'{args.split}_sets_ok:', ','.join(lines))
        return
    if args.command == 'freeze':
        freeze_holdout()
        return
    if args.command == 'judge':
        run_llm_judge(output, lines, sample=args.sample)
        return
    if args.command == 'judge-calibrate':
        run_calibration(output, pro_model=args.pro_model)
        return
    if args.command == 'report':
        summary = load_json(output / 'summary.json') if (output / 'summary.json').exists() else None
        if summary is None:
            raise SystemExit('missing_summary; run self-check or run first')
        print_lines(summary)
        return
    if args.command == 'report-frozen':
        if not (output / 'summary.json').exists():
            raise SystemExit('missing_summary; report-frozen needs a completed run directory')
        write_frozen_report(output)
        try:
            label = str((output / 'report.md').resolve().relative_to(ROOT))
        except ValueError:
            label = str(output / 'report.md')
        print(json.dumps({'report_written': label, 'run_dir': str(output)}, ensure_ascii=False))
        return
    if args.command == 'run':
        if not growth_up():
            raise SystemExit('growth_not_healthy; use self-check or start an isolated stack')
        validate_dev_sets(lines, split=args.split)
        shopping, support = [], []
        if 'shopping' in lines:
            shopping = run_shopping_live(output, args.case, split=args.split, trials=args.trials)
        if 'support' in lines:
            support = run_support_live(output, args.case, split=args.split, trials=args.trials)
        report = write_report(output, shopping, support,
                              official=args.official, partial=bool(args.case), trials=args.trials)
        append_rerun_ledger(output, report)
        print_lines(report)
        return
    if args.command == 'gate':
        if not args.baseline:
            raise SystemExit('gate needs --baseline <run dir>')
        baseline_path = Path(args.baseline) / 'summary.json'
        if not baseline_path.exists():
            raise SystemExit(f'missing_baseline_summary:{baseline_path}')
        if not (output / 'summary.json').exists():
            raise SystemExit('missing_current_summary; run first, or pass --output <dir>')
        from quality_v2 import gate_compare
        verdict = gate_compare(load_json(output / 'summary.json'), load_json(baseline_path))
        (output / 'gate.json').write_text(json.dumps(verdict, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(verdict, ensure_ascii=False, indent=2))
        if verdict['verdict'] == 'BLOCK':
            raise SystemExit('gate_BLOCK')
        return
    if args.command == 'probes':
        if not args.baseline:
            raise SystemExit('probes needs --baseline <run dir>')
        from quality_v2 import failure_probes
        probes = failure_probes(args.baseline)
        case_ids = sorted(probes)
        rerun = ('python scripts/eval_quality_v2.py run --case ' + ','.join(case_ids)
                 + ' --output <新目录>') if case_ids else None
        print(json.dumps({'count': len(case_ids), 'probes': probes, 'rerun': rerun},
                         ensure_ascii=False, indent=2))
        return
    raise SystemExit('unknown_command')


if __name__ == '__main__':
    main()
