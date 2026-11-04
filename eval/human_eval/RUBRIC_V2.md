# Rubric v2（可判定项 + 确定性汇总）

> v2.1（2026-11-04 修订）：明确 store_id 判定、data 矛盾上限；v2 首轮 5 评者 overall κ=0.832，但 commute 一致率仅 0.662，见 `analysis/deep-review/proxy-eval/v2/README.md`。

> 目标：把 v1 的“主观 1–5”改成**逐项可判定**，让不同评者（人/LLM/异族模型）更容易一致。
> 输出 checklist，`overall` 由规则计算，评者不直接拍总分。

## 逐项判定

| 字段 | 取值 | 判定规则 |
|---|---|---|
| `hard_gate` | 0/1 | 1 当且仅当：同性；申请方满足候选方全部「必须」项；候选方满足申请方全部「必须」项；计划租期档差 <2。任一不满足=0。 |
| `lifestyle_conflicts` | 数组，元素 ∈ {schedule, smoking, pet, tidiness} | schedule：夜猫子 vs 早睡早起/正常作息；smoking：经常吸烟 vs 不吸烟；pet：一方养宠/过敏且另一方不接受；tidiness：双方整洁度相差 ≥2 档。可多选。 |
| `commute` | 0/1/2 | 有 `store_id` 时：2=同 store_id；1=同片区但不同 store；0=跨片区/异地。缺 `store_id` 时：1=同片区，0=跨片区；**不得把“同片区”当同门店**。 |
| `lease_stability` | 0/1/2 | 2=租期档位相同；1=相邻一档；0=相差 ≥2 档。 |
| `data_consistency` | 0/1/2 | 2=资料完整自洽；1=轻微缺失/含糊；0=明显矛盾（如兴趣含养猫但 `has_pet=无` 且声明宠物过敏/不接受宠物）。 |
| `boundary` | 0/1/2 | 2=无隐私/越权/承诺问题；1=轻微；0=出现隐私泄露、越权、承诺性措辞。 |
| `reason` | 字符串 | ≤40 字，指出最关键判定依据。 |

## overall 计算规则（评者必须按规则算，不许直接拍）

```text
if hard_gate == 0: overall = 1
elif len(lifestyle_conflicts) >= 2: overall = 2
elif len(lifestyle_conflicts) == 1: overall = 3
else:
    bonus = (1 if commute == 2 else 0) + (1 if lease_stability == 2 else 0) \
          + (1 if data_consistency == 2 else 0) + (1 if boundary == 2 else 0)
    overall = 5 if bonus >= 3 else 4
    if data_consistency == 0: overall = min(overall, 3)   # v2.1：资料自相矛盾不得给高分
```

## 输出 JSON

```json
{"pair_id":"P01","hard_gate":1,"lifestyle_conflicts":[],
 "commute":2,"lease_stability":2,"data_consistency":1,"boundary":2,
 "overall":4,"reason":"同店同租期无冲突；兴趣标签与宠物字段轻微矛盾"}
```

> 盲评材料必须包含 `store_id`（否则无法判断“同门店”）；这是 v2 首轮 P04 分歧的原因。

## 与 v1 的差异

- v1：hard/fit/evidence/boundary/overall 全部 1–5 主观打分；
- v2：除 `overall` 外均为可核对项，`overall` 由规则推导；便于算 item-level κ 与定位分歧来源。
- v2 仍是代理评审（E2.5），不是人工真值；人工盲评仍按 `PROTOCOL.md`。
