# Sentinel 动态规则（ADR-0009）

代码注册的规则仅是兜底默认；配置以下 data-id 后由 Nacos 热更（`scripts/nacos_config_push.py` 推送）：

- `smartlect-sentinel-dubbo-rules.json`：Dubbo 熔断规则（DegradeRule JSON 数组），开启方式：
  配置 `smartlect.sentinel.dubbo-rules-data-id`。
- `smartlect-sentinel-gateway-rules.json`：网关流控规则（GatewayFlowRule JSON 数组），开启方式：
  配置 `smartlect.sentinel.gateway-rules-data-id`。

示例字段见同目录两个 json。回滚：删除 data-id 配置项并重启，即回退代码兜底规则。
