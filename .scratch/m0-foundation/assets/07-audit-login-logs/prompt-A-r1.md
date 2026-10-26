骨架关卡：负责人说"改"，修一轮。这一步仍然只改契约骨架（签名、类型、docstring/TSDoc、跳过的测试清单），函数体仍是 `raise NotImplementedError` / `throw new Error("未实现")`。评审原文：/home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/assets/07-audit-login-logs/skeleton-review-A-done.md，以本提示为准。动手前读 /home/shawn/桌面/robot-data-platform/docs/agents/codex-workflow.md 第 7.1 节「历次评审打回过的写法」（新加的），修的时候不要引入同类问题。

**负责人的决定**
- 过期会话删除：改成 100 毫秒短锁，拿不到锁就跳过删除和日志，仍返回 401，下次访问再删再记。负责人已批准改第 6 张的这个行为；第 6 张对应的测试在实现阶段一起改，骨架里把测试清单和契约写好。
- 你第 4 块的三条（增加 `failure` 登录结果、没有变化的请求不记、失败的新建对象编号留空）执行线同意，照写。

**必须改的**
1. `audit` 参数去掉默认值，改成必填关键字参数（`accounts/audit_contract.py:36` 和 11 个方法）。运维调用显式传一个具名常量（例如 `OPS_AUDIT_CONTEXT`，来源 IP 和请求编号都为空）。漏传是 `TypeError`；传了不合法的上下文是平台缺陷，归 `DefectError`（见第 5 条）。
2. 本人改口令输错旧口令时，失败操作日志和第 6 张的 G2 计数在同一个写事务里提交，不另开短事务（`audit_contract.py:356` 附近）。和登录输错口令的做法一致。`test_own_wrong_password` 跟着改。
3. docstring 不套模板：`audit_contract.py` 358、411、465、518、573、625、667、717 行那 8 段共用的 6 行，改成每个方法只写自己真会发生的情况（哪些异常会补记、哪些不会、开始执行从哪一步算）。`audit` 参数说明也逐个写：只走运维的方法不写"HTTP 必须传"，只走 HTTP 的方法不写"运维为空"。改完自查所有新增公开函数，没有逐字相同的段落。

**一并改的**
4. "开始执行"的界线统一：管理员预检通过、进入写事务以后被拒绝的（重复登录名、最后一个管理员等冲突）都算开始执行，回滚后记失败日志。`set_role`、`set_status`、`delete_account` 补上，和 `create_account` 一致；测试清单补上。
5. 领域层收到不合法的 `AuditContext` 归 `DefectError`，账号方法的 `Raises:` 里不写 `AuditInputError`（否则会映射成 422）。
6. import-linter 改成分层：`"rdp.jobs | rdp.accounts"`、`"rdp.audit"`、`"rdp.infra"`，去掉 `ignore_imports` 例外，注释写明理由（领域都可以写日志，日志不依赖其他领域）。
7. 操作日志的"账号"筛选同时支持按操作人和按对象账号（查"谁动过这个账号"），接口、前端类型化 search、测试清单都补上。
8. 补测试：`purge_expired` 在没有设置行时按 30 天清除。
9. 契约注明：过期后再也没被访问的会话，不会留下"会话过期"日志。
10. 过渡模块 `audit_contract.py`：在骨架里写清楚，实现阶段第一步就把覆盖直接写进 `service.py` 并删掉这个模块，不让两套服务并存。（这一轮不用挪。）

改完 `make check` 全绿，OpenAPI 有变化用 `make api-types` 重新生成。

边界：
- 只改 `src/`、`tests/`。本票允许改的受保护文件：`pyproject.toml`（只改 import-linter；依赖表和别的段不动）。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。
- 不安装任何东西，不访问网络（沙箱为了跑测试开了网络权限，但这张票用不到网络；评审会查运行日志，出现安装或联网的命令整轮打回）。需要新依赖时停下，在最终回复里写依赖申请（AGENTS.md 规则 7）。
- 自己在 `/tmp` 或别处建的试验文件，交付前删掉。

最终回复分四块：
1. 逐条写处理结果（第 1–10 条）。
2. `make check` 最后一次运行的命令和末尾输出原样贴出（pytest、Vitest 的 passed、skipped 数目要看得出）；再贴 `git status --porcelain --untracked-files=all`。
3. 契约变更申请、依赖申请：没有就写"无"。
4. 拿不准的地方。
