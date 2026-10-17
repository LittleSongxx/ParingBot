"""Prepare the default store so the live UI can show featured products, answer policy, and demo a purchase.

This writes only execution_scope_id=store. It never seeds isolated eval scenarios,
registers a scope, or approves set_recommendation_policy.
"""
import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import uuid

import httpx

from eval_support import json_value, login_merchant, proposal_from, wait_for
from runtime import ROOT, ENV_FILE, parse_env
from seed_knowledge import seed as seed_knowledge
from smartlect.commerce import CommerceClient, CommerceError


PLAYBOOK_VERSION = 'store-playbook-v1'
PLAYBOOK_COUPON_NAME = '默认店体验秒杀券'
SHANGHAI = timezone(timedelta(hours=8))
ARTIFACT = ROOT / 'artifacts/store-playbook.json'
PREFERRED_PRODUCTS = (
    '065293686460191',
    '622491960431656',
    '303019597302892',
    '917186661226040',
    '683735539720416',
    '748346463863251',
    '438316828084252',
    '763086281772264',
    '664740861226404',
    '378919755916188',
    '350000232815799',
    '422543322296606',
)
DEMO_USER_INDEX = 0
DEMO_ACCOUNT = '9100000000'
PERSONAS = (
    {'user_index': 0, 'browse': ('065293686460191', '303019597302892', '438316828084252'),
     'order': '065293686460191'},
    {'user_index': 1, 'browse': ('622491960431656', '748346463863251', '763086281772264'),
     'order': '622491960431656'},
    {'user_index': 2, 'browse': ('683735539720416', '350000232815799', '650980987345712'),
     'order': '683735539720416'},
    {'user_index': 3, 'browse': ('917186661226040', '664740861226404', '422543322296606'),
     'order': '917186661226040'},
)


def playbook_id(kind, product_id):
    return hashlib.sha256(f'{PLAYBOOK_VERSION}:{kind}:{product_id}'.encode()).hexdigest()[:32]


def is_isolated_product(product_id):
    return str(product_id).startswith(('9100', '9300'))


def pick_catalog_skus(items, *, min_count=2, max_count=12, preferred=PREFERRED_PRODUCTS):
    available = [item for item in items
                 if not is_isolated_product(item['product_id']) and (item.get('stock') or 0) >= 1]
    by_product = {}
    for item in available:
        by_product.setdefault(item['product_id'], []).append(item)
    for group in by_product.values():
        group.sort(key=lambda item: item['sku_key'])
    selected, seen = [], set()
    for product_id in preferred:
        if product_id in by_product and product_id not in seen:
            selected.append(by_product[product_id][0])
            seen.add(product_id)
        if len(selected) >= max_count:
            return selected
    extras = sorted((item for item in available if item['product_id'] not in seen),
                    key=lambda item: (-(item.get('stock') or 0), item['product_id'], item['sku_key']))
    for item in extras:
        if item['product_id'] in seen:
            continue
        selected.append(item)
        seen.add(item['product_id'])
        if len(selected) >= max_count:
            break
    if len(selected) < min_count:
        raise AssertionError('default catalog has fewer than %s in-stock SKUs; install catalog first' % min_count)
    return selected




def grant_versions(snapshot, product_scope, merchant_id):
    campaigns = {row['campaign_id']: row['version'] for row in snapshot.get('campaigns', [])
                 if row.get('owner_id') == merchant_id and row.get('product_id') in product_scope}
    creatives = {row['creative_id']: row['version'] for row in snapshot.get('creatives', [])
                 if row.get('owner_id') == merchant_id and row.get('campaign_id') in campaigns}
    return campaigns, creatives


def budget_cap_cents(snapshot, extra=0):
    total = sum(row.get('budget_cents') or 0 for row in snapshot.get('campaigns', [])) + extra
    spent = ((snapshot.get('account') or {}).get('spent_cents') or 0)
    return max(total, spent, 10000)


def grant_is_current(snapshot, product_ids, now=None):
    account = snapshot.get('account') or {}
    grant_id = account.get('grant_id')
    if not grant_id:
        return False
    grant = next((row for row in snapshot.get('grants', []) if row.get('grant_id') == grant_id), None)
    if not grant or grant.get('revoked_at'):
        return False
    until = grant.get('valid_until')
    if not until:
        return False
    expiry = datetime.fromisoformat(until.replace('Z', '+00:00'))
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    if expiry <= (now or datetime.now(timezone.utc)):
        return False
    envelope = grant.get('envelope') or {}
    return set(product_ids) <= set(envelope.get('product_scope') or ())


