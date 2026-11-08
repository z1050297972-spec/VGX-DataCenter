# 直接调用项目环境，避免 PATH 上的 Python/ruff 和 uv 缓存写入影响检查。
.PHONY: check check-web-changed fmt api-types check-api-types web-tools
.DEFAULT_GOAL := check

# package.json 的 scripts 只供本地开发；检查命令只在这里维护，避免两处漂移。
# 直接调用已安装工具，不触发包管理器的联网或 store 写入。
WEB_BIN := src/web/node_modules/.bin

# 生成和过期检查共用命令；只改变输出目录，避免两边的序列化或工具选项漂移。
define generate-api-types
.venv/bin/python -m rdp.api.openapi_export "$(1)/openapi.json" && $(WEB_BIN)/openapi-typescript "$(1)/openapi.json" -o "$(1)/schema.d.ts"
endef

web-tools:
	@test -d src/web/node_modules || { echo "先在 src/web 里运行 pnpm install --frozen-lockfile" >&2; exit 1; }

check:
	@echo "[shell] bash -n 安装、升级与一键部署脚本"
	bash -n scripts/install.sh
	bash -n scripts/upgrade.sh
	bash -n scripts/setup.sh
	@echo "[1/12] ruff format --check"
	.venv/bin/ruff format --check .
	@echo "[2/12] ruff check"
	.venv/bin/ruff check .
	@echo "[3/12] basedpyright"
	.venv/bin/basedpyright
	@echo "[4/12] import-linter"
	.venv/bin/lint-imports --no-cache --no-logo
	@echo "[5/12] 契约检查"
	.venv/bin/python scripts/check_contracts.py src/rdp scripts
	@echo "[6/12] pytest"
	.venv/bin/pytest -n auto --maxprocesses=8
	@$(MAKE) --no-print-directory web-tools
	@echo "[7/12] OpenAPI 过期检查"
	@$(MAKE) --no-print-directory check-api-types
	@echo "[8/12] tsc"
	$(WEB_BIN)/tsc --project src/web/tsconfig.json --noEmit
	@echo "[9/12] ESLint"
	cd src/web && node_modules/.bin/eslint . --max-warnings 0
	@echo "[10/12] Prettier"
	cd src/web && node_modules/.bin/prettier --check .
	@echo "[11/12] stylelint"
	cd src/web && node_modules/.bin/stylelint "src/**/*.css"
	@echo "[12/12] Vitest"
	cd src/web && node_modules/.bin/vitest run

# 提交时的分层检查（2026-11-08 负责人同意）：只改了前端时用这个，不跑后端。
# WEB_CHANGED 是相对 src/web 的改动文件；为空或含配置文件时退回全量 Vitest。
# 合并提交和其他改动仍由钩子跑完整 make check。
check-web-changed: web-tools
	@echo "[web 1/5] tsc"
	$(WEB_BIN)/tsc --project src/web/tsconfig.json --noEmit
	@echo "[web 2/5] ESLint"
	cd src/web && node_modules/.bin/eslint . --max-warnings 0
	@echo "[web 3/5] Prettier"
	cd src/web && node_modules/.bin/prettier --check .
	@echo "[web 4/5] stylelint"
	cd src/web && node_modules/.bin/stylelint "src/**/*.css"
	@echo "[web 5/5] Vitest（只跑受改动影响的测试）"
	cd src/web && if [ -n "$(WEB_CHANGED)" ]; then node_modules/.bin/vitest related --run $(WEB_CHANGED); else node_modules/.bin/vitest run; fi

fmt:
	.venv/bin/ruff format .
	.venv/bin/ruff check --fix .
	@$(MAKE) --no-print-directory web-tools
	cd src/web && node_modules/.bin/eslint . --fix
	cd src/web && node_modules/.bin/prettier --write .

api-types: web-tools
	$(call generate-api-types,src/web/src/api)

check-api-types: web-tools
	@set -eu; \
	api_dir=$$(mktemp -d); \
	trap 'rm -rf "$$api_dir"' EXIT HUP INT TERM; \
	$(call generate-api-types,$$api_dir); \
	if ! cmp -s "$$api_dir/openapi.json" src/web/src/api/openapi.json || \
	   ! cmp -s "$$api_dir/schema.d.ts" src/web/src/api/schema.d.ts; then \
		echo "OpenAPI 或生成类型已过期，请运行 make api-types" >&2; exit 1; \
	fi; \
	echo "OpenAPI 与生成类型均未过期"
