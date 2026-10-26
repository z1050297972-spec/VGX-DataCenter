**1. 改动清单**

契约骨架已完成；新增 Python 函数均只含 `raise NotImplementedError`，前端函数只抛“未实现”。模型和迁移未激活，改动未暂存、未提交；临时检查日志已删除。

| 文件 | 改动 |
|---|---|
| `pyproject.toml` | 仅调整 import-linter，登记 audit 及 accounts → audit。 |
| `src/rdp/accounts/_boundary.py` | 允许固定的补记失败标记穿过脱敏边界。 |
| `src/rdp/accounts/types.py` | 从原路径再导出 ActorRef。 |
| [src/rdp/accounts/audit_contract.py](/home/shawn/桌面/robot-data-platform.wt/m0-07-audit-login-logs/src/rdp/accounts/audit_contract.py) | 隔离账号服务覆盖骨架，逐项声明开始边界、事务和失败补记。 |
| `src/rdp/api/__init__.py` | 注册日志路由和 OpenAPI。 |
| `src/rdp/api/audit.py` | 四个管理员接口、请求来源提取及补记失败报告骨架。 |
| `src/rdp/api/audit_schemas.py` | 查询、日志响应及保留期字段声明。 |
| `src/rdp/audit/__init__.py` | 声明领域职责和依赖边界。 |
| `src/rdp/audit/errors.py` | 定义安全的日志输入异常。 |
| `src/rdp/audit/models.py` | 两种日志及设置表，全部保持 `__abstract__`。 |
| `src/rdp/audit/policy.py` | 保留期、分页、明细容量和短锁常量。 |
| `src/rdp/audit/records.py` | 追加、查询及保留期读写契约。 |
| `src/rdp/audit/service.py` | 独立失败补记及 `purge_expired(now)` 契约。 |
| `src/rdp/audit/types.py` | 枚举、身份快照、白名单明细及游标页类型。 |
| `src/rdp/infra/actors.py` | 承载共用 ActorRef，避免领域循环依赖。 |
| `src/rdp/infra/db/migrations/pending/__init__.py` | 隔离待激活迁移。 |
| `src/rdp/infra/db/migrations/pending/v0003_audit_login_logs.py` | 0003 升级及拒绝降级骨架。 |
| `src/rdp/ops/audit.py` | 运维边界补记失败报告骨架。 |
| `src/web/src/accounts/Pages.tsx` | 管理员日志菜单及布局权限复核。 |
| `src/web/src/accounts/navigation.ts` | 共用管理员页面清单。 |
| `src/web/src/api/audit.ts` | 使用生成类型的日志 HTTP 调用骨架。 |
| `src/web/src/api/audit.test.ts` | 传输、错误、取消等跳过测试。 |
| `src/web/src/api/openapi.json` | 经 `make api-types` 重新生成。 |
| `src/web/src/api/schema.d.ts` | 经 `make api-types` 重新生成。 |
| `src/web/src/audit/Pages.tsx` | 两个日志页面骨架。 |
| `src/web/src/audit/Pages.test.tsx` | 页面、权限、筛选及快照跳过测试。 |
| `src/web/src/audit/queries.ts` | Query/Mutation 契约骨架。 |
| `src/web/src/audit/search.ts` | TanStack Router 类型化筛选契约。 |
| `src/web/src/router.tsx` | 注册两个日志路由及 search 校验。 |
| `tests/test_audit_accounts.py` | 账号事务、登录结果、失败补记与快照测试清单。 |
| `tests/test_audit_api.py` | 权限顺序、Origin、来源和错误边界测试清单。 |
| `tests/test_audit_migration.py` | 隔离、升级、回滚及数据库约束测试清单。 |
| `tests/test_audit_records.py` | 追加、敏感字段、分页、保留期和时间边界测试清单。 |

**2. `make check`**

最后一次检查命令，退出码 `0`：

```bash
make check > /tmp/rdp-m0-07-check.log 2>&1
```

末尾输出原样：

```text
================= 880 passed, 251 skipped, 1 warning in 59.90s =================
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.L9w8LooYCS/openapi.json → /tmp/tmp.L9w8LooYCS/schema.d.ts [50.7ms]
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

 RUN  v5.0.5 /home/shawn/桌面/robot-data-platform.wt/m0-07-audit-login-logs/src/web


 Test Files  12 passed | 2 skipped (14)
      Tests  128 passed | 33 skipped (161)
   Start at  21:21:28
   Duration  4.68s (tests 42%, environment 38%, import 18%)

```

唯一 warning 来自现有 Starlette/httpx 测试依赖；没有安装或更换依赖。既有 OpenAPI 路径和 schema 均未变化。