def competing_fixture_active(snapshot):
    return [row for row in snapshot.get('campaigns', [])
            if row.get('status') == 'ACTIVE' and is_isolated_product(row.get('product_id'))]


def playbook_delivery_ready(snapshot, planned, merchant_id, now=None):
    if not grant_is_current(snapshot, [row['product_id'] for row in planned], now=now):
        return False
    if competing_fixture_active(snapshot):
        return False
    campaigns = {row['campaign_id']: row for row in snapshot.get('campaigns', [])}
    creatives = {row['creative_id']: row for row in snapshot.get('creatives', [])}
    for row in planned:
        campaign = campaigns.get(row['campaign_id'])
        creative = creatives.get(row['creative_id'])
        if not campaign or campaign.get('owner_id') != merchant_id or campaign.get('status') != 'ACTIVE':
            return False
        if not creative or creative.get('status') != 'ACTIVE':
            return False
    return True


def should_skip_walkthrough(skip, replay, artifact):
    if skip:
        return True
    if replay:
        return False
    walk = (artifact or {}).get('walkthrough') or {}
    ticket = (artifact or {}).get('ticket') or {}
    return walk.get('payment_status') == 'PAID' and ticket.get('status') in {'OPEN', 'TAKEN_OVER'}


def grant_envelope(product_ids, cap, *, until=None):
    return {
        'objective': OBJECTIVE,
        'product_scope': list(product_ids),
        'budget_cap_cents': cap,
        'max_budget_change_cents': CAMPAIGN_BUDGET_CENTS,
        'valid_until': (until or datetime.now(timezone.utc) + timedelta(days=365)).isoformat(),
    }


def load_artifact():
    if not ARTIFACT.exists():
        return {}
    return json.loads(ARTIFACT.read_text())


def save_artifact(evidence):
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    temporary = ARTIFACT.with_suffix('.tmp')
    temporary.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, default=json_value) + '\n')
    temporary.replace(ARTIFACT)


def http(client, method, path, ok=(200,), **kwargs):
    response = client.request(method, path, **kwargs)
    assert response.status_code in ok, '%s %s: HTTP %s %s' % (
        method, path, response.status_code, response.text[:800])
    if not response.content:
        return {}
    return response.json()


def origin_headers(client, csrf):
    return {'Origin': str(client.base_url).rstrip('/'), 'X-CSRF-Token': csrf}


