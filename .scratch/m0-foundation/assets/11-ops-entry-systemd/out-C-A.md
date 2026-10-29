**1. 改动清单**

本轮仅交契约骨架，未运行部署脚本、联网或安装工具；未暂存、未提交。

- [scripts/setup.sh](/home/shawn/桌面/robot-data-platform.wt/m0-11-ops-entry-systemd/scripts/setup.sh)：完整帮助文案置于 `usage` 前注释；24 个阶段函数均只有 `exit 78`。
- [src/rdp/ops/setup_queries.py](/home/shawn/桌面/robot-data-platform.wt/m0-11-ops-entry-systemd/src/rdp/ops/setup_queries.py)：配置校验、管理员存在性、挂载候选、访问地址及查询入口契约；6 个函数均为六项 docstring 加 `NotImplementedError`。
- [tests/test_ops_setup_script.py](/home/shawn/桌面/robot-data-platform.wt/m0-11-ops-entry-systemd/tests/test_ops_setup_script.py)：46 项脚本测试清单，全部跳过。
- [tests/test_ops_setup_queries.py](/home/shawn/桌面/robot-data-platform.wt/m0-11-ops-entry-systemd/tests/test_ops_setup_queries.py)：19 项只读查询测试清单，全部跳过。
- [Makefile](/home/shawn/桌面/robot-data-platform.wt/m0-11-ops-entry-systemd/Makefile)：仅增加新脚本的 `bash -n` 检查。

**2. `make check`**

退出码 **0**。末尾原样输出：

```text
=========== 1967 passed, 65 skipped, 1 warning in 147.26s (0:02:27) ============
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.sZLG0y6Ygw/openapi.json → /tmp/tmp.sZLG0y6Ygw/schema.d.ts [70.5ms]
OpenAPI 与生成类型均未过期
[8/11] tsc
src/web/node_modules/.bin/tsc --project src/web/tsconfig.json --noEmit
[9/11] ESLint
cd src/web && node_modules/.bin/eslint . --max-warnings 0
[10/11] Prettier
cd src/web && node_modules/.bin/prettier --check .
Checking formatting...
All matched files use Prettier code style!
[11/11] Vitest
cd src/web && node_modules/.bin/vitest run

 RUN  v5.0.5 /home/shawn/桌面/robot-data-platform.wt/m0-11-ops-entry-systemd/src/web


 Test Files  22 passed (22)
      Tests  250 passed (250)
   Start at  18:48:24
   Duration  7.46s (tests 49%, environment 30%, import 21%)
```

65 项跳过均为本轮新增契约清单。

**3. 契约变更申请、依赖申请**

均为 **无**。

没有修改 `install.sh`、既有 `rdp` 命令或配置模型，也没有新增 Python/JS 依赖。

**4. 设计选择与待核实事项**

- **配置校验**：导出目标提交，使用隔离的临时 `uv sync --frozen --no-dev` 环境执行平台校验。避免改动源仓库 `.venv`，也无需扩展 `install.sh`。目标提交必须包含新增查询入口。
- **工具安装**：固定 uv `0.13.5`、Node `22.23.2`、pnpm `11.22.0`；选择 pnpm 官方独立二进制。先准备 Node，再用其内置 JSON 解析官方发行元数据，不引入 jq 或提前要求 Python。
- **SHA256**：Node 使用同源 `SHASUMS256.txt`；uv/pnpm 使用官方 GitHub release metadata 的 SHA256 digest。摘要缺失或不合法即停止，不跳过校验。
- **`--no-systemd`**：建议由 setup 在前台监管两个服务，健康检查后持续运行；不留下脱离终端的后台进程。原 `install.sh --no-systemd` 行为不变。
- **非交互管理员**：新增显式 `--skip-admin`，延后创建并打印命令；默认仍要求安全终端交互，不新增口令参数或环境变量。
- **待执行线联网核实**：固定发行包及 GitHub asset digest 的实际可用性。本轮按限制未验证网络资源；验收 9 应覆盖，不能因缺摘要而放宽校验。

**需负责人另行决定：无。** 上述选择供执行线按最后一条 Comment 的预批流程复核记录。