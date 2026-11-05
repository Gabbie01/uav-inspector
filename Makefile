.PHONY: help install test lint fmt typecheck demo demo-hallucination verify-examples doctor generate clean

help:
	@echo "uav-inspector 可用命令："
	@echo "  make install            初始化虚拟环境并安装依赖"
	@echo "  make test               跑单元测试（不联网）"
	@echo "  make lint               ruff 静态检查"
	@echo "  make fmt                ruff 自动格式化"
	@echo "  make typecheck          mypy 严格类型检查"
	@echo "  make demo               离线演示：解析样例日志并生成报告（不需要 API Key）"
	@echo "  make demo-hallucination  幻觉闸门演示：注入假幻觉，看代码如何拦截（不需要 API Key）"
	@echo "  make verify-examples    真实报告样例事实校验：逐条回查 docs/examples/（不需要 API Key）"
	@echo "  make doctor             环境自检：检查配置与 API 连通性"
	@echo "  make generate           用真实大模型生成报告（需要 .env 中的 key）"

install:
	uv sync

test:
	uv run pytest

lint:
	uv run ruff check src tests scripts

fmt:
	uv run ruff format src tests scripts
	uv run ruff check --fix src tests scripts

typecheck:
	uv run mypy

demo:
	uv run uav-inspect demo

demo-hallucination:
	uv run python scripts/hallucination_demo.py

verify-examples:
	uv run python scripts/verify_examples.py

doctor:
	uv run uav-inspect doctor

generate:
	uv run uav-inspect generate data/samples/inspection_2026-10-28.log

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache .coverage htmlcov reports
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
