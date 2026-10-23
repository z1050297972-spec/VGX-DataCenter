# 直接调用项目环境，避免 PATH 上的 Python/ruff 和 uv 缓存写入影响检查。
.PHONY: check fmt

check:
	@echo "[1/5] ruff format --check"
	.venv/bin/ruff format --check .
	@echo "[2/5] ruff check"
	.venv/bin/ruff check .
	@echo "[3/5] basedpyright"
	.venv/bin/basedpyright
	@echo "[4/5] import-linter"
	.venv/bin/lint-imports --no-cache --no-logo
# 派工 A2 的契约检查脚本只有桩；派工 B 实现后，在 import-linter 与 pytest 之间接上。
	@echo "[5/5] pytest"
	.venv/bin/pytest

fmt:
	.venv/bin/ruff format .
	.venv/bin/ruff check --fix .
