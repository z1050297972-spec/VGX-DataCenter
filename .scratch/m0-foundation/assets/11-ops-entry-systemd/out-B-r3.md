**1. 改动清单**

- [src/rdp/infra/state.py](/home/shawn/桌面/robot-data-platform.wt/m0-11-ops-entry-systemd/src/rdp/infra/state.py)：捕获 mkdir 的 `FileExistsError` 后重新核验；仅接受真实目录，不 chmod 竞争方目录。祖先递归同样适用。
- [tests/test_state_concurrency.py](/home/shawn/桌面/robot-data-platform.wt/m0-11-ops-entry-systemd/tests/test_state_concurrency.py)：新增确定性竞争、文件/软链接拒绝、路径消失及四进程屏障并发测试。

未修改其他模块，未暂存、未提交；临时文件已清理。

**2. `make check`**

本轮运行一次，退出码 **0**。pytest **1967 passed / 0 skipped**；Vitest **250 passed / 0 skipped**。

```bash
make check > /tmp/rdp-r3-check.ilhQPo/check.log 2>&1
```

末尾原样输出：

```text
================= 1967 passed, 1 warning in 147.07s (0:02:27) ==================
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.ZlKE6RcaR2/openapi.json → /tmp/tmp.ZlKE6RcaR2/schema.d.ts [70.4ms]
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
   Start at  12:34:14
   Duration  7.14s (tests 49%, environment 29%, import 21%)
```

运行前 `git status --porcelain --untracked-files=all`：

```text
 M src/rdp/infra/state.py
?? tests/test_state_concurrency.py
```

运行后：

```text
 M src/rdp/infra/state.py
?? tests/test_state_concurrency.py
```

**3. 契约补充/docstring 改动**

`initialize_state.Time Semantics` 仅增加一句：

> 并发初始化时，若其他进程抢先创建目录，则重新核验后按既有目录处理，不修改其权限。

签名、返回值及其余契约未改，无新增依赖。

**4. 拿不准的地方及装配路径检查**

无待决项。未发现其他同类、会导致 Web/worker 同时启动失败的创建竞争，因此未扩展修改。

| 检查点 | 结论 |
|---|---|
| 运行日志 | 分别写 `web.log`、`worker.log`，追加打开；归档按各自文件名前缀处理。 |
| worker 锁 | 使用原子 `os.open(O_CREAT…)` 加 `flock`；Web 不创建该锁。 |
| 数据库 | 引擎延迟连接，启动先只读检查版本；缺库会拒绝启动，不由两个服务竞争建库。WAL/SHM 由 SQLite 协调。 |
| 迁移备份目录 | 存在“检查后创建”，但位于迁移锁内，且不属于服务启动路径。 |

**5. 先红后绿**

| 测试 | 首次结果 |
|---|---|
| `test_directory_created_between_check_and_mkdir`（祖先/root/logs/job） | **四项均红**：`FileExistsError [Errno 17]`；修复后全绿，并确认竞争方的 0755 权限未被修改。 |
| `test_creation_collision_rejects_non_directory`（普通文件/软链接/悬空链接） | 初绿：修复中的重新核验已保留对应拒绝行为。 |
| `test_initialize_state_concurrent_processes` | 修复后新增验证，初绿：四个真实进程经屏障同时初始化，全部成功，新建目录均为 0700。 |
| `test_collision_without_remaining_directory_is_not_success` | 初绿：修复已在无法确认目录存在时保留原异常。 |

相关回归 **41 项通过**，随后完整检查通过。