**1. 改动清单**

契约骨架已完成，改动留在工作区，未暂存、未提交。新增业务函数均为桩；鉴权、迁移和页面业务尚未启用。

| 文件 | 改动 |
|---|---|
| `src/rdp/accounts/__init__.py` | 声明账号领域职责与依赖边界。 |
| `src/rdp/accounts/policy.py` | 登录名、口令、会话、限流等具名规则。 |
| `src/rdp/accounts/types.py` | 角色、状态、ActorRef、账号快照及命令类型。 |
| `src/rdp/accounts/errors.py` | 401/403/404/422/429 异常契约。 |
| `src/rdp/accounts/models.py` | 账号、会话、登录节流表的抽象声明。 |
| `src/rdp/accounts/security.py` | Argon2id、会话令牌及摘要函数骨架。 |
| `src/rdp/accounts/service.py` | 登录、鉴权、账号管理、会话清理事务契约。 |
| `src/rdp/ops/accounts.py` | 可注入口令读取的首号创建、运维重置骨架。 |
| `src/rdp/api/account_schemas.py` | 请求、响应模型及安全快照转换骨架。 |
| `src/rdp/api/account_auth.py` | 全局鉴权、Origin、cookie、S1 兜底契约。 |
| `src/rdp/api/accounts.py` | 十个账号 API 操作的路由骨架。 |
| `src/rdp/api/__init__.py` | 增加时钟参数、登记新路由及详情接口安全声明。 |
| `src/rdp/api/errors.py` | 补状态码表、Retry-After 和账号异常脱敏契约。 |
| `src/rdp/infra/diagnostics.py` | INPUT 允许 401、403、429，同步说明。 |
| `src/rdp/infra/db/migrations/pending/__init__.py` | 声明未激活迁移目录。 |
| `src/rdp/infra/db/migrations/pending/v0002_accounts_sessions.py` | 第二版前向迁移及拒绝降级骨架。 |
| `src/web/src/api/accounts.ts` | 使用生成类型的账号客户端函数骨架。 |
| `src/web/src/api/accounts.test.ts` | 客户端跳过测试清单。 |
| `src/web/src/api/problems.ts` | 接受 401/403/429 的正确 problem 组合。 |
| `src/web/src/api/openapi.json` | 由 `make api-types` 重新生成。 |
| `src/web/src/api/schema.d.ts` | 由 `make api-types` 重新生成。 |
| `src/web/src/accounts/navigation.ts` | 登录守卫、安全回跳、统一 401 处理骨架。 |
| `src/web/src/accounts/navigation.test.ts` | 导航跳过测试清单。 |
| `src/web/src/accounts/Pages.tsx` | 登录、改密、管理页、账号菜单和布局占位组件。 |
| `src/web/src/accounts/Pages.test.tsx` | 页面交互、错误显示及确认流程测试清单。 |
| `src/web/src/router.tsx` | 登记三个占位页面，保留现有首页行为。 |
| `tests/test_accounts.py` | 领域、秘密、模型、并发及失败行为测试清单。 |
| `tests/test_account_api.py` | 鉴权、接口、Origin、cookie、S1、隐私测试清单。 |
| `tests/test_account_ops.py` | 运维交互、取消和恢复测试清单。 |
| `tests/test_accounts_migration.py` | 迁移、备份、回滚及一致性测试清单。 |
| `tests/test_diagnostics.py` | 更新已批准状态码的独立期望，保留越界拒绝断言。 |
| `tests/test_api_errors.py` | 修正状态码测试的过期说明，断言不变。 |
| `pyproject.toml` | 仅在 import-linter 登记 accounts 同层边界及禁用 Web 框架。 |

未联网、未安装依赖；临时目录已清理。

**2. `make check`**

最后一次命令：

```text
make check
```

退出码 `0`，十一步全绿。末尾输出原样如下：

