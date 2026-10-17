# Java 后端收敛验证证据（2026-10-17）

本目录保存本轮 README/ADR/支付/订单状态/热点库存/工程护栏的原始验证输出。它是证据，不是结论；结论与口径见 `docs/改动记录/2026-10-17/` 下对应功能记录。

| 文件 | 内容 |
|---|---|
| `unit-tests.log` | 全仓单元测试日志（516 tests / 0 failure / 0 error） |
| `integration-verify.log` | 最终 `mvn -B -Pintegration verify` 完整日志：9 个 IT 类 / 45 个测试（1 个按条件跳过）、BUILD SUCCESS、JaCoCo 38.7% |
| `dev-check.log` | `./scripts/dev.sh check`：Java 单测、assistant 339 tests（68 skipped）、双前端 79 tests、自检与进程独立性检查 |

相关证据在相邻目录：

- `../order-load/`：10/20 VU、热点库存开/关四轮原始 JSON；汇总口径见 `docs/verification/order-load.md`。
- `../pay-signature/`：最终 demo 结果 `demo-final.json`；HMAC 无签名 401 / 正确签名 200 / 同 nonce 重放 409 的原始输出 `hmac-replay.txt`。

本文件不包含凭据、数据库连接串或买家原文。
