**1. 本轮改动清单**

整票已完成；前两次检查点的改动保留。

- `src/web/src/audit/search.ts`：实现类型化筛选校验，保留微秒精度和字符串编号。
- `src/web/src/audit/queries.ts`：实现查询、保存、缓存失效及离页取消。
- `src/web/src/audit/Pages.tsx`：实现两个只读日志页面、筛选、游标分页和保留期表单。
- `src/web/src/audit/Pages.test.tsx`：启用剩余 26 条测试，另补 5 条回归测试。
- `src/web/src/api/audit.ts`：集中定义分页、游标和保留期边界常量。
- `src/rdp/infra/actors.py`：提供唯一的 Unicode 名字判断及长度常量。
- `src/rdp/accounts/_records.py`：复用基础层名字判断。
- `src/rdp/accounts/policy.py`：重新导出共用名字长度常量。
- `src/rdp/audit/_validation.py`：移除 `isprintable()`，复用同一判断。
- `src/rdp/audit/types.py`：明细显示名复用共用长度常量。
- `tests/test_audit_accounts.py`：新增 U+E000 回归；清理不可达测试分支，保证线程清理和编码器恢复。
- `tests/test_accounts.py`：删除一处过时测试说明，断言不变。

过程说法、未实现函数和跳过测试扫描均无匹配。本轮临时日志已全部删除，未创建辅助脚本文件。未暂存、未提交。

**2. `make check`**

本轮仅运行一次完整检查，退出码 0。实际命令：

```bash
make check > /tmp/rdp07-current-make-check.log 2>&1
```

末尾输出原样如下；pytest、Vitest 的 skipped 均为 **0**：

```text
================== 1262 passed, 1 warning in 73.00s (0:01:12) ==================
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.ruA8DX8k1o/openapi.json → /tmp/tmp.ruA8DX8k1o/schema.d.ts [49.6ms]
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


 Test Files  14 passed (14)
      Tests  172 passed (172)
   Start at  01:34:26
   Duration  5.72s (tests 54%, environment 28%, import 17%)
```

**3. 契约变更申请、依赖申请**

无。既有公开签名、类型和函数契约未改。

本轮文档调整：

- `infra/actors.py` 模块职责增加“和共用名字规则”；新增 `is_display_name` 的六项契约。
- `test_service_failure_secrets` 删除“；不写登录或操作日志”，保密断言不变。
- `test_failure_append_preserves_error` 改为“业务和补记都失败时保留原错误类别，附追加失败标记且不泄漏驱动文本”。
- `test_failure_category` 改为“业务数据库故障回滚后追加一条失败事件，保留原类别且 after 为空”。
- 新增前端边界常量说明；既有 TSDoc 未改。

**4. 待决事项、第 6 张测试、剩余工作**

无待决事项，无剩余实现或测试。

本轮没有修改第 6 张测试断言。前轮改动继续保留：

- `test_authenticate_expired_delete_busy`：`ConflictError` → `AuthenticationError`；保留会话、下次访问删除的断言不变。
- `test_service_failure_cleanup`：故障注入限定写事务关闭，原断言不变。
- `test_login_unknown_no_state`：业务 SQL 观察排除独立审计短事务，账号/G2/会话断言不变。
- 历史迁移测试使用 0002 fixture；其余账号测试仅补传 `audit`。

真实浏览器演示按约定由执行线完成。

**5. 本轮先红后绿**

`src/web/src/audit/Pages.test.tsx`：

| 测试行为 | 首次结果 |
|---|---|
| 两类表格只读 | R：页面未实现 |
| 保留期仅在操作页面 | R：表单缺失 |
| 保留期边界及失败保留输入 | R：表单缺失 |
| 禁止重复保存、成功刷新并回首页 | R：保存功能缺失 |
| 管理员和成员菜单 | P：已有账号菜单覆盖 |
| 成员直接访问不查询日志 | P：已有路由守卫覆盖 |
| 聚焦降权隐藏内容并取消请求 | P：已有账号布局覆盖 |
| 操作人和对象删除标记 | R：页面未实现 |
| 登录历史身份和未知账号 | R：页面未实现 |
| 缺失来源及 IPv4/IPv6 | R：页面未实现 |
| 安全文本和秘密字段排除 | R：页面未实现 |
| 类型化 search 刷新分享 | R：筛选表单缺失 |
| 改筛选清游标、下一页用游标 | R：筛选和翻页缺失 |
| 带偏移时间及范围边界 | R：校验函数未实现 |
| 非法参数安全拒绝 | R：校验函数未实现 |
| 缺失字段、未知键、字符串编号 | R：校验函数未实现 |
| 本地时间展示、UTC 提交 | R：页面未实现 |
| Query key、缓存隔离及零缓存时间 | R：查询 hook 未实现 |
| 聚焦、无重试轮询、取消迟到请求 | R：查询 hook 未实现 |
| 设置读取失败禁用保存 | R：设置界面缺失 |
| 空态、末页和失败诊断 | R：页面未实现 |
| Provider 缺失与统一错误视图 | R：hook 仍抛“未实现” |
| 操作人和对象独立筛选 | R：筛选表单缺失 |
| 两个账号入 key、交换后重新查询 | R：筛选和翻页缺失 |
| 对象编号边界 | R：校验函数未实现 |
| 已删除目标按原编号查询 | R：对象筛选缺失 |
| 非法 URL 阻止日志请求 | P：已实现校验与路由边界覆盖 |
| 保存时离页取消、忽略迟到成功 | P：已实现取消机制覆盖 |
| 首页保存也刷新操作日志 | P：已实现缓存失效覆盖 |
| 登录查询聚焦、取消、无轮询重试 | P：已实现查询配置覆盖 |
| 设置查询聚焦、取消、无轮询重试 | P：已实现查询配置覆盖 |

`tests/test_audit_accounts.py`：

- `test_display_name_unicode_rule_shared`：**R**，U+E000 被日志侧 `isprintable()` 拒绝，创建账号抛 `AuditInputError`；统一规则后通过。