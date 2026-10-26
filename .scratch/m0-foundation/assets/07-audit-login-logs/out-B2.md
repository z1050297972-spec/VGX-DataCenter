**1. 改动清单**

本轮交回第二个检查点：**后端和前端客户端已完成，页面部分仍未完成**。已接近 80 分钟预算，剩余工作列在第 4 块。

改动未暂存、未提交；本轮 `/tmp/rdp07-b2-*.log` 临时日志已删除，没有安装或联网。

| 本轮文件 | 改动 |
|---|---|
| `src/rdp/accounts/_audit.py` | 操作快照、成功追加、失败补记及旧口令失败的事务适配。 |
| `src/rdp/accounts/_login.py` | 登录判定、G2/会话与日志原子提交、匿名及执行故障记录。 |
| `src/rdp/accounts/_inputs.py` | 提取本人改密输入校验，控制函数复杂度。 |
| `src/rdp/accounts/service.py` | 完成账号操作、登录、登出、日志查询和保留期服务接入。 |
| `src/rdp/api/_account_context.py` | 共用已认证身份提取，避免跨模块调用私有函数。 |
| `src/rdp/api/_audit_views.py` | 查询参数及安全响应转换，保留 64 位编号文本。 |
| `src/rdp/api/accounts.py` | 使用共用身份提取。 |
| `src/rdp/api/audit.py` | 实现四个管理员接口。 |
| `src/rdp/api/errors.py` | 在统一异常边界报告审计补记失败。 |
| `src/rdp/ops/accounts.py` | 在运维边界报告补记失败，保留原错误。 |
| `src/web/src/api/_request.ts` | 提取共用超时、取消及迟到响应处理。 |
| `src/web/src/api/accounts.ts` | 复用共用请求执行器，公开签名不变。 |
| `src/web/src/api/audit.ts` | 实现四个日志客户端调用及基本响应校验。 |
| `src/web/src/api/audit.test.ts` | 展开全部 13 个客户端用例。 |
| `tests/audit_account_support.py` | 增加真实账号操作场景。 |
| `tests/test_audit_accounts.py` | 展开剩余 92 个用例，补充无变化请求的提交故障测试。 |
| `tests/test_audit_api.py` | 展开剩余 26 个用例，补充 API/运维报告接入测试。 |
| `tests/test_accounts.py` | 调整两个旧测试的故障注入或 SQL 观察范围，原断言不变。 |

**2. `make check`**

末次命令，退出码 `0`：

```bash
make check > /tmp/rdp07-b2-check.log 2>&1
```

pytest **零 skipped**；Vitest 剩余页面清单 **26 skipped**。末尾输出原样：

```text
================== 1261 passed, 1 warning in 72.99s (0:01:12) ==================
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.SkZgdIWYh9/openapi.json → /tmp/tmp.SkZgdIWYh9/schema.d.ts [50.6ms]
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


 Test Files  13 passed | 1 skipped (14)
      Tests  141 passed | 26 skipped (167)
   Start at  00:54:59
   Duration  4.44s (tests 42%, environment 38%, import 19%)

```

收尾检查曾发现私有函数跨模块引用和响应校验的类型检查问题，修正后重跑通过。

**3. 契约变更申请、依赖申请**

均无。

已批准的领域公开签名、类型及函数 docstring 未改。本轮文档调整：

- `ops/accounts.py` 模块说明改为“领域负责操作日志，入口额外报告补记失败”。
- `api/errors.py` 删除“实现阶段”过程措辞。
- `test_login_unknown_no_state` 说明限定为账号、G2、会话业务状态只读；审计短事务另由本票测试覆盖。
- 新增辅助函数的中文职责说明和请求执行器六项 TSDoc。
- 删除已实现客户端函数的未使用参数豁免。

**4. 评审事项、旧测试调整、剩余工作**

第 6 张本轮没有新增行为断言变更。两个测试仅调整观察范围：

| 测试 | 调整 |
|---|---|
| `test_service_failure_cleanup` | 关闭故障只注入业务写事务，避免新增只读预检先失败；原 ConflictError 和安全 note 断言保留。 |
| `test_login_unknown_no_state` | SQL 采集排除 H2 独立审计短事务；原业务“不写账号/G2/会话”断言保留，新日志写入由本票测试验证。 |

**剩余前端 26 个用例**全部位于 `src/web/src/audit/Pages.test.tsx`，对应：

- `search.ts`：类型化筛选校验、UTC 边界、账号编号及游标重置。
- `queries.ts`：列表/设置 Query、Mutation、缓存失效、取消与聚焦重查。
- `Pages.tsx`：两个 antd 页面、保留期表单、只读展示、删除标记、翻页和诊断。
- 页面级权限、刷新/分享、迟到响应和账号切换测试。

另外，收尾应补一个跨模块边界回归：日志姓名校验目前使用 `isprintable()`，账号侧按 Unicode 类别排除控制字符，两者对部分 Unicode 字符可能不一致，应统一后再做整票验收。