def plaza_rush_coupon_payload(now=None):
    current = now or datetime.now(SHANGHAI)
    start = (current - timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
    end = (current + timedelta(days=365)).strftime('%Y-%m-%d %H:%M:%S')
    return {
        'couponName': PLAYBOOK_COUPON_NAME,
        'couponType': 3,
        'discountAmount': 5,
        'totalCount': 100,
        'validStartTime': start,
        'validEndTime': end,
        'rushingstatus': 1,
        'rushingStartTime': start,
        'rushingEndTime': end,
    }


def existing_plaza_coupon(rows, name=PLAYBOOK_COUPON_NAME):
    return next((row for row in rows or [] if row.get('couponName') == name), None)


def list_plaza_seed_coupon(client):
    listed = http(client, 'POST', '/admin-api/discountCoupon/loadDiscountCoupon', data={
        'pageNo': 1, 'pageSize': 50, 'couponNameFuzzy': PLAYBOOK_COUPON_NAME,
    })
    assert listed.get('code') == 200, listed
    return existing_plaza_coupon((listed.get('data') or {}).get('list'))


def warmup_plaza_seed_coupon(client, coupon_id):
    warmed = http(client, 'POST', '/admin-api/discountCoupon/warmupRushStock',
                  data={'couponId': coupon_id})
    assert warmed.get('code') == 200, warmed


def seed_plaza_rush_coupon(client, *, now=None):
    existing = list_plaza_seed_coupon(client)
    if existing:
        coupon_id = existing.get('couponId')
        if existing.get('rushingstatus') == 1 and coupon_id:
            warmup_plaza_seed_coupon(client, coupon_id)
        return {'coupon_id': coupon_id, 'created': False, 'name': PLAYBOOK_COUPON_NAME}
    try:
        saved = http(client, 'POST', '/admin-api/discountCoupon/saveDiscountCoupon',
                     data=plaza_rush_coupon_payload(now))
    except AssertionError as error:
        created = list_plaza_seed_coupon(client)
        if created and created.get('couponId'):
            if created.get('rushingstatus') == 1:
                warmup_plaza_seed_coupon(client, created['couponId'])
            return {'coupon_id': created['couponId'], 'created': True, 'name': PLAYBOOK_COUPON_NAME}
        raise error
    assert saved.get('code') == 200, saved
    created = list_plaza_seed_coupon(client)
    coupon_id = (created or {}).get('couponId')
    if coupon_id and (created or {}).get('rushingstatus') == 1:
        warmup_plaza_seed_coupon(client, coupon_id)
    return {'coupon_id': coupon_id, 'created': True, 'name': PLAYBOOK_COUPON_NAME}


def seed_demo_behavior(java, config, catalog_items):
    by_product = {}
    for item in catalog_items:
        product_id = item.get('product_id')
        if product_id and (item.get('stock') or 0) >= 1:
            by_product.setdefault(product_id, item)
    rows = []
    for persona in PERSONAS:
        session = java.request('admin', '/internal/demo/session', form={
            'userIndex': persona['user_index'], 'password': config['SMARTLECT_DEMO_PASSWORD']})
        browsed = []
        for product_id in persona['browse']:
            try:
                java.request('gateway', '/api/product/getProduct', form={'productId': product_id}, session=session)
                browsed.append(product_id)
            except CommerceError:
                continue
        ordered = None
        sku = by_product.get(persona['order'])
        property_ids = (sku or {}).get('sku_name') or (sku or {}).get('property_value_ids')
        if sku and property_ids:
            try:
                pay = java.request('gateway', '/api/order/postOrder', data={
                    'payMethod': 'mock',
                    'addressId': session['addressId'],
                    'orderFrom': 0,
                    'orderList': [{
                        'productId': persona['order'],
                        'propertyValueIds': property_ids,
                        'buyCount': 1,
                    }],
                }, session=session, key='%s:persona:%s:%s' % (
                    PLAYBOOK_VERSION, session['userId'], persona['order']))
                java.request('pay', '/internal/pay/mock/complete', data={'payOrderId': pay['payOrderId']}, session=session)
                ordered = persona['order']
            except CommerceError:
                ordered = None
        rows.append({
            'account': session['userId'],
            'browse': browsed,
            'order_product_id': ordered,
        })
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-walkthrough', action='store_true')
    parser.add_argument('--replay-walkthrough', action='store_true')
    parser.add_argument('--coupons-only', action='store_true',
                        help='login as merchant and seed the plaza rush coupon, then exit')
    args = parser.parse_args()
    if args.skip_walkthrough and args.replay_walkthrough:
        parser.error('use only one of --skip-walkthrough and --replay-walkthrough')
    if args.coupons_only and (args.skip_walkthrough or args.replay_walkthrough):
        parser.error('--coupons-only cannot be combined with walkthrough flags')

    config = parse_env(ENV_FILE)
    assert config.get('SMARTLECT_PAYMENT_MODE') == 'mock', 'mock payment required'
    if args.coupons_only:
        base = 'http://127.0.0.1:' + config['SMARTLECT_GATEWAY_PORT']
        with httpx.Client(base_url=base, timeout=120, trust_env=False) as merchant:
            login_merchant(merchant, config)
            coupon = seed_plaza_rush_coupon(merchant)
        print(json.dumps({'status': 'READY', 'coupon': coupon}, ensure_ascii=False, indent=2))
        return
    assert config.get('SMARTLECT_DEMO_ENABLED', '').lower() == 'true', 'SMARTLECT_DEMO_ENABLED=true required'
    prior = load_artifact()
    evidence = {
        'playbook': PLAYBOOK_VERSION,
        'status': 'RUNNING',
        'execution_scope_id': 'store',
        'demo_user': {'user_index': DEMO_USER_INDEX, 'account': DEMO_ACCOUNT},
        'password_hint': 'SMARTLECT_DEMO_PASSWORD in run/runtime.env',
    }

    def stage(label):
        evidence['stage'] = label
        save_artifact(evidence)
        print(label, flush=True)

    stage('Seed store knowledge and demo shoppers')
    asyncio.run(seed_knowledge(False))
    java = CommerceClient(config)
    java.request('admin', '/internal/demo/seed')
    user = java.request('admin', '/internal/demo/session', form={
        'userIndex': DEMO_USER_INDEX, 'password': config['SMARTLECT_DEMO_PASSWORD']})
    assert str(user['userId']) == DEMO_ACCOUNT
    evidence['demo_user']['address_id'] = user['addressId']
    save_artifact(evidence)

    base = 'http://127.0.0.1:' + config['SMARTLECT_GATEWAY_PORT']
    web_user = 'http://127.0.0.1:' + config.get('SMARTLECT_WEB_USER_PORT', '18180')
    web_admin = 'http://127.0.0.1:' + config.get('SMARTLECT_WEB_ADMIN_PORT', '18181')

    with httpx.Client(base_url=base, timeout=45, trust_env=False) as merchant, \
            httpx.Client(base_url=base, timeout=45, trust_env=False) as shopper, \
            httpx.Client(base_url=base, timeout=45, trust_env=False) as guest:
        stage('Merchant login on the default store')
        merchant_headers = login_merchant(merchant, config)
        auth = http(merchant, 'GET', '/admin-api/assistant/session')
        if auth['actor']['execution_scope_id'] != 'store':
            selected = http(merchant, 'POST', '/admin-api/assistant/scopes/select',
                            json={'execution_scope_id': 'store'}, headers=merchant_headers)
            merchant_headers = origin_headers(merchant, selected['csrf_token'])
            auth = http(merchant, 'GET', '/admin-api/assistant/session')
        assert auth['actor']['execution_scope_id'] == 'store', auth['actor']
        merchant_id = auth['actor']['actor_id']
        merchant_headers = origin_headers(merchant, auth['csrf_token'])

        stage('Seed default store shipping address')
        logistics_payload = http(merchant, 'POST', '/admin-api/setting/getLogistics')
        current_logistics = logistics_payload.get('data') if isinstance(logistics_payload, dict) else None
        if not (current_logistics or {}).get('senderName'):
            saved = merchant.post('/admin-api/setting/saveLogistics', data={
                'senderName': '智选演示仓',
                'senderPhone': '010-88880000',
                'senderAddress': '北京市朝阳区智选路 1 号演示仓',
            })
            assert saved.status_code == 200 and saved.json().get('code') == 200, saved.text
            current_logistics = (http(merchant, 'POST', '/admin-api/setting/getLogistics') or {}).get('data')
        evidence['logistics'] = {
            'senderName': (current_logistics or {}).get('senderName'),
            'senderPhone': (current_logistics or {}).get('senderPhone'),
        }
        save_artifact(evidence)

        stage('Seed an in-window plaza rush coupon')
        evidence['coupon'] = seed_plaza_rush_coupon(merchant)
        save_artifact(evidence)

        shopper.cookies.set('token', user['token'])
        shopper_session = http(shopper, 'GET', '/api/assistant/session')
        assert shopper_session['actor']['execution_scope_id'] == 'store', shopper_session['actor']
        shopper_headers = origin_headers(shopper, shopper_session['csrf_token'])

        stage('Pick in-stock catalog SKUs for demo personas')
    print(json.dumps({
        'status': 'READY',
        'campaigns': len(evidence.get('campaigns', [])),  # 广告线 v7 退役，保留字段兼容输出
        'walkthrough': evidence.get('walkthrough', {}),
        'ticket': evidence.get('ticket', {}),  # 退役收口：ticket 不再是局部变量
        'login': DEMO_ACCOUNT,
        'password': 'see SMARTLECT_DEMO_PASSWORD in run/runtime.env',
        'open_ticket_as_shopper': (evidence.get('urls') or {}).get('assistant'),
        'open_ticket_as_merchant': (evidence.get('urls') or {}).get('admin_support'),
        'artifact': str(ARTIFACT.relative_to(ROOT)),
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
