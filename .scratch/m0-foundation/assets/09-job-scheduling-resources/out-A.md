**1. 改动清单**

无。发现既有列需要变更，按你的停工边界暂停，契约骨架尚未编写。工作区干净。

**2. `make check`**

最后命令：`make check`，退出码 `0`。pytest、Vitest 均为 **0 skipped**。

原样摘录 pytest 结尾：
```text
================= 1517 passed, 1 warning in 111.97s (0:01:51) ==================
```

检查末尾原样输出：
```text
[10/11] Prettier
cd src/web && node_modules/.bin/prettier --check .
Checking formatting...
All matched files use Prettier code style!
[11/11] Vitest
cd src/web && node_modules/.bin/vitest run

 RUN  v5.0.5 /home/shawn/桌面/robot-data-platform.wt/m0-09-job-scheduling-resources/src/web


 Test Files  16 passed (16)
      Tests  205 passed (205)
   Start at  21:43:23
   Duration  6.73s (tests 52%, environment 28%, import 19%)
```

`git status --porcelain --untracked-files=all` 输出为空。检查产生的临时目录已自动清理。

**3. 契约变更申请、依赖申请**

需要批准一项既有列变更：

- 当前 [jobs/models.py:100](/home/shawn/桌面/robot-data-platform.wt/m0-09-job-scheduling-resources/src/rdp/jobs/models.py:100) 的 `submitter_id` 为 `Mapped[int]`、`nullable=False`，迁移 `0004` 同样规定 `NOT NULL`，无法保存 `SYSTEM_ACTOR = ActorRef(None, "系统")`。
- 建议改为 `Mapped[int | None]`、允许 NULL，并增加约束：空编号只能对应“系统”；账号编号仍须为正整数。
- 由 `pending/0005` 声明迁移契约，保留旧记录、索引及编号序列；不修改 `0004`，本阶段不激活迁移。

依赖申请：无。已合并公开签名的实际改动：无。

**4. 需要评审决定**

请批准上述 `jobs.submitter_id` 可空性扩展。

需要确认的依据是你明确要求：修改“已有表结构里已有的列”时停下；事先批准的作业表扩展只列了“加列”。这一处影响系统提交人的持久化，因此尚未修改。