"""Shared final-demo HTTP client; setup writes only Growth-owned resource mappings.

Java owns fixture allocation and every transaction. No service management, original
project access, direct commerce SQL, or fabricated model/financial outcomes.
"""
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import subprocess
import time
import uuid

import httpx

from eval_support import cents, login_merchant, proposal_from
from runtime import ROOT, ENV_FILE, model_env, parse_env
from smartlect.commerce import CommerceClient
from smartlect.db import connect_from_env
from smartlect.adminscope import AdminScopeStore
from smartlect.scenario_scope import ScenarioScopeStore


def now():
    return datetime.now(timezone.utc).isoformat()


class ScenarioClient:
    def __init__(self, evidence, save, *, requested_mode='configured'):
        self.evidence, self.save = evidence, save
        self.config = {**parse_env(ENV_FILE), **model_env()}
        if self.config.get('SMARTLECT_PAYMENT_MODE') != 'mock':
            raise ValueError('demo_requires_mock_payment')
        self.base = 'http://127.0.0.1:' + self.config['SMARTLECT_GATEWAY_PORT']
        assistant = 'http://127.0.0.1:' + self.config['SMARTLECT_ASSISTANT_PORT']
        with httpx.Client(timeout=10, trust_env=False) as client:
            health = client.get(assistant + '/health')
            health.raise_for_status()
            health = health.json()
        self.mode = health['model_mode']
        if self.mode not in {'live', 'mock'} or requested_mode not in {'configured', self.mode}:
            raise ValueError('requested_mode_differs_from_running_api; configure_and_restart_before_demo')
        if self.mode == 'live' and not self.config.get('SMARTLECT_MODEL_API_KEY'):
            raise ValueError('live_model_not_configured')
        for key, value in self.config.items():
            if key.startswith(('SMARTLECT_ASSISTANT_MYSQL_', 'SMARTLECT_MYSQL_')):
                os.environ[key] = value
        self.java = CommerceClient(self.config)
        self.store = AdminScopeStore()
        # register_scope 在架构清晰化重构中从 AdminScopeStore 移到 ScenarioScopeStore
        self.scopes = ScenarioScopeStore(self.store.connect)
        self.clients = ExitStack()
        self.user = self.clients.enter_context(httpx.Client(base_url=self.base, timeout=35, trust_env=False))
        self.merchant = self.clients.enter_context(httpx.Client(base_url=self.base, timeout=60, trust_env=False))
        self.evidence.update(model_mode=self.mode, ai_capability_verified=False, payment_mode='mock',
                             java_http=True, model_runs=[], writes=[], checks=[], knowledge=[])
        self.evidence['source'] = {'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            'working_diff_sha256': hashlib.sha256(subprocess.check_output(
                ['git', 'diff', '--binary', 'HEAD', '--', '.', ':(exclude)evals/rag_cases.jsonl'], cwd=ROOT)).hexdigest(),
            'driver_sha256': {name: hashlib.sha256((ROOT / 'scripts' / name).read_bytes()).hexdigest()
                              for name in ('scenario_client.py',)}}

    def close(self):
        self.clients.close()

    def stage(self, label):
        self.evidence['stage'] = label
        self.save()
        print(label, flush=True)

    def check(self, condition, label):
        if not condition:
            raise AssertionError(label)
        self.evidence['checks'].append(label)
        self.save()

    def _fresh_csrf(self, merchant=False):
        # 服务端 CSRF nonce 一次性消费（与前端 refreshCsrf 契约一致）：每次写前取新 token
        client, prefix = (self.merchant, '/admin-api/assistant/') if merchant else (self.user, '/api/assistant/')
        response = client.get(prefix + 'session')
        response.raise_for_status()
        return {'Origin': self.base, 'X-CSRF-Token': response.json()['csrf_token']}

    def request(self, path, payload=None, *, merchant=False, method=None, params=None, accepted=(200,)):
        client, _ = (self.merchant, self.mheaders) if merchant else (self.user, self.uheaders)
        method = method or ('POST' if payload is not None else 'GET')
        prefix = '/admin-api/assistant/' if merchant else '/api/assistant/'
        record = None
        if method != 'GET':
            record = {'path': prefix + path, 'method': method, 'request': payload, 'started_at': now()}
            self.evidence['writes'].append(record)
            self.save()  # Durable original request before every business write; no cookies/CSRF in evidence.
        headers = self._fresh_csrf(merchant) if method != 'GET' else None
        response = client.request(method, prefix + path, json=payload, params=params, headers=headers)
        if record is not None:
            record.update(http_status=response.status_code, completed_at=now())
            self.save()
        if response.status_code not in accepted:
            raise AssertionError(f'{method} {prefix + path}: HTTP {response.status_code}')
        result = response.json()
        if record is not None:
            record['response'] = ({'actor_id': result['actor']['actor_id'],
                                   'execution_scope_id': result['actor']['execution_scope_id']}
                                  if path == 'scopes/select' else result)
            self.save()
        return result if response.status_code == 200 else {'http_status': response.status_code, 'body': result}

    def wait(self, read, predicate, label, *, timeout=45):
        self.stage(label)
        deadline = time.monotonic() + timeout
        while True:
            value = read()
            if predicate(value):
                return value
            if time.monotonic() >= deadline:
                raise AssertionError('bounded_wait_expired: ' + label)
            time.sleep(.3)

    @staticmethod
    def rows(sql, params=()):
        with connect_from_env() as connection, connection.cursor() as cursor:
            cursor.execute(sql, params)
            return list(cursor.fetchall())

    def setup(self, *, actor_ref=None, product_count=2, initial_stock=5, user_count=3):
        if actor_ref not in {None, 'user_a', 'user_b', 'visitor'}:
            raise ValueError('unsupported_scenario_actor')
        if type(product_count) is not int or not 1 <= product_count <= 20:
            raise ValueError('invalid_scenario_product_count')
        self.stage('Java allocates a new owned demo scope and independent users/SKUs')
        request = {'scenarioRunId': self.evidence['run_id'], 'branchId': self.evidence['scenario'],
                   'userCount': user_count, 'productCount': product_count, 'initialStock': initial_stock}
        self.evidence['seed_request'] = request
        self.save()
        self.manifest = self.java.request('admin', '/internal/demo/scenario/seed', data=request)
        self.scope = self.manifest['executionScopeId']
        self.evidence.update(java_manifest=self.manifest, execution_scope_id=self.scope)
        self.save()
        self.check(self.java.request('admin', '/internal/demo/scenario/read', data={'executionScopeId': self.scope})
                   == self.manifest, 'Java registry persists the exact new scenario manifest')
        visitor_id = None
        if actor_ref == 'visitor':
            guest = self.user.get('/api/assistant/session')
            guest.raise_for_status()
            visitor = guest.json()['actor']
            self.check(visitor['subject_type'] == 'visitor', 'Anonymous setup receives a signed visitor identity')
            visitor_id = visitor['actor_id']
        self.scopes.register_scope(self.scope, scenario_run_id=self.evidence['run_id'], branch_id=self.evidence['scenario'],
            users=[u['userId'] for u in self.manifest['users']], products=self.manifest['products'],
            **({'visitors': [visitor_id]} if visitor_id else {}))
        self.session = None
        if actor_ref != 'visitor':
            self.session = self.java.request('admin', '/internal/demo/scenario/session', data={
                'executionScopeId': self.scope, 'userIndex': {'user_a': 0, 'user_b': 1}.get(actor_ref, self.evidence['seed'] % 3),
                'password': self.config['SMARTLECT_DEMO_PASSWORD']})
            self.evidence['user_id'] = self.session['userId']
            self.user.cookies.set('token', self.session['token'])
        auth = self.user.get('/api/assistant/session')
        auth.raise_for_status()
        auth = auth.json()
        self.check(auth['actor']['execution_scope_id'] == self.scope and
                   auth['actor']['actor_id'] == (visitor_id if visitor_id else self.session['userId']) and
                   auth['actor']['subject_type'] == ('visitor' if visitor_id else 'user'),
                   'Normal cookie bridge selects the server-owned actor and scope')
        if visitor_id:
            self.check(auth['actor']['permissions'] == ['shopping:read'], 'Scoped visitor keeps read-only Shopping permissions')
        self.actor = auth['actor']
        self.uheaders = {'Origin': self.base, 'X-CSRF-Token': auth['csrf_token']}
        self.mheaders = login_merchant(self.merchant, self.config)
        actor = self.merchant.get('/admin-api/assistant/session').json()['actor']
        self.store.grant_scope_access(actor['actor_id'], self.scope, self.evidence['run_id'])
        selected = self.request('scopes/select', {'execution_scope_id': self.scope}, merchant=True)
        self.mheaders = {'Origin': self.base, 'X-CSRF-Token': selected['csrf_token']}
        self.catalog = self.java.request('product', '/internal/product/snapshotBatch',
                                         data={'productIds': self.manifest['products']})
        self.evidence['catalogue'] = self.catalog
        self.save()

    def seed_knowledge(self):
        self.stage('Publish unchanged local policy fixtures through the scoped management API')
        names = ('02-payment', '03-refund-request', '04-refund-progress', '06-price-confirmation',
                 '08-sku', '09-order-confirmation', '10-order-query', '12-operation-recovery', '28-human-support')
        for name in names:
            path = ROOT / 'fixtures' / 'knowledge' / (name + '.md')
            body = path.read_text()
            draft = self.request('knowledge', {'doc_id': name, 'title': body.splitlines()[0].lstrip('# '),
                'source_uri': str(path.relative_to(ROOT)), 'body': body, 'acl': 'PUBLIC',
                'valid_from': (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
                'valid_until': (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()}, merchant=True)
            published = self.request(f"knowledge/{name}/{draft['version']}/publish", {}, merchant=True)
            self.check(published['status'] == 'PUBLISHED', 'Published policy ' + name)
            self.evidence['knowledge'].append({'doc_id': name, 'version': draft['version'],
                'sha256': hashlib.sha256(body.encode()).hexdigest()})
        self.collect_index_usage()

    def collect_index_usage(self):
        rows = self.rows('SELECT call_id,doc_id,document_version,status,trace_json,started_at,completed_at '
                         'FROM knowledge_index_attempt WHERE execution_scope_id=%s ORDER BY started_at,call_id', (self.scope,))
        self.evidence['index_attempts'] = [{**row, 'trace_json': json.loads(row['trace_json'])
            if isinstance(row['trace_json'], str) else row['trace_json']} for row in rows]
        self.save()

    def conversation(self):
        value = self.request('conversations', {})['conversation_id']
        self.evidence.setdefault('conversation_ids', []).append(value)
        self.save()
        return value

    def message(self, conversation, text, *, label):
        self.stage(label)
        record = {'domain': 'shopping', 'label': label, 'conversation_id': conversation,
                  'request': {'message_id': uuid.uuid4().hex, 'text': text}, 'started_at': now()}
        self.evidence['model_runs'].append(record)
        self.save()
        created = self.request(f'conversations/{conversation}/messages', record['request'])
        record['agent_run_id'] = created['agent_run_id']
        self.save()
        def read():
            record['run'] = self.request('runs/' + created['agent_run_id'])
            self.save()
            return record['run']
        run = self.wait(read, lambda r: r['state'] not in {'CREATED', 'RUNNING'}, label + ': model completion', timeout=95)
        record['completed_at'] = now()
        record['tool_receipts'] = self.rows('SELECT call_id,tool_name,arguments_json,outcome,receipt_json '
            'FROM tool_call WHERE agent_run_id=%s ORDER BY started_at,call_id', (created['agent_run_id'],))
        self.save()
        self.require_model_mode(run)
        return run['result']

    def require_model_mode(self, run):
        result, context = run.get('result') or {}, run.get('context') or {}
        self.check(result.get('model_mode') == self.mode, 'Run retains its actual requested model mode')
        call_limit = int(self.config.get('SMARTLECT_MODEL_CALL_LIMIT') or 6)
        self.check(context.get('model_calls', 0) <= (min(4, call_limit) if 'plan' in result else call_limit),
                   'Provider retries and repairs stay within the domain run attempt limit')
        if self.mode == 'live':
            self.check(any(a.get('status') == 'succeeded' and a.get('model_mode') == 'live'
                           and a.get('model_id') in {'qwen3.7-plus', 'qwen3.7-plus-2026-05-26', 'glm-5.3'}
                           for a in context.get('model_attempts', [])), 'Live run includes an actual authorized model attempt')
        else:
            self.check(context.get('model_calls', 0) == 0, 'Mock run makes no model request')

    def verify_citations(self, result):
        self.check(bool(result.get('citations')), 'Policy response includes source citations')
        for citation in result['citations']:
            original = self.request(f"knowledge/{citation['doc_id']}/{citation['version']}")
            self.check(citation['content'] in original['body'], 'Citation excerpt matches the current visible source')

    def stock(self, sku):
        return self.java.request('stock', '/internal/stock/getBatch', data=[{
            'productId': sku['productId'], 'propertyValueIdHash': sku['propertyValueIdHash']}])[0]['stock']

    def select_sku(self, products, product_id):
        selected = next((p for p in products if p['productId'] == product_id), None)
        self.check(selected is not None, 'Recommendation returns the requested real product in this scope')
        original = next(s for s in self.catalog['skus'] if s['productId'] == selected['productId']
                        and s['propertyValueIdHash'] == selected['propertyValueIdHash'])
        self.check(selected['propertyValueIds'] == original['propertyValueIds']
                   and selected['price_cents'] == cents(original['price']) and self.stock(selected) > 0,
                   'Chosen recommendation matches authoritative Java SKU, price and positive stock')
        self.evidence['selected_sku'] = selected
        return selected

    def propose(self, conversation, action_type, parameters):
        return proposal_from(self.request(f'conversations/{conversation}/proposals', {
            'message_id': uuid.uuid4().hex, 'action_type': action_type, 'parameters': parameters}))

    def confirm(self, proposal, *, discard_response=False):
        request = {'proposal_version': proposal.get('decision_version') or proposal['version'], 'approved': True}
        path = f"proposals/{proposal['proposal_id']}/confirm"
        if discard_response:
            record = {'proposal_id': proposal['proposal_id'], 'request': request, 'started_at': now(),
                      'fault': 'client_discards_confirmation_response_body', 'server_unknown_state_asserted': False}
            self.evidence['confirmation_interruption'] = record
            self.save()
            # Real request reaches the normal API. The simulated client loses the body,
            # not the server's durable transaction; do not invent a server UNKNOWN state.
            with self.user.stream('POST', '/api/assistant/' + path, json=request, headers=self._fresh_csrf()) as response:
                record['received_http_status'] = response.status_code
                if response.status_code != 200:
                    raise AssertionError('confirmation_interruption_http_' + str(response.status_code))
            record['response_body_read'] = False
            record['completed_at'] = now()
            self.save()
            current = self.request('proposals/' + proposal['proposal_id'])
            record['recovered_original_proposal'] = current
            self.save()
        else:
            current = proposal_from(self.request(path, request))
        if current['status'] not in {'SUCCEEDED', 'FAILED'}:
            current = self.wait(lambda: proposal_from(self.request(path, request)),
                lambda p: p['status'] in {'SUCCEEDED', 'FAILED'}, 'Recover the same confirmed proposal', timeout=45)
        self.check(current['status'] == 'SUCCEEDED', 'User-confirmed transaction reaches authoritative success')
        self.check(current['proposal_id'] == proposal['proposal_id'], 'Recovery keeps the original approved proposal')
        self.check(all(current[key] == proposal[key] for key in ('action_id', 'idempotency_key')),
                   'Recovery preserves the original action ID and idempotency key')
        return current

    def pay(self, order):
        receipt = order['receipt']
        pay_id, amount = receipt['payOrderId'], receipt['amountCents']
        self.evidence['order_confirmation'] = order
        self.evidence['pay_order_id'] = pay_id
        self.save()
        pending = self.request('payments/' + pay_id)
        self.check(pending['paymentStatus'] == 'PENDING', 'Order confirmation does not implicitly pay')
        self.request('payments/' + pay_id + '/complete', {'expected_amount_cents': amount})
        paid = self.wait(lambda: self.request('payments/' + pay_id),
            lambda p: p['commandStatus'] == 'business_completed', 'Wait for Java simulated payment and order synchronization')
        self.check(paid['paymentStatus'] == 'PAID' and paid['orderSynchronized'], 'Separate user payment confirmation reaches PAID')
        self.evidence['payment_receipt'] = paid
        orders = self.java.request('order', '/internal/order/commerce/listOrders', data={'limit': 30}, session=self.session)
        paid_order = next(o for o in orders if o['payOrderId'] == pay_id)
        item = paid_order['items'][0]
        self.check(len(paid_order['items']) == 1 and item.get('orderId') in {None, paid_order['orderId']},
                   'Single purchased item belongs to its authoritative parent order')
        item = {**item, 'orderId': paid_order['orderId']}
        self.check(cents(item['paidAmount']) == amount, 'Java purchased item cash amount matches payment')
        self.evidence['paid_order_item'] = item
        self.save()
        return item

    def reconcile(self, sku, refund, *, ad_click=None):
        pay_id = self.evidence['pay_order_id']
        amount = self.evidence['order_confirmation']['receipt']['amountCents']
        financial = self.wait(lambda: self.ledger.summary(pay_id),
            lambda r: r['paidCents'] == r['refundedCents'] == amount,
            'Wait for actual Java payment/refund events and Growth ledger')
        events = {e['event_type']: e for e in report['events']}
        rec = self.evidence['recommendation_touch']['click']['touches'][0]
        expected_category = 'AD_ATTRIBUTED' if ad_click else 'NATURAL_VERIFIED'
        self.check(set(events) == {'PAYMENT', 'REFUND'} and financial['netCents'] == 0
                   and financial['paymentConversions'] == 1, 'Exactly one payment and refund reconcile to zero net cents')
        for event in events.values():
            self.check(event['category'] == expected_category and event['execution_scope_id'] == self.scope
                       and event['recommendation_click_id'] == rec['touch_id']
                       and event['recommendation_id'] == sku['recommendation_id']
                       and event['ad_click_id'] == (ad_click['traffic_touch_id'] if ad_click else None)
                       and event['amount_cents'] == amount,
                       'Financial event independently retains its actual traffic and exact-SKU recommendation sources')
        self.check(all(events['PAYMENT'][k] == events['REFUND'][k] for k in (
            'context_id', 'ad_click_id', 'campaign_id', 'creative_id', 'recommendation_click_id',
            'recommendation_id', 'assignment_id', 'strategy_version', 'category')), 'Refund inherits the original attribution')
        final_stock = self.wait(lambda: self.stock(sku), lambda s: s == self.evidence['initial_stock'],
                                'Wait for exactly one refund inventory restoration')
        replay = self.confirm(refund)
        self.check(replay['receipt'] == refund['receipt'] and self.stock(sku) == final_stock,
                   'Repeated confirmation restores neither money nor stock twice')
        self.evidence.update(refund_confirmation=refund, ledger=financial, attribution=report, final_stock=final_stock)
        self.save()
