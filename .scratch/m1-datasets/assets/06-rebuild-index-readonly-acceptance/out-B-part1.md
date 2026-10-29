**1. 改动清单**

前半段检查点完成，改动留在工作区，未暂存、未提交。

- 新增 `rdp rebuild-index`：拒绝运行中的 worker、全程持单实例锁、清空索引、执行两段扫描、打印摘要。
- 成功审计与索引发布同事务提交；扫描失败记录失败操作并释放锁。
- 不统计大小，清除旧统计值并提示每晚或页面手动提交。
- 新增审计迁移、日志中文标签，已运行 `make api-types`。
- 仅修改 `src/`、`tests/`；未访问 `/mnt`、真实部署或 systemd；试验日志已删除。

**2. `make check`**

退出码 **0**。pytest 汇总：

```text
============ 2285 passed, 2 skipped, 8 warnings in 81.35s (0:01:21) ============
```

末尾输出：

```text
All matched files use Prettier code style!
[11/11] Vitest

 Test Files  23 passed (23)
      Tests  251 passed (251)
   Start at  09:23:11
   Duration  10.13s (tests 43%, environment 27%, import 18%, transform 11%, setup 2%)
```

**3. 契约变更申请、依赖申请**

请审核以下新增扩展，既有值含义保持不变：

- 操作码：`rebuild_index`。
- 审计对象：`dataset_index`，固定编号 `all`。
- 新迁移：`0009_rebuild_index_audit`，扩展对象类型 CHECK，保留历史日志和编号高水位。
- 对应 OpenAPI 枚举及生成类型。

依赖申请：**无**。受保护文件变更申请：**无**。

**4. 执行线演练及下一段**

在本 worktree、隔离的 `HOME` 和 `RDP_CONFIG` 下使用：

```bash
.venv/bin/python -m rdp migrate
.venv/bin/python -m rdp worker
# 另一终端，同一临时配置：
.venv/bin/python -m rdp rebuild-index
```

worker 运行时应退出 **1** 并提示网页提交；停止临时 worker 后重建应退出 **0**，打印计数、耗时和大小提示。日志应新增一条“运维”的 `rebuild_index` 成功记录。

注意：

- 清空后扫描失败会留下空索引，修复原因后可重跑。
- 比对业务内容时须区分扫描时间、代次等运行元数据，以及大小统计产生的字段和发现；真实数据的一致性尚待演练确认。
- 下一段补取锁竞争、发布/审计事务故障回滚测试，并处理真实演练反馈；真实部署验收、耗时实测和手册仍由执行线完成。

**5. 先红后绿**

| 测试 | 独立运行记录 |
|---|---|
| `test_rebuild_refuses_running_worker` | 红：未知子命令退出 2 → 绿 |
| `test_rebuild_runs_both_stages` | 红：索引为空 → 绿 |
| `test_rebuild_holds_worker_lock` | 红：扫描期间锁可取得 → 绿 |
| `test_rebuild_clears_corrupt_index` | 红：旧损坏指纹阻止扫描 → 绿 |
| `test_rebuild_records_one_ops_log` | 红：无操作日志 → 绿 |
| `test_rebuild_drops_sizes_and_prints_next_step` | 修正夹具约束后红：缺大小提示 → 绿 |
| `test_rebuild_scan_failure_is_audited` | 红：缺失败日志 → 绿 |
| 前端“重建索引操作可筛选且显示中文标签” | 红：操作码被拒绝 → 绿 |
| 迁移保留历史 `[False]` | 首次绿：此前迁移实现已包含历史与序列恢复 |
| 迁移空表 `[True]` | 首次绿：此前迁移实现已包含空表序列恢复 |
| `test_rebuild_lock_race` | 跳过，下一段 |
| `test_rebuild_publication_failure` | 跳过，下一段 |