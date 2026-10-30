# ParingBot 运维手册

## 1. 环境要求

- Docker Desktop（含 Compose v2）。Windows 下 WSL2 后端即可。
- 端口：默认只把 `127.0.0.1:8080` 暴露给宿主；MySQL 与后端只在 compose 内网。
- 需要联网拉取镜像/依赖；LLM API Key 不随仓库分发。

## 2. 首次部署

```bash
cp .env.example .env          # 按需修改数据库口令与 JWT_SECRET
docker compose up -d --build  # 首次构建约 5-15 分钟（langchain 依赖较大）
docker compose ps             # 三个服务 healthy 后访问
```

Windows + WSL 若在 WSL 内执行且 `docker` 默认上下文报错，使用：

```bash
DOCKER_CONTEXT=default docker compose up -d --build
```

访问 <http://127.0.0.1:8080>，演示账号：

| 身份 | 账号 | 密码 |
|---|---|---|
| 管理员 | `admin` | `admin123` |
| 租客 | `member01` | `123456` |

## 3. 配置项（.env）

| 变量 | 默认 | 说明 |
|---|---|---|
| `MYSQL_ROOT_PASSWORD` | 无 | MySQL root 口令，必须设置 |
| `MYSQL_DATABASE` | `paringbot` | 业务库名，首次初始化时建库 |
| `MYSQL_USER` / `MYSQL_PASSWORD` | `paringbot` / 无 | 应用账号（由镜像自动授权） |
| `JWT_SECRET` | 无 | JWT 签名密钥，务必改为随机值 |
| `APP_PORT` | `8080` | 对外端口（只绑定 127.0.0.1） |
| `PUBLIC_BASE_URL` | 空 | 文件地址前缀；空表示返回相对路径（推荐） |
| `MATCH_TIMEOUT_SECONDS` | `600` | 单次匹配运行超时 |
| `MAX_UPLOAD_MB` | `5` | 上传文件大小上限 |
| `TZ` | `Asia/Shanghai` | 容器时区 |

生成随机口令：`openssl rand -hex 24`。

## 4. 配置模型 API Key

种子配置的 `api_key` 为空，**不填无法发起真实匹配**（前置检查会给出提示）：

1. 管理员登录 → 【AI 模型配置】；
2. 给「调度」用途填 API Key（画像/筛选/审核三条同理，可共用同一 Key）；
3. 点「测试连接」确认可用，保存后下一步调用即生效（配置每次执行现查，无需重启）。

当前实现通过 OpenAI 兼容接口调用，默认 `base_url=https://api.deepseek.com/v1`、模型 `deepseek-chat`，可在页面修改。

## 5. 验证部署

```bash
docker compose ps
docker compose logs --tail=100 backend
python scripts/smoke_check.py --base http://127.0.0.1:8080
docker compose exec -T backend pytest -q     # 266+ 用例，使用真实 MySQL + FakeModel
docker compose exec -T backend python -c "import main; print('import ok')"
```

## 6. 数据与备份

```bash
# 备份
docker compose exec -T mysql sh -c 'mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" paringbot' > backup.sql
# 恢复（覆盖当前库）
docker compose exec -T mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" paringbot' < backup.sql
```

数据卷：`paringbot_mysql_data`（数据库）、`paringbot_uploads`（上传文件）。
重建空库：`docker compose down -v && docker compose up -d --build`（会删除以上两个卷）。

## 7. 本地开发模式（不用 Docker）

```bash
# 数据库：本机 MySQL 8，建库 paringbot 并导入 deploy/mysql/init/*.sql
cd backend
python -m venv .venv && . .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py                                   # 读取仓库根 .env，监听 9090

cd frontend
npm install
npm run dev                                      # 5173，代理到 http://localhost:9090

# 本地开发时根 .env 的 PUBLIC_BASE_URL 为空会让上传地址变成相对路径，
# 需要临时指定：PUBLIC_BASE_URL=http://localhost:9090（或在 backend/.env 里设置）
```

## 8. 常见问题

| 现象 | 处理 |
|---|---|
| WSL 内 `docker` 报上下文错误 | 命令前加 `DOCKER_CONTEXT=default` |
| 端口 8080 被占用 | 改 `.env` 的 `APP_PORT` 后 `docker compose up -d` |
| 后端启动时数据库连不上 | 等 mysql healthy；`docker compose logs mysql` 查看初始化是否报错 |
| 页面能开但接口全 404 | 确认 nginx 容器已启动（`docker compose ps`），反代 `/api/` 到 `backend:9090/` |
| 上传成功但图片不显示 | 确认 `PUBLIC_BASE_URL` 为空且 nginx 有 `/files/` 转发；或直接访问 `/files/download/<文件名>` |
| 发起匹配提示模型未配置 | 见第 4 节，给四个用途各启用一条带 Key 的模型配置 |
| 历史运行记录与当前口径不一致 | 种子库保留了修复前产生的历史运行记录，新运行走修复后逻辑；历史不追溯 |

## 9. 停止与清理

```bash
docker compose stop          # 停止但保留数据
docker compose down          # 停止并删容器/网络，保留数据卷
docker compose down -v       # 连同数据卷一起删除（不可恢复）
```

## 安全与鉴权行为

| 行为 | 说明 |
|---|---|
| 登录失败 | 账号或 IP 维度 10 次失败 / 5 分钟触发锁定（默认 5 分钟），锁定期间正确密码也拒绝；可通过环境变量调整 |
| 账号枚举 | 未注册、密码错误、账号停用统一返回「账号或密码错误」；未知账号用等价 PBKDF2 计算对齐耗时 |
| Token 失效 | JWT 内带密码指纹：改密码后旧 token 立即失效；账号停用/删除同样失效 |
| 上传 | 除扩展名外校验文件头魔数（png/jpg/jpeg/gif/webp），HTML 改名图片会被拒绝；单文件 ≤5 MB |
| 分页 | 服务端统一限幅：page_num ≥ 1、page_size ≤ 100，负数/超大值会被规整而不是报 500 |
| 响应头 | nginx 统一加 `X-Content-Type-Options: nosniff`、`X-Frame-Options: SAMEORIGIN`、`Referrer-Policy` |
| 文件访问 | `/files/download/{文件名}` 仅放行合法文件路径；其它 `/files/*` 返回 404，不再落到 SPA 首页 |
| 级联删除 | 删除账号时档案/偏好/动态/画像/匹配记录在同一事务内删除，文件清理在事务之后 |
