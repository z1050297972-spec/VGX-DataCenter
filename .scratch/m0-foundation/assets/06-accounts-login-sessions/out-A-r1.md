**1. 逐条处理结果**

业务函数仍为 `raise NotImplementedError` / `throw new Error("未实现")`；改动未暂存、未提交。

| 项目 | 处理结果 |
|---|---|
| 决定 1 | 删除全局登录预算、1024 桶及节流表。未知/停用账号做一次假验证，正常返回统一“账号或口令错误”401，不计数、不建行。新增 Argon2 进程内共享并发上限 2。 |
| 决定 2 | 明确管理员建号必须首次改密；运维首号不设置该标记，保留对应测试清单。 |
| 决定 3 | 明确所有写请求缺 Origin 均 403，命令行脚本必须自己携带正确 Origin。 |
| 第 1 条 | 逐路由重写 Raises；逐方法重写副作用和时间语义。`list_accounts` 全程只读，不再描述写事务、哈希或无关异常。 |
| 第 2 条 | 回拨不报冲突；负经过时长按 0，活动/修改时间取最大值，既有等待截止不重写。替换原先期望 409 的测试。 |
| 第 3 条 | 固定顺序为 Origin → 公开白名单 → 认证 → 强制改密 → 路由匹配。公开路径错误方法也先过 Origin；补齐 403/401/405 优先级测试。 |
| 第 4 条 | Argon2 所有实例共享 2 个名额，包含初始化、假验证、hash、verify、重哈希；补排队超时、释放、取消和嵌套重哈希测试。 |
| 第 5 条 | 删除 `clear_expired_sessions` 及全部相关测试引用；只保留访问时删除和每账号 32 会话上限。 |
| 第 6 条 | 补 ErrorBoundary 401 清 cookie、所有路由认证脱敏、管理员操作自己后下一请求 401、窗口聚焦重查身份的测试清单。非法状态改为 418，并配正确标题，避免因标题不匹配而误通过。 |
| 第 7 条 | 有效会话刷新在获写锁阶段遇 BUSY/LOCKED 时继续请求；过期删除及其他失败仍拒绝。连续刷新失败仍按旧持久化时刻到期。 |
| 第 8 条 | 仅登录、改密或活动刷新实际提交时续 cookie；新增 `activity_refreshed` 标志，未刷新、锁忙或并发已刷新均不重发。 |
| 第 9 条 | `create_app` 无条件关闭三个 FastAPI 文档路由，调整直接受影响的旧测试；离线导出保留，已运行 `make api-types`。 |

未联网、未安装依赖；无另建试验文件，OpenAPI 检查临时目录已清理。

**2. `make check`**

最后一次命令：

```text
make check
```

退出码 `0`，末尾输出原样如下：

```text
================= 557 passed, 274 skipped, 1 warning in 26.19s =================
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.P13JHVPJo1/openapi.json → /tmp/tmp.P13JHVPJo1/schema.d.ts [37.7ms]
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

 RUN  v5.0.5 /home/shawn/桌面/robot-data-platform.wt/m0-06-accounts-login-sessions/src/web


 Test Files  9 passed | 3 skipped (12)
      Tests  77 passed | 47 skipped (124)
   Start at  08:26:58
   Duration  1.56s (environment 50%, tests 25%, import 24%, transform 1%, setup 1%)
```

运行前 `git status --porcelain --untracked-files=all`：

```text
 M pyproject.toml
 M src/rdp/api/__init__.py
 M src/rdp/api/errors.py
 M src/rdp/infra/diagnostics.py
 M src/web/src/api/openapi.json
 M src/web/src/api/problems.ts
 M src/web/src/api/schema.d.ts
 M src/web/src/router.tsx
 M tests/test_api_database.py
 M tests/test_api_errors.py
 M tests/test_diagnostics.py
 M tests/test_web_app.py
?? src/rdp/accounts/__init__.py
?? src/rdp/accounts/errors.py
?? src/rdp/accounts/models.py
?? src/rdp/accounts/policy.py
?? src/rdp/accounts/security.py
?? src/rdp/accounts/service.py
?? src/rdp/accounts/types.py
?? src/rdp/api/account_auth.py
?? src/rdp/api/account_schemas.py
?? src/rdp/api/accounts.py
?? src/rdp/infra/db/migrations/pending/__init__.py
?? src/rdp/infra/db/migrations/pending/v0002_accounts_sessions.py
?? src/rdp/ops/accounts.py
?? src/web/src/accounts/Pages.test.tsx
?? src/web/src/accounts/Pages.tsx
?? src/web/src/accounts/navigation.test.ts
?? src/web/src/accounts/navigation.ts
?? src/web/src/api/accounts.test.ts
?? src/web/src/api/accounts.ts
?? tests/test_account_api.py
?? tests/test_account_ops.py
?? tests/test_accounts.py
?? tests/test_accounts_migration.py
```

运行后 `git status --porcelain --untracked-files=all`：

```text
 M pyproject.toml
 M src/rdp/api/__init__.py
 M src/rdp/api/errors.py
 M src/rdp/infra/diagnostics.py
 M src/web/src/api/openapi.json
 M src/web/src/api/problems.ts
 M src/web/src/api/schema.d.ts
 M src/web/src/router.tsx
 M tests/test_api_database.py
 M tests/test_api_errors.py
 M tests/test_diagnostics.py
 M tests/test_web_app.py
?? src/rdp/accounts/__init__.py
?? src/rdp/accounts/errors.py
?? src/rdp/accounts/models.py
?? src/rdp/accounts/policy.py
?? src/rdp/accounts/security.py
?? src/rdp/accounts/service.py
?? src/rdp/accounts/types.py
?? src/rdp/api/account_auth.py
?? src/rdp/api/account_schemas.py
?? src/rdp/api/accounts.py
?? src/rdp/infra/db/migrations/pending/__init__.py
?? src/rdp/infra/db/migrations/pending/v0002_accounts_sessions.py
?? src/rdp/ops/accounts.py
?? src/web/src/accounts/Pages.test.tsx
?? src/web/src/accounts/Pages.tsx
?? src/web/src/accounts/navigation.test.ts
?? src/web/src/accounts/navigation.ts
?? src/web/src/api/accounts.test.ts
?? src/web/src/api/accounts.ts
?? tests/test_account_api.py
?? tests/test_account_ops.py
?? tests/test_accounts.py
?? tests/test_accounts_migration.py
```

**3. 申请**

- 契约变更申请：无额外申请；本轮按指定修订，Argon2 排队处理见下。
- 依赖申请：无。
- 受保护文件申请：无。本轮未修改受保护文件，状态中的 `pyproject.toml` 是上一轮遗留改动。

**4. 需要评审决定的地方**

Argon2 已按以下方案写入骨架，供评审：

- 进程内共享 **2 个名额**，用标准库 `BoundedSemaphore`。
- 最多排队 **1 秒**，超时抛 `ExternalError`，HTTP **502**；不新增 503，不占用 G2 的 429，不带 `Retry-After`，不自动重试。
- 超时不增加失败计数、不留下部分账号或会话变更。
- 排队时限不强行中断已开始的 Argon2；运算退出后才释放名额。验证和内部重哈希共用一次名额，避免重复申请造成死锁。

其余无待定项。