```text
================= 557 passed, 247 skipped, 1 warning in 26.17s =================
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.eDUpreslkL/openapi.json → /tmp/tmp.eDUpreslkL/schema.d.ts [37.5ms]
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
      Tests  77 passed | 42 skipped (119)
   Start at  07:35:57
   Duration  1.51s (environment 49%, tests 26%, import 23%, transform 1%, setup 1%)
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
 M tests/test_api_errors.py
 M tests/test_diagnostics.py
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
 M tests/test_api_errors.py
 M tests/test_diagnostics.py
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

**3. 契约变更申请、依赖申请、受保护文件申请**

以下已写入骨架，提交负责人统一拍板：

- `create_app` 增加可选 `clock`；登记账号接口，并约定实现阶段启用全局鉴权和 S1。
- `InputError`、`ALLOWED_HTTP_STATUSES`、`ProblemResponse` 及前端解析接受 401/403/429；429 带向上取整的 `Retry-After`。
- `handle_error`、`ErrorBoundary` 的账号请求增加秘密脱敏、429 响应头、401 清 cookie，并复用注入的请求时刻。新增辅助函数仍是桩，尚未接线。
- 详情接口通过全局边界要求登录；所有已登录且完成强制改密的角色均可查看。
- 第 5 张 `session_scope`、只读会话和迁移实现契约不改；账号服务自行管理独立事务。

依赖申请：**无**。额外受保护文件申请：**无**。规范与手册未修改。

**4. 已定方案及需要骨架关卡确认的取舍**

| 项目 | 骨架中的决定与理由 |
|---|---|
| 骨架隔离 | 三个 ORM 模型暂为 `__abstract__`；0002 暂放 `pending/`。实现时激活并移入 `versions/`。现有迁移 head、建表一致性测试及旧接口运行行为保持不变。 |
| 登录名、显示名 | 登录名为 `[a-z][a-z0-9_.-]{2,31}`，不修剪、不折叠大小写、不支持更名；显示名 1–64 码点，拒绝首尾空白和控制字符。 |
| 编号与操作者 | SQLite `AUTOINCREMENT` 防止已提交删除的编号复用；JSON 编号使用十进制文本避免 JS 精度损失。`ActorRef.name` 保存当时显示名；运维用 `ActorRef(None, "运维")`。历史快照不建账号外键。 |
| 口令 | 10–128 个 Unicode 码点，不归一化、不要求组合，允许空格；拒绝代理码点。生产采用默认 Argon2id，成功登录按需重哈希。测试可降成本，清单保留默认参数用例。 |
| 哈希资源边界 | 存量 Argon2 编码验证上限为 256 MiB、10 轮、16 路，超过按存量数据问题拒绝，防止损坏编码造成失控消耗。 |
| 会话 | `token_urlsafe(32)` 原文仅放 cookie，数据库存 SHA-256；高熵随机令牌无需慢哈希，查库后常量时间复核摘要。 |
| G1 精度 | 7 天闲置到期，无绝对期限；每次核验，但最少间隔 60 秒持久化活动。**可能提前不足 60 秒过期**，这是减少写入的明确取舍，需关卡确认。访问时删过期会话，另提供有界清理函数供第 9 张调用。 |
| 会话数量 | 每账号最多 32 个，超出淘汰最旧；本人改密撤销全部旧会话并签发新会话。角色改变也撤销目标全部会话，避免继续使用旧权限。 |
| G2 与未知账号 | 已知账号计数放账号表；第五次失败开始等待 60 秒，等待中不哈希，失败状态提交后才抛异常。未知/停用账号验证假哈希，统一提示；未知名字映射固定 1024 桶，避免无限建行。 |
| 附加登录预算 | 所有身份共用每分钟 60 次核验预算，限制轮换名字消耗 CPU。**会限制全平台登录吞吐，未知桶碰撞也可能保守拒绝**，作为额外规则提交关卡确认。 |
| 并发与事务 | `BEGIN IMMEDIATE` 后重验身份、角色、目标及管理员数量；账号修改和会话撤销同事务。旧请求晚获锁不回退活动/修改时间；失败清理沿用第 5 张语义。 |
| 强制改密 | 除“我是谁”、本人改密、登出外均返回 403，包括管理员接口和报错详情；完成后恢复业务访问。 |
| cookie | `rdp_session`，HttpOnly、Lax、Path=/、无 Domain；Max-Age 从 G1 推导为 604800 秒，认证成功响应滑动续期。HTTP 阶段不设 Secure，M5 调整；服务端有效性优先。 |
| Origin | 不安全方法缺失、null、重复或非法 Origin 一律 403，登录也检查。本站按服务器 scheme、Host、有效端口判断，不信任客户端转发头。无 Origin 的客户端必须显式提供；代理及 Host/DNS 信任留给部署确认。 |
| 默认拒绝与 S1 | 仅精确 GET 健康、POST 登录免身份检查；全局守卫覆盖后注册路由。匿名 POST 健康返回 405/Allow；其他未知 API 先鉴权，登录后返回 404。 |
| 运维 | 两次可注入、无回显读取，常量时间比较；输入期间不持锁。首号要求没有任何管理员，含停用；重置删会话、清 G2、强制改密，不自动启用账号。 |
| 前端 | 回跳仅允许安全站内路径，最长 2048；任何 API 401 清缓存并统一跳登录。停用、删除二次确认；列表每页 100 项；请求上限 10 秒，不自动重试写操作。 |
| 检查豁免 | 14 条单独的 TS 未使用参数豁免，均注明实现阶段删除；1 条 S105 豁免，仅针对令牌格式正则的误报。 |

247 个 pytest 跳过项和 42 个 Vitest 跳过项是实施清单，不代表账号功能已通过行为验证。