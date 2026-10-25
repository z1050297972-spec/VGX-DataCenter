**1. 第 1–6 条处理结果**

本轮仍为契约骨架，业务函数体未实现；未暂存、未提交。

1. **旧口令错误改为 400**：新增 `CurrentPasswordError`，继承 `AccountInputError`，固定提示“当前口令不正确”。前四次提交 G2 计数后返回 400，保留 cookie 和页面；第五次仍为 429。字段校验仍为 422，真实会话失效才返回 401。前端契约和跳过测试同步修改。
2. **补齐角色检查顺序**：明确 Origin → 白名单 → 认证 → 强制改密 → 角色 → 路由 → 参数校验。六个管理员操作均声明 `get_admin_context`；全局入口在读取请求体前检查权限。成员访问已知管理员模板，即使方法错误、编号非法或 JSON 不合格，也先返回 403。补齐嵌套路由展开测试。
3. **Argon2 全部移出事务**：登录、改密采用只读快照 → 事务外核验/哈希 → 写事务重读并提交；建号、重置和运维操作也先计算新哈希。补齐排队/运算期间其他连接可取得写锁，以及快照变化时拒绝旧结果的测试。
4. **非法时钟归 500**：新增 `get_account_now` 骨架，入口统一校验并缓存时刻。非法返回值、回调失败和时间溢出归 `DefectError`；领域直接调用的非法 `now` 仍可归 `AccountInputError`，不混淆用户字段错误。
5. **刷新获锁等待缩至 100 毫秒**：新增具名常量和 `session_scope_with_lock_timeout` 骨架，约定独立连接在 BEGIN 前设置 `busy_timeout`。普通事务仍为 5000 毫秒；补配置隔离、超时、异常分类和清理测试。
6. **清理完成**：路由重复的秘密保护说明移至模块 docstring；重复文档关闭测试合并；`security.py` 只描述 `ExternalError`，不再写 HTTP 状态码。已重新生成 OpenAPI。

未联网、未安装依赖；无另建试验文件，OpenAPI 临时目录已清理。

**2. `make check`**

最后一次命令：

```text
make check
```

退出码 `0`。末尾输出原样如下：

```text
================= 557 passed, 320 skipped, 1 warning in 26.09s =================
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.rgEJXYGOcu/openapi.json → /tmp/tmp.rgEJXYGOcu/schema.d.ts [37.1ms]
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
      Tests  77 passed | 50 skipped (127)
   Start at  09:14:54
   Duration  1.61s (environment 50%, tests 25%, import 24%, transform 1%, setup 1%)
```

运行前 `git status --porcelain --untracked-files=all`：

```text
 M pyproject.toml
 M src/rdp/api/__init__.py
 M src/rdp/api/errors.py
 M src/rdp/infra/db/connection.py
 M src/rdp/infra/diagnostics.py
 M src/web/src/api/openapi.json
 M src/web/src/api/problems.ts
 M src/web/src/api/schema.d.ts
 M src/web/src/router.tsx
 M tests/test_api_database.py
 M tests/test_api_errors.py
 M tests/test_db_connection.py
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
 M src/rdp/infra/db/connection.py
 M src/rdp/infra/diagnostics.py
 M src/web/src/api/openapi.json
 M src/web/src/api/problems.ts
 M src/web/src/api/schema.d.ts
 M src/web/src/router.tsx
 M tests/test_api_database.py
 M tests/test_api_errors.py
 M tests/test_db_connection.py
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

- **契约变更申请**：为第 5 条新增数据库工作单元 `session_scope_with_lock_timeout`，并扩展 `_begin_transaction` 的契约以支持连接级超时选项。既有函数实现未变，普通 `session_scope` 默认 5 秒不变；新增入口仍是桩，提交骨架评审。
- **依赖申请**：无。
- **受保护文件申请**：无。本轮未修改受保护配置；状态中的 `pyproject.toml` 是前轮遗留改动。

**4. 重读发现变化时的处理**

已写入骨架，按以下优先级处理：

1. 账号已删除、停用，或改密请求的当前会话已撤销：**401**。
2. 当前 G2 已处于等待：**429**，不再次计数、不延长截止。
3. 账号仍可用、不在等待，但口令哈希或原始 G2 二元组与快照不同：**409**，提示“账号状态已变化，请重试”。

上述情况均丢弃预计算结果，不写旧重哈希、不增加失败计数、不签发会话，也不自动重试。只有重读确认一致才应用核验结果。

其余无待定项。