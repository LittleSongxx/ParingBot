# 业务库：MySQL。本项目全部结构化数据都在这一个库里：用户、租客、匹配、
# Agent 过程记录，没有第二个数据库。
TORTOISE_ORM = {
    "connections": {
        "default": {
            "engine": "tortoise.backends.mysql",
            "credentials": {
                "host": "localhost",
                "port": 3306,
                # 数据库名称，和 ai_coliving.sql 里建的库同名
                "database": "ai_coliving",
                "user": "root",
                # 数据库密码，按本机 MySQL 实际密码改
                "password": "123456",
                "minsize": 1,
                "maxsize": 10,
                "charset": "utf8mb4",
                "echo": True
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

JWT_SECRET = "ai-coliving-match-platform-jwt-secret"
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24