```text
git status --porcelain --untracked-files=all
 M pyproject.toml
 M src/rdp/accounts/_boundary.py
 M src/rdp/accounts/types.py
 M src/rdp/api/__init__.py
 M src/web/src/accounts/Pages.tsx
 M src/web/src/accounts/navigation.ts
 M src/web/src/api/openapi.json
 M src/web/src/api/schema.d.ts
 M src/web/src/router.tsx
?? src/rdp/accounts/audit_contract.py
?? src/rdp/api/audit.py
?? src/rdp/api/audit_schemas.py
?? src/rdp/audit/__init__.py
?? src/rdp/audit/errors.py
?? src/rdp/audit/models.py
?? src/rdp/audit/policy.py
?? src/rdp/audit/records.py
?? src/rdp/audit/service.py
?? src/rdp/audit/types.py
?? src/rdp/infra/actors.py
?? src/rdp/infra/db/migrations/pending/__init__.py
?? src/rdp/infra/db/migrations/pending/v0003_audit_login_logs.py
?? src/rdp/ops/audit.py
?? src/web/src/api/audit.test.ts
?? src/web/src/api/audit.ts
?? src/web/src/audit/Pages.test.tsx
?? src/web/src/audit/Pages.tsx
?? src/web/src/audit/queries.ts
?? src/web/src/audit/search.ts
?? tests/test_audit_accounts.py
?? tests/test_audit_api.py
?? tests/test_audit_migration.py
?? tests/test_audit_records.py
```

**3. 契约变更申请、依赖申请**

依赖申请：**无**。

第 6 张运行中的 `AccountService` 未替换。以下变更写在隔离的 `AuditedAccountService` 骨架中；原参数类型和返回类型不变，均新增关键字参数：

```python
audit: AuditContext = _EMPTY_AUDIT_CONTEXT
```

默认值为不可变的空来源，仅兼容既有直接调用；HTTP 必须显式传入来源 IP 和请求编号。

| 旧签名 → 骨架签名（省略 self） | 原因 |
|---|---|
| `login(credentials, *, now)` → `login(credentials, *, now, audit=…)` | 登录日志来源及请求关联。 |
| `authenticate(token, *, now)` → `authenticate(token, *, now, audit=…)` | 过期删除记录本次访问来源。 |
| `logout(identity, *, now)` → `logout(identity, *, now, audit=…)` | 登出日志来源。 |
| `change_password(identity, change, *, now)` → `change_password(identity, change, *, now, audit=…)` | 本人改密操作日志。 |
| `create_account(identity, command, *, now)` → `create_account(identity, command, *, now, audit=…)` | 新建账号操作日志。 |
| `set_role(identity, account_id, role, *, now)` → `set_role(identity, account_id, role, *, now, audit=…)` | 改角色操作日志。 |
| `set_status(identity, account_id, status, *, now)` → `set_status(identity, account_id, status, *, now, audit=…)` | 启停操作日志。 |
| `reset_password(identity, account_id, password, *, now)` → `reset_password(identity, account_id, password, *, now, audit=…)` | 管理员重置日志。 |
| `delete_account(identity, account_id, *, now)` → `delete_account(identity, account_id, *, now, audit=…)` | 删除操作日志。 |
| `create_first_admin(command, *, now)` → `create_first_admin(command, *, now, audit=…)` | 首管理员日志，运维来源为空。 |
| `reset_password_from_ops(login_name, password, *, now)` → `reset_password_from_ops(login_name, password, *, now, audit=…)` | 运维重置日志，来源为空。 |

**需要批准的行为差异：**现有第 6 张过期删除等待约 5000 毫秒，锁冲突抛 `ConflictError`（409）；本票执行线要求短锁 100 毫秒，拿不到时跳过删除和日志，仍拒绝过期身份（401）。骨架已明确记录该差异，尚未激活。按照你限定的“变更第 6 张 HTTP 行为须停下”边界，实施前需要确认。

**4. 需要评审决定的地方**

- **骨架隔离方式：**账号覆盖暂放 `audit_contract.py`。批准后逐函数 TDD 并回 `service.py`，接入请求上下文和 API/运维报告边界，再删除过渡模块。
- **登录执行故障：**在五种既定结果之外增加 `failure` 和失败类别，用于哈希资源、并发或数据库故障，避免伪造“口令错误”结论。
- **本人输错旧口令：**保留第 6 张已批准的 G2 提交及 400/429 行为；计数提交后，独立短事务补记失败操作。
- **无变化请求：**同角色、同启停状态、同有效保留期不写操作日志，按“没有真正改动”处理。
- **账号编号：**已确认模型和 0002 迁移均使用 `AUTOINCREMENT`。失败新建若事务回滚，即使曾分配编号，失败日志也将对象编号留空，防止未提交编号复用造成错关联。