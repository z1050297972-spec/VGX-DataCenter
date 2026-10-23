# 直接调用项目环境，避免 PATH 上的 Python/ruff 和 uv 缓存写入影响检查。
.PHONY: check fmt

check:
	@echo "[1/6] ruff format --check"
	.venv/bin/ruff format --check .
	@echo "[2/6] ruff check"
	.venv/bin/ruff check .
	@echo "[3/6] basedpyright"
	.venv/bin/basedpyright
	@echo "[4/6] import-linter"
	.venv/bin/lint-imports --no-cache --no-logo
	@echo "[5/6] 契约检查"
	.venv/bin/python scripts/check_contracts.py src/rdp scripts
	@echo "[6/6] pytest"
	.venv/bin/pytest

fmt:
	.venv/bin/ruff format .
	.venv/bin/ruff check --fix .
