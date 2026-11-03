FROM mysql:8.0.40

# 初始化 profile：demo = base + demo 演示供给；eval = base only（禁止任何候选供给）
ARG INIT_PROFILE=demo
COPY sql/base/ /seed/base/
COPY sql/${INIT_PROFILE}/ /seed/profile/

# MySQL 官方入口只执行 /docker-entrypoint-initdb.d 下的平铺文件，这里按 profile 摊平
RUN mkdir -p /docker-entrypoint-initdb.d \
 && cp /seed/base/*.sql /docker-entrypoint-initdb.d/ \
 && { cp /seed/profile/*.sql /docker-entrypoint-initdb.d/ 2>/dev/null || true; }
