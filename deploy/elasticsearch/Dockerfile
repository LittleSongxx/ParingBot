# IK 分词插件不随官方镜像分发（社区构建源 get.infini.cloud，与 ES 8.19.0 严格同版）；
# 随镜像预装，索引 analyzer 才能生效。IK 相比 smartcn 支持自定义词典与热更新，
# 是国内电商搜索的主流选择。
FROM docker.elastic.co/elasticsearch/elasticsearch:8.19.0
RUN elasticsearch-plugin install --batch \
    https://get.infini.cloud/elasticsearch/analysis-ik/8.19.0
