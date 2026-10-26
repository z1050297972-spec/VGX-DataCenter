# 第 7 张骨架评审（A-done，快照 1d7a52e）

机械检查：`make check` 复跑全绿（pytest 880 passed / 251 skipped，Vitest 128 passed / 33 skipped）；只改了 `src/`、`tests/` 和 `pyproject.toml` 的 import-linter；运行日志没有安装、联网、碰 /mnt 或 git 写操作，`/tmp/rdp-*` 已清空；违规试验 9 项全部符合预期（violation_probe-A-done.txt）。

## 阻塞（执行线核实）
1. `accounts/audit_contract.py:36` 和 11 个方法签名：`audit` 参数带默认值 `_EMPTY_AUDIT_CONTEXT`，和 `tests/test_audit_api.py:43`"缺失上下文归 DefectError"矛盾；HTTP 漏传时来源 IP 会悄悄记成空（违反验收 3）。改成必填关键字参数；运维显式传具名常量（例如 `OPS_AUDIT_CONTEXT`）。
2. `audit_contract.py:356`：本人改口令输错旧口令时，失败操作日志另开短事务。第 6 张这时本来就要提交 G2 计数，有现成的写事务，应当同一事务提交（和登录输错口令的做法一致）；相应测试改断言。
3. docstring 套模板，再犯 7.1 第一条：`audit_contract.py` 358、411、465、518、573、625、667、717 行，8 个方法逐字共用同一段 6 行；`audit` 参数说明 11 处是同一句，只给运维用的方法写着"HTTP 必须传"，只走 HTTP 的方法写着"运维两项为空"。每个方法只写自己真会发生的情况。

## 执行线采纳、一并修的
4. "开始执行"的界线统一：管理员预检通过、进入写事务以后被拒绝的（重复登录名、最后一个管理员等 409）都算开始执行，记失败日志；`set_role`、`set_status`、`delete_account` 现在不记，补上，和 `create_account` 一致。
5. 领域层收到不合法的 `AuditContext` 是平台缺陷，归 `DefectError`，不是 `AuditInputError`（否则会映射成 422）。
6. import-linter 改成分层：`"rdp.jobs | rdp.accounts"`、`"rdp.audit"`、`"rdp.infra"`，去掉 `ignore_imports` 例外；第 8 张 jobs → audit 也不用再开口子。
7. 操作日志的"账号"筛选同时支持按操作人和按对象账号（查"谁动过这个账号"）。
8. 补测试：`purge_expired` 在没有设置行时按 30 天清除。
9. 契约注明：过期后再也没被访问的会话，不会留下"会话过期"日志。
10. 过渡模块：B 的第一步就把覆盖直接写进 `service.py` 并删掉 `audit_contract.py`，不要两套服务并存。过程说法（骨架、拟议、实现阶段等）在 B 里清掉。

## Codex 第 4 块的决定
- 增加 `failure` 登录结果（哈希资源、并发、数据库故障）、没有变化的请求不记、失败的新建对象编号留空：执行线同意。
- 过期会话删除改成 100 毫秒短锁、拿不到就跳过并仍返回 401（第 6 张现在等约 5 秒、锁冲突返回 409）：建议批准，但改了第 6 张的对外行为，要负责人确认。
