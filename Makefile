# 直接调用项目环境，避免 PATH 上的 Python/ruff 和 uv 缓存写入影响检查。
.PHONY: check fmt api-types web-tools
.DEFAULT_GOAL := check

# package.json 的 scripts 只供本地开发；检查命令只在这里维护，避免两处漂移。
# 直接调用已安装工具，不触发包管理器的联网或 store 写入。
WEB_BIN := src/web/node_modules/.bin

web-tools:
	@test -d src/web/node_modules || { echo "先在 src/web 里运行 pnpm install --frozen-lockfile" >&2; exit 1; }

check:
	@echo "[1/11] ruff format --check"
	.venv/bin/ruff format --check .
	@echo "[2/11] ruff check"
	.venv/bin/ruff check .
	@echo "[3/11] basedpyright"
	.venv/bin/basedpyright
	@echo "[4/11] import-linter"
	.venv/bin/lint-imports --no-cache --no-logo
	@echo "[5/11] 契约检查"
	.venv/bin/python scripts/check_contracts.py src/rdp scripts
	@echo "[6/11] pytest"
	.venv/bin/pytest
	@$(MAKE) --no-print-directory web-tools
	# A2 的导出函数是契约桩；派工 B 在此接入 [7/11] OpenAPI 过期检查。
	# B 将导出与生成结果写入临时目录并逐字节比较，不改入库文件。
	@echo "[8/11] tsc"
	$(WEB_BIN)/tsc --project src/web/tsconfig.json --noEmit
	@echo "[9/11] ESLint"
	cd src/web && node_modules/.bin/eslint . --max-warnings 0
	@echo "[10/11] Prettier"
	cd src/web && node_modules/.bin/prettier --check .
	@echo "[11/11] Vitest"
	cd src/web && node_modules/.bin/vitest run

fmt:
	.venv/bin/ruff format .
	.venv/bin/ruff check --fix .
	@$(MAKE) --no-print-directory web-tools
	cd src/web && node_modules/.bin/eslint . --fix
	cd src/web && node_modules/.bin/prettier --write .

api-types: web-tools
	.venv/bin/python -m rdp.api.openapi_export src/web/src/api/openapi.json
	$(WEB_BIN)/openapi-typescript src/web/src/api/openapi.json -o src/web/src/api/schema.d.ts
