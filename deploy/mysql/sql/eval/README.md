# eval profile（只读说明）

本目录是 eval profile 的初始化目录，**只允许放 schema/配置/规则迁移，禁止任何候选供给**。

- 禁止：`INSERT/UPDATE/REPLACE member_profile|roommate_preference`（包括“补流动性”“克隆候选”）。
- `eval/check_freeze.py` 会在 CI 扫描本目录，发现成员供给写语句直接失败。
- 需要新的评测供给？先改评测协议，用独立的“市场池”生成，并升级 MANIFEST；不得按申请人定制。
