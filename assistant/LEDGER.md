# Commerce event ledger (F1 runtime, v1 facts)

> **已退役（ADR-0008，2026-10）**：growth 事件消费 worker、`/internal/ledger/summary`
> 端点与 `SMARTLECT_ASSISTANT_EVENTS_ENABLED` 开关已随推荐/归因线退役删除；`assistant`
> 进程不再有独立 consumer，`smartlect.events` 模块与 demo 的 ledger 对账分支同批移除。
> 本文以下内容为 F1/P2 时期的历史记录，保留作设计沿革与验证证据索引，不再描述现役运行态。
> 现役账务事实源是 Java 订单/支付服务本身；30 天保留清理任务已并入 API 进程
> （`app.py` `_retention_loop`）。

Use `./scripts/dev.sh up` with `SMARTLECT_ASSISTANT_EVENTS_ENABLED=true`: it starts
the FastAPI application and an independent `smartlect.worker` consumer. The
checksummed migrations retain `commerce_event`, `commerce_exception` and the
transaction lock row, and add domain task tables only in `smartlect_growth`. It never reads or writes a Java
transaction table. Java owns the AMQP topology and its durable queue/dead-letter
policy; the consumer verifies `smartlect.growth.commerce.queue` already exists.

Required configuration comes from Smartlect's generated runtime environment:

- `SMARTLECT_MYSQL_HOST`, `SMARTLECT_MYSQL_PORT`
- `SMARTLECT_ASSISTANT_MYSQL_DATABASE=smartlect_growth`, `SMARTLECT_ASSISTANT_MYSQL_USER=smartlect_growth`, `SMARTLECT_ASSISTANT_MYSQL_PASSWORD`
- `SMARTLECT_RABBIT_HOST`, `SMARTLECT_RABBIT_PORT`, `SMARTLECT_RABBIT_USER`, `SMARTLECT_RABBIT_PASSWORD`, `SMARTLECT_RABBIT_VHOST`
- `SMARTLECT_INTERNAL_TOKEN`

`GET /health` reports consumer connectivity when enabled; unavailable consumption
returns 503. Disabled mode preserves the keyless P0 health behavior.
`GET /internal/ledger/summary?payOrderId=<id>` requires `X-Internal-Token` and returns
`paidCents`, `refundedCents`, `netCents`, `paymentConversions`, status counts and up
to 1000 event records. Omit the payment ID for whole-ledger totals. This endpoint
is read-only; raw exception payloads are not returned.

## Accepted facts and accounting

Messages are JSON `{"schema_version":1,"events":[...]}` with 1–100 events. Event
fields use the Java camelCase protocol: `eventId`, `idempotencyKey`, `eventType`,
`userId`, `source`, `productId`, `skuKey`, `orderId`, `requestId`, `occurredAt` and
`payload`. Financial payloads require `payOrderId`, `orderItemId`, `currency=CNY`
and exact nonnegative `paidAmount` or `refundAmount`; refunds additionally require
`refundStatus=COMPLETED`. Occurrence and receipt times are stored separately in UTC.

One MySQL transaction persists raw facts/exceptions, evaluates accounting state,
then commits. Only after that commit does AMQP receive a manual ACK. Transaction
or connection failure leaves the message unacknowledged for redelivery. Identical
event/idempotency replays do not add effects; conflicting identifier reuse is
retained as an exception. A distinct PAYMENT for an already accounted item is
marked DUPLICATE only if its ownership, SKU, payment identity and amount agree.

PAYMENT uses item-level actual paid cents; conversions count distinct payment
orders. REFUND applies only against the matching paid item/user/product/SKU and
cannot exceed the item's cumulative paid amount. A refund arriving before its
payment stays PENDING and is reconsidered when new facts arrive. Confirmed refunds
of free items are valid zero-cent facts; stock restoration remains Java's job.
REPEAT_PURCHASE
is an applied behavior label with no revenue effect. Other known behavior events
also have no monetary effect. Unsupported types stay UNKNOWN, malformed facts
are retained in `commerce_exception`, and semantic conflicts stay INVALID.

The initial single ledger row lock intentionally serializes ingestion and
reconciliation. It protects concurrent refunds with a small implementation;
per-payment locks are the upgrade when measured ingestion volume requires them.
No ad attribution, recommendation strategy or optimization benefit is claimed by
these accounting totals.

## Replay and checks

With the same generated environment, `python -m smartlect.events` rechecks pending
facts. `python -m smartlect.events --replay-exception <message_hash>` retries a
retained raw batch without deleting its exception history. Invalid messages are
not silently accepted by replay.

Direct dependencies are declared in `pyproject.toml`, with the full closure fixed
in `requirements.lock`. Usage follows the primary
[Pika consumer documentation](https://pika.readthedocs.io/en/stable/examples/blocking_consumer_generator.html)
and [PyMySQL transaction example](https://pymysql.readthedocs.io/en/latest/user/examples.html).

The following P2 records are historical; current F1 results are in
`../artifacts/f1-validation.json` and `../artifacts/f1-amqp-replay.json`.

Verified in the then-new `assistant/.venv-p2` Python 3.13 environment: package installation
and `pip check` passed. The final real-database run passed all 20 checks (15
foundation/contract/HTTP checks and 5 MySQL tests), without skips. An initial run
caught an empty-tuple versus empty-list summary result; the API now returns a
consistent list and the rollback/replay check passed on rerun. The final log is
`/tmp/smartlect-growth-p2-tests.log`. Run the real database suite serially with:

```bash
SMARTLECT_RUN_MYSQL_TESTS=1 assistant/.venv-p2/bin/python -m unittest discover -s growth/tests -v
```

That suite creates its own 512 MB `smartlect-growth-it-*` MySQL container, applies
the actual ledger schema, checks replay/order/rollback/concurrency and removes
only its verified container. A final zero-cash refund parsing regression also
passed; the latest lightweight run passed 16 checks and deliberately skipped the
5 database checks already executed separately.

Live validation subsequently passed: Java's three paid items and one refund
reconciled to 3475/1000/2475 cents and one payment conversion. A second actual
purchase emitted three REPEAT_PURCHASE labels without extra income. See the
root artifacts/p2-live-ledger.json and the scenario JSON files.
scripts/check_event_replay.py committed the original facts, closed a real AMQP
delivery without ACK, observed redelivery, restarted the actual consumer, and
verified a new broker ACK with unchanged ledger totals. Evidence is in
artifacts/p2-amqp-replay.json. P2 remains incomplete for ad/recommendation
attribution and actual VIEW event integration.
