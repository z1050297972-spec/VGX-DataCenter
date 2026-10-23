1. 改动清单

- [pyproject.toml](/home/shawn/桌面/robot-data-platform.wt/m0-01-repo-skeleton-check-chain/pyproject.toml)：追加四类工具的 `[tool.*]` 配置及中文说明。
- [Makefile](/home/shawn/桌面/robot-data-platform.wt/m0-01-repo-skeleton-check-chain/Makefile)：新增 `check`、`fmt`；注明契约检查在派工 B 接入。
- [.githooks/pre-commit](/home/shawn/桌面/robot-data-platform.wt/m0-01-repo-skeleton-check-chain/.githooks/pre-commit)：新增可执行钩子，按 D2 判断规划提交，使用 NUL 分隔及 `--no-renames`。
- [src/rdp/api/__init__.py](/home/shawn/桌面/robot-data-platform.wt/m0-01-repo-skeleton-check-chain/src/rdp/api/__init__.py)：说明 Web 入口层职责和边界。
- [src/rdp/ops/__init__.py](/home/shawn/桌面/robot-data-platform.wt/m0-01-repo-skeleton-check-chain/src/rdp/ops/__init__.py)：说明运维入口层职责和边界。
- [src/rdp/infra/__init__.py](/home/shawn/桌面/robot-data-platform.wt/m0-01-repo-skeleton-check-chain/src/rdp/infra/__init__.py)：说明基础层职责和依赖约束。
- [src/rdp/infra/timeutil.py](/home/shawn/桌面/robot-data-platform.wt/m0-01-repo-skeleton-check-chain/src/rdp/infra/timeutil.py)：新增 `ensure_utc` 的签名、六项契约和桩。
- [scripts/check_contracts.py](/home/shawn/桌面/robot-data-platform.wt/m0-01-repo-skeleton-check-chain/scripts/check_contracts.py)：新增 `check_file`、`main` 的完整契约和桩。
- [tests/test_timeutil.py](/home/shawn/桌面/robot-data-platform.wt/m0-01-repo-skeleton-check-chain/tests/test_timeutil.py)：10 个显式跳过的契约测试。
- [tests/test_check_contracts.py](/home/shawn/桌面/robot-data-platform.wt/m0-01-repo-skeleton-check-chain/tests/test_check_contracts.py)：46 个显式跳过的契约测试。

原有三张配置表及 `uv.lock` 未变；无需修改 `.gitignore`。未暂存、未提交。

2. `make check`

最后一次命令：`make check`，退出码 **0**。`make fmt` 也已通过。

basedpyright 原样输出：

```text
[3/5] basedpyright
.venv/bin/basedpyright
0 errors, 0 warnings, 0 notes
```

末尾输出原样摘录：

```text
SKIPPED [1] tests/test_timeutil.py:43: A2 契约骨架，派工 B 用 TDD 实现
SKIPPED [1] tests/test_timeutil.py:48: A2 契约骨架，派工 B 用 TDD 实现
SKIPPED [1] tests/test_timeutil.py:53: A2 契约骨架，派工 B 用 TDD 实现
============================= 56 skipped in 0.02s ==============================
```

[完整检查输出](/tmp/rdp-a2-final-check.txt)。56 个测试全部按骨架要求跳过，尚未验证函数实现。

运行前 `git status --porcelain --untracked-files=all`：

```text
 M pyproject.toml
?? .githooks/pre-commit
?? Makefile
?? scripts/check_contracts.py
?? src/rdp/api/__init__.py
?? src/rdp/infra/__init__.py
?? src/rdp/infra/timeutil.py
?? src/rdp/ops/__init__.py
?? tests/test_check_contracts.py
?? tests/test_timeutil.py
```

运行后同一命令：

```text
 M pyproject.toml
?? .githooks/pre-commit
?? Makefile
?? scripts/check_contracts.py
?? src/rdp/api/__init__.py
?? src/rdp/infra/__init__.py
?? src/rdp/infra/timeutil.py
?? src/rdp/ops/__init__.py
?? tests/test_check_contracts.py
?? tests/test_timeutil.py
```

两份状态逐字相同。

3. 契约变更申请、依赖申请

无。

4. 拿不准、需要评审决定的地方

无未决歧义。本次骨架将 UTC 换算越界规定为 `OverflowError`，检查脚本的路径处理、问题计数及错误输出规则已写入 docstring，供契约评审核对。

钩子已直接运行通过，也用模拟清单验证了中文路径、改名、删除和失败分支；真实提交验收仍由 Claude 在探针工作目录完成。

5. 检查配置的要点

- **Ruff**：行宽 100，目标 Python 3.12。启用默认 `E4/E7/E9/F`，以及 `B/UP/I/N/PTH/SIM/D/T20/DTZ/S/ERA001`；`E722` 禁止裸 `except`。
- **阈值**：`C901` 圈复杂度 ≤10；`PLR0913` 参数 ≤5；`PLR0915` 语句 ≤40；`PLR0912` 分支 ≤12。
- **豁免检查**：开启 `PGH003/PGH004/RUF100`；basedpyright 开启无规则名及多余豁免报错，关闭 `type: ignore` 的抑制作用。
- **中文兼容**：关闭 `D400/D415`。0.17.1 实测仍拒绝中文句号；保留 `RUF001–003`，添加中文标点白名单，配置后的探针通过。
- **测试放宽**：仅豁免 `S101`（pytest 需要断言）、`D417`（fixture 参数无需重复写 Args）；保留 `D103`。
- **pydoclint**：通过 `explicit-preview-rules` 点名开启 `DOC102/201/402/403/501`；配合 `D417` 核对参数。单行职责文档免于 DOC 检查。
- **未开启的 DOC 规则**：`DOC202` 在 0.17.1 中拒绝无显式返回函数的 `Returns: 无`；`DOC502` 误报 `Raises: 无`，并拒绝记录透传异常。两项均已实测；启用的规则兼容 `NotImplementedError` 骨架。
- **其他工具**：basedpyright 严格模式绑定项目 `.venv`；import-linter 限制入口向下依赖，预留领域层位置，反向依赖探针已被拒绝；pytest 显示跳过原因，不设覆盖率门槛。