因此当前仍不是页面演示或整票完工版本。

**5. 本轮先红后绿**

参数化用例结果相同的合并一行；不同的分别注明。测试初稿中的夹具或比较范围问题没有冒称实现缺陷。

`tests/test_audit_accounts.py`

| 测试 | R / P |
|---|---|
| `test_success_atomic` | R：九类操作均未生成成功日志；夹具目录修正后确认。 |
| `test_execution_boundary` | R：执行失败未补记，保留期服务未实现。 |
| `test_rejection_not_logged` | P：已有校验及本轮执行边界已覆盖。 |
| `test_failure_append_preserves_error` | R：没有补记失败标记。 |
| `test_failure_category` | R：没有失败事件。 |
| `test_login_outcomes` | R：六种结果均没有登录日志。 |
| `test_login_atomic[g2_increment/g2_wait/success/rehash]` | R：状态变化未伴随登录日志。 |
| `test_login_atomic[commit_failure]` | P：既有工作单元已经回滚提交失败。 |
| `test_missing_login_privacy` | R：没有匿名失败记录。 |
| `test_login_rejection_race` | R：没有拒绝日志，也未进入重读短事务。 |
| `test_logout_atomic` | R：日志故障注入未触发，因登出没有写日志。 |
| `test_session_rollback_clock` | P：已有负经过时长和刷新规则满足。 |
| `test_no_fabricated_logout` | P：没有合成登出记录；删除用例初稿误比较实时删除标记，改为比较历史事件后通过。 |
| `test_password_secrets` | P：白名单适配及已有秘密边界已满足。 |
| `test_own_wrong_password` | R：只有 G2 更新，没有失败操作日志。 |
| `test_ops_actor` | P：此前成功日志接入已使用运维快照。 |
| `test_actor_reexport` | P：既有 ActorRef 再导出已满足。 |
| `test_failure_notice_survives_secret_boundary` | P：此前补记及脱敏边界已保留固定标记。 |
| `test_login_execution_failure` | R：读取、真实哈希名额耗尽、并发 G2 变化和提交故障均未补登录失败记录。 |
| `test_failed_creation_has_no_reusable_account_id` | P：失败模板已保持空对象编号。 |
| `test_read_permissions` | R：三个服务查询入口未实现。 |
| `test_conflict_after_admin_precheck_is_logged` | P：此前 H3 包装已覆盖写事务中的冲突。 |
| `test_target_disappears_inside_write_is_logged` | P：此前执行边界和失败模板已覆盖。 |
| `test_write_reauthorization_rejection_is_not_logged` | P：此前明确排除了授权拒绝。 |
| `test_own_wrong_password_transaction[first_wrong/fifth_wrong/log_flush_failure]` | R：失败日志缺失，日志故障不能影响 G2 提交。 |
| `test_own_wrong_password_transaction[commit_failure]` | P：既有提交失败回滚机制满足。 |
| `test_noop_commit_failure_not_audited` | R：无变化请求在提交故障时误记失败事件，已修复。 |

`tests/test_audit_api.py`

| 测试 | R / P |
|---|---|
| `test_authorization_order` | R：管理员正常请求仍返回未实现错误。 |
| `test_member_denied` | P：既有全局管理员鉴权已满足。 |
| `test_origin_required` | R：拒绝分支已正确，但设置读写路由未实现。 |
| `test_no_single_row_mutation` | P：批准的路由声明没有单条修改、删除入口。 |
| `test_response_types` | R：列表路由未实现。 |
| `test_api_errors[input/conflict/external/defect]` | R：路由未进入数据库查询；缺陷用例增加“故障确实注入”的断言后确认。 |
| `test_api_errors[validation]` | P：已有 Pydantic 参数校验满足。 |
| `test_operation_account_query_api[actor_only/target_only/both/target_overflow/cursor_filter_change]` | R：查询路由未实现。 |
| `test_operation_account_query_api[target_leading_zero]` | P：已有 schema 正则拒绝。 |
| `test_invalid_domain_audit_returns_server_error` | R：加入正常请求对照后确认路由未实现，不能拿占位 500 冒充正确结果。 |
| `test_failure_report_is_connected` | R：接口未完成，补记报告没有接入边界。 |
| `test_ops_failure_report_is_connected` | R：运维边界没有报告补记失败。 |

`src/web/src/api/audit.test.ts`：以下 13 项首次均因函数抛“未实现”而失败，随后通过。

```text
R 列表 GET、路径和游标参数
R 两种列表空页及末页
R 64 位编号与敏感字段
R 保留期读取失败及 PUT 载荷
R 写请求超时、不自动重试
R 四种调用的统一 401 处理
R 403／502／422 诊断
R defaultFetch 的 this 回归
R 四种请求超时、取消和迟到结果
R 畸形响应、网络错误及取消诊断
R 同源 PUT 与 cookie 边界
R 操作人、对象账号两个独立参数
R 仅按对象账号筛选
```