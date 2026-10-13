# 与 /deploy/elasticsearch/Dockerfile 保持一致（IK 分词，社区构建源）。
# 该副本当前未被 compose 引用，仅留作 backend 独立构建入口。
FROM docker.elastic.co/elasticsearch/elasticsearch:8.19.0
RUN elasticsearch-plugin install --batch \
    https://get.infini.cloud/elasticsearch/analysis-ik/8.19.0
