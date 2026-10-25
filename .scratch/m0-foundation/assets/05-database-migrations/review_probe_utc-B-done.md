# 〔审〕违规试验：一个时间列不用 UTC 列类型（工单「Claude 的步骤」）

- 做法：在 `B-done`（`86412ee`）上给 `src/rdp/infra/db/models.py` 加一个 `AuditEventRow`，其中 `happened_at = mapped_column(DateTime(timezone=True))`，不用 `UTCDateTime`。用 `git commit-tree` 拍成探针提交 `refs/rdp/m0-05/probe-utc`（`41f878a`，不进任何分支），在探针工作目录检出。
- 评审：一个 Standards 轴子 agent 只读看 `86412ee...41f878a`。提示里不提 UTC，只给 CODING_STANDARDS、AGENTS.md 和坏味道基线。
- 结果：**抓到。** 第一条硬性违规就是"CODING_STANDARDS 5.2，models.py:99：`happened_at` 用的是 `DateTime(timezone=True)`，没有用 `UTCDateTime()`。SQLite 不存时区……绕开了数据库层统一的 UTC 转换"。另外报了 `action` 缺 CHECK 长度约束、没有配套迁移、`String(64)` 是魔数。
- 说明：这一项在工单里定为〔审〕，这里只验证评审这一侧。新表没有配套迁移，`test_compare_metadata` 多半也会报差异；但同样的错误写在一张已有迁移的新表里（迁移脚本也用不带 UTC 的类型）时，只有评审能发现。
