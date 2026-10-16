# Smartlect 工程入口。旧 eval-harness 线（app/frontend/eval harness）已于 2026-10-04 退役，
# 原 4 个 harness 目标随之移除；完整本地流程见 scripts/dev.sh 与 README「快速开始」。

.PHONY: help build check test-backend test-assistant test-web \
        infra-up up down status demo seed-store reset-demo

help:
	@echo "Smartlect make 目标："
	@echo "  build        后端打包 + assistant venv 就绪 + 双前端构建（scripts/dev.sh build）"
	@echo "  check        全量自检：独立性检查 + runtime 自测 + backend/assistant/web 测试"
	@echo "  test-backend 仅后端  mvn -f backend/pom.xml test"
	@echo "  test-assistant 仅 assistant（先重装本包再跑 unittest，防止测到旧源码）"
	@echo "  test-web     仅前端  web/user 与 web/admin vitest"
	@echo "  infra-up/up/down/status  本地基础设施编排（scripts/runtime.py）"
	@echo "  demo/seed-store/reset-demo  演示链路（scripts/dev.sh 子命令）"
	@echo "质量评测（quality-v2/support-eval）不经 make：见 evals/ 与 scripts/eval_quality_v2.py。"

build:
	./scripts/dev.sh build

check:
	./scripts/dev.sh check

test-backend:
	mvn -B -f backend/pom.xml test

test-assistant:
	assistant/.venv/bin/python -m pip install --no-index --no-deps --no-build-isolation ./assistant
	assistant/.venv/bin/python -m unittest discover -s assistant/tests

test-web:
	npm --prefix web/user run test
	npm --prefix web/admin run test

infra-up:
	./scripts/dev.sh infra-up

up:
	./scripts/dev.sh up

down:
	./scripts/dev.sh down

status:
	./scripts/dev.sh status

demo:
	./scripts/dev.sh demo

seed-store:
	./scripts/dev.sh seed-store

reset-demo:
	./scripts/dev.sh reset-demo
