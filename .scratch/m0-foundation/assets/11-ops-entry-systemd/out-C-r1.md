**1. 本轮改动清单**

- `scripts/setup.sh`：重复运行改用合法状态参数；正确处理 0/3；默认模式报告两个单元状态。
- `scripts/install.sh`：按指令分别转义；`WorkingDirectory` 不加引号，仅将 `%` 写成 `%%`。
- `scripts/systemd/rdp-web.service`：移除 `WorkingDirectory` 外层引号。
- `scripts/systemd/rdp-worker.service`：移除 `WorkingDirectory` 外层引号。
- `tests/setup_support.py`：假命令接入真实参数解析规则，移除裸 `status` 支持。
- `tests/test_ops_setup_script.py`：补充重复运行、状态码、参数一致性及升级命令测试。
- `tests/test_ops_deploy_scripts.py`：修正错误断言；新增安装/升级 × 三种路径的真实 systemd 校验。

未暂存、未提交，临时检查日志已删除。

**2. `make check`**

本轮仅运行一次，退出码 0：**pytest 2055 passed / 0 skipped；Vitest 250 passed / 0 skipped**。

```bash
make check > /tmp/rdp-setup-review1-check.log 2>&1
```

末尾输出，从 pytest 汇总起原样：

```text
================= 2055 passed, 1 warning in 275.52s (0:04:35) ==================
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.oy3qE0GPfS/openapi.json → /tmp/tmp.oy3qE0GPfS/schema.d.ts [69.6ms]
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
   Start at  21:01:11
   Duration  7.55s (tests 49%, environment 29%, import 20%, transform 1%)
```

运行前 `git status --porcelain --untracked-files=all`：

```text
 M scripts/install.sh
 M scripts/setup.sh
 M scripts/systemd/rdp-web.service
 M scripts/systemd/rdp-worker.service
 M src/rdp/ops/setup_queries.py
 M tests/test_ops_deploy_scripts.py
 M tests/test_ops_setup_queries.py
 M tests/test_ops_setup_script.py
?? tests/setup_support.py
```

运行后：

```text
 M scripts/install.sh
 M scripts/setup.sh
 M scripts/systemd/rdp-web.service
 M scripts/systemd/rdp-worker.service
 M src/rdp/ops/setup_queries.py
 M tests/test_ops_deploy_scripts.py
 M tests/test_ops_setup_queries.py
 M tests/test_ops_setup_script.py
?? tests/setup_support.py
```

状态包含上一轮保留的改动。

**3. 契约变更申请、依赖申请**

无。未改公开签名、Python docstring 或帮助文本。

补充脚本注释，说明：

- 状态码 3 是正常状态信息，其余非零码仍按检查失败处理。
- `WorkingDirectory` 按整行读取；`ExecStart`、`Environment` 使用双引号值的转义规则。

**4. 拿不准的地方**

无待决事项。

本机 `systemd-analyze` 259 可运行；六项校验使用 `--user verify --man=no --generators=no`，没有连接用户总线或启动服务。

`upgrade.sh` 共用修复后的渲染函数，升级路径已验证，无需修改该文件。`Environment` 现有引号、反斜线、百分号及字面 `$` 处理保留，通过了真实解析校验。

**5. 本轮先红后绿**

以下红项最终均通过；初绿项注明原因。

- `test_repeat_arguments_match_real_cli`：红，真实解析器拒绝裸 `status`，抛出 `SystemExit(2)`。
- `test_repeat_reports_read_only_states[0-0-0-False]`：红，缺少单元状态查询。
- `test_repeat_reports_read_only_states[3-3-3-False]`：红，缺少单元状态查询。
- `test_repeat_reports_read_only_states[0-3-0-True]`：初绿，前一步已支持 0/3，且前台模式不调用 systemd。
- `test_fake_entrypoints_enforce_real_argument_contracts`：红，假安装入口遇未知参数返回 1，未遵循真实解析器的退出码 2。
- `test_rendered_units_pass_systemd_verify[install-plain]`：红，带引号的工作目录被判定为非绝对路径。
- `test_rendered_units_pass_systemd_verify[install-部署 空格]`：红，同上。
- `test_rendered_units_pass_systemd_verify[install-部署%目录]`：红，同上。
- `test_rendered_units_pass_systemd_verify[upgrade-plain]`：红，同上。
- `test_rendered_units_pass_systemd_verify[upgrade-部署 空格]`：红，同上。
- `test_rendered_units_pass_systemd_verify[upgrade-部署%目录]`：红，同上。
- `test_literal_dollar_in_exec_start`：红，修正断言后发现工作目录仍带引号。
- `test_install_custom_paths`：红，工作目录错误套用了双引号值的转义。
- `test_repeat_does_not_hide_status_errors[failure0]`：初绿，worker 返回 1 已被失败边界捕获。
- `test_repeat_does_not_hide_status_errors[failure1]`：初绿，worker 返回 2 已被失败边界捕获。
- `test_repeat_does_not_hide_status_errors[failure2]`：初绿，作业查询返回 1 已被失败边界捕获。
- `test_repeat_does_not_hide_status_errors[failure3]`：初绿，systemd 查询返回 1 已被失败边界捕获。
- `test_repeat_does_not_hide_status_errors[failure4]`：初绿，systemd 查询返回 4 已被失败边界捕获。
- `test_printed_upgrade_command_matches_script_parser`：初绿，原打印命令的参数已符合真实升级脚本。