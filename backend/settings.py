"""应用配置。

所有可变的配置都从环境变量读取，默认值只保证「本机开发能跑起来」；
部署时用仓库根目录或 backend/ 下的 .env 覆盖，不需要改代码。

.env 的解析只认 KEY=VALUE，不新增依赖；读取顺序是仓库根 .env 在前、
backend/.env 在后，且已存在的环境变量优先，这样容器里通过 environment /
env_file 注入的值不会被仓库里的 .env 盖掉。
"""

import os

# settings.py 在 backend/ 目录下，仓库根目录是它的上一级
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_BACKEND_DIR)
# 先读仓库根 .env，再读 backend/.env；同一个键以先读到的为准
_ENV_FILES = (
    os.path.join(_REPO_ROOT, ".env"),
    os.path.join(_BACKEND_DIR, ".env"),
)


def _load_env() -> None:
    """把 .env 里的 KEY=VALUE 读进 os.environ，已经存在的变量不覆盖。

    格式故意写得很宽松：允许空行和 # 注释、允许值带成对引号，
    不认识的写法直接跳过。它只是给本机开发和容器启动补默认值用的，
    真正的配置来源仍然是环境变量本身。
    """
    for env_path in _ENV_FILES:
        if not os.path.isfile(env_path):
            continue
        try:
            with open(env_path, "r", encoding="utf-8") as handle:
                lines = handle.readlines()
        except OSError:
            # .env 读不了不影响启动，继续用默认值和已有环境变量
            continue
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            # 去掉值两边成对的引号，和常见的 .env 写法保持一致
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            if key:
                os.environ.setdefault(key, value)


def _env_str(name: str, default: str) -> str:
    """取字符串配置。环境变量存在时就用它，哪怕是空字符串。"""
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    """取整数配置。填了非法内容时退回默认值，不让应用因为一个笔误起不来。"""
    try:
        return int(str(os.environ.get(name, default)).strip())
    except (TypeError, ValueError):
        return default


_load_env()

# ---------- 数据库 ----------
# 业务库：MySQL。本项目全部结构化数据都在这一个库里：用户、租客、匹配、
# Agent 过程记录，没有第二个数据库。
DB_HOST = _env_str("DB_HOST", "localhost")
DB_PORT = _env_int("DB_PORT", 3306)
DB_NAME = _env_str("DB_NAME", "smartlect")
DB_USER = _env_str("DB_USER", "root")
DB_PASSWORD = _env_str("DB_PASSWORD", "123456")

TORTOISE_ORM = {
    "connections": {
        "default": {
            "engine": "tortoise.backends.mysql",
            "credentials": {
                "host": DB_HOST,
                "port": DB_PORT,
                # 数据库名称，和 smartlect.sql 里建的库同名
                "database": DB_NAME,
                "user": DB_USER,
                # 数据库密码，按本机 MySQL 实际密码改；线上用环境变量覆盖
                "password": DB_PASSWORD,
                "minsize": 1,
                "maxsize": 10,
                "charset": "utf8mb4",
                # 默认关掉 SQL 日志：容器里每条查询一行会把有效日志淹掉；
                # 本机排障时用 DB_ECHO=true 打开
                "echo": _env_str("DB_ECHO", "false").strip().lower() in ("1", "true", "yes", "on")
            }
        },
    },
    "apps": {
      "models": {
          # 指向 models 包，Tortoise 会扫描包里导出的所有 Model 子类
          "models": ["models"],
          "default_connection": "default",
      }
    },
    # use_tz 必须关掉。开着时 ORM 自动写入的时间取的是 UTC 时刻，
    # 而下面 timezone 配的是东八区，两边差 8 小时，页面上看到的创建时间
    # 会比实际早八个钟头。关掉之后 ORM 与 common/times.now() 都按东八区走，
    # 写进去和读出来是同一个时刻
    "use_tz": False,
    "timezone": "Asia/Shanghai"
}

# ---------- 登录态 ----------
# 默认值只能用于本机开发。部署时必须在 .env 里换成随机密钥，
# 否则任何人都能按这个公开默认值伪造 token
JWT_SECRET = _env_str("JWT_SECRET", "dev-only-change-me")
JWT_ALGORITHM = _env_str("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_HOURS = _env_int("JWT_EXPIRE_HOURS", 24)

# ---------- 跨域 ----------
# 逗号分隔的允许来源，覆盖本机前端（5173 端口）的两种写法
CORS_ORIGINS = _env_str(
    "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
# CORSMiddleware 只认列表，这里把逗号分隔的配置解析开
CORS_ORIGIN_LIST = [origin.strip() for origin in CORS_ORIGINS.split(",") if origin.strip()]

# ---------- 文件上传 ----------
# 文件访问地址前缀。空字符串表示返回相对地址，页面跟着当前域名走，
# 换域名 / 端口时不需要重新上传已有的图片
PUBLIC_BASE_URL = _env_str("PUBLIC_BASE_URL", "http://localhost:9090")
# 上传的文件统一放在 backend/files 目录下
UPLOAD_DIR = _env_str("UPLOAD_DIR", "files")
# 单个上传文件的大小上限，单位 MB
MAX_UPLOAD_MB = _env_int("MAX_UPLOAD_MB", 5)

# ---------- 智能匹配 ----------
# 一次匹配运行的超时时间，超时后运行标记为中断，页面可以重新发起
MATCH_TIMEOUT_SECONDS = _env_int("MATCH_TIMEOUT_SECONDS", 600)

# ---------- 启动 ----------
HOST = _env_str("HOST", "localhost")
PORT = _env_int("PORT", 9090)