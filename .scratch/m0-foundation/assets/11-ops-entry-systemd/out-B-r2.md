**1. 改动清单**

- [src/rdp/cli.py](/home/shawn/桌面/robot-data-platform.wt/m0-11-ops-entry-systemd/src/rdp/cli.py)：生产运行器改用应用自有的 `Server` 子类，保留 uvicorn 优雅关闭和处理器恢复，取消关闭后的信号重抛。
- [tests/test_ops_process_signals.py](/home/shawn/桌面/robot-data-platform.wt/m0-11-ops-entry-systemd/tests/test_ops_process_signals.py)：新增真实 Web/worker 子进程停止测试及信号处理器恢复测试。临时 HOME、临时端口；启动/停止各限 10 秒，超时 kill 后限时回收。

未修改 uvicorn 包，未添加依赖，未暂存或提交；临时文件已清理。

**2. `make check`**

本轮运行一次，退出码 **0**。pytest **1958 passed / 0 skipped**；Vitest **250 passed / 0 skipped**。

```bash
make check > /tmp/rdp-r2-check.Qfg2X6/check.log 2>&1
```

末尾原样输出：

```text
================= 1958 passed, 1 warning in 147.28s (0:02:27) ==================
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.FzYLAPWKI1/openapi.json → /tmp/tmp.FzYLAPWKI1/schema.d.ts [72.2ms]
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
   Start at  12:06:54
   Duration  7.43s (tests 49%, environment 29%, import 21%)
```

运行前 `git status --porcelain --untracked-files=all`：

```text
 M src/rdp/cli.py
?? tests/test_ops_process_signals.py
```

运行后：

```text
 M src/rdp/cli.py
?? tests/test_ops_process_signals.py
```

**3. 契约补充/docstring 改动**

签名、类型和退出码契约未改。

- `run_web.Args.runner` 改称“生产 uvicorn 适配器或测试替身”。
- `run_web.Side Effects` 补充：已处理的 SIGTERM/SIGINT 正常返回，使 `start_web` 完成报错排空、引擎释放和结束日志。
- 私有运行器注释说明 uvicorn 0.54 重抛信号的问题及适配理由。

**4. 拿不准的地方**

无待决项。正常 SIGTERM、SIGINT 均返回 **0**，无需为 systemd 另设退出码。

选择覆盖信号上下文而非全局忽略信号：仍由 uvicorn `handle_exit` 处理停止请求及第二次 SIGINT，结束后恢复原处理器。升级 uvicorn 时应继续运行这些真实进程测试。

**5. 先红后绿**

| 测试 | 首次结果与最终结果 |
|---|---|
| Web SIGTERM | **红**：退出码 `-15`（shell 对应 143），`Finished server process` 已出现，结束日志为 0 条；修复后退出码 0、结束日志完整。 |
| Web SIGINT | 初绿：旧实现这一分支已能正常返回；修复后继续通过。 |
| worker SIGTERM | 初绿：现有 worker 信号处理正确；新增真实进程测试确认退出码 0、两条生命周期日志及锁释放。 |
| Web 恢复处理器／SIGTERM | 修复后新增验证，初绿：原处理器恢复，未重放信号。 |
| Web 恢复处理器／SIGINT | 修复后新增验证，初绿：原处理器恢复，未重放信号。 |

相关回归 **57 项通过**，随后完整检查通过。