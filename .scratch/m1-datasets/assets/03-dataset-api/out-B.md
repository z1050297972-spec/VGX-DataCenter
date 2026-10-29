**1. 改动清单**

第二段完成，改动留在工作区，未暂存、未提交。

- [面板与布局查询](/home/shawn/桌面/robot-data-platform.wt/m1-03-dataset-api/src/rdp/jobs/dataset_browser/queries.py)：四组两级聚合、完整计数与有界样例、离线提示；布局跨会话保存、账号隔离、同值不写、回拨保护，无操作日志。
- [作业提交](/home/shawn/桌面/robot-data-platform.wt/m1-03-dataset-api/src/rdp/jobs/dataset_browser/commands.py)：复用 M0 提交与审计事务，当前账号提交，Web 不执行作业。
- [0008 迁移](/home/shawn/桌面/robot-data-platform.wt/m1-03-dataset-api/src/rdp/infra/db/migrations/versions/v0008_dataset_layout.py)：从 pending 移入活动链，验证升级保留数据、约束和账号删除级联。
- 9 项跳过全部解除；不可读存储根及会话撤销测试扩展到第二段接口。
- OpenAPI 经 `make api-types` 生成；临时脚本、日志已清理。未访问 `/mnt`、联网、安装或操作真实部署。

**2. 三轮 `make check` 汇总及末尾输出**

三轮退出码均为 0、**0 skipped**。pytest 汇总按运行顺序原样如下：

```text
================= 2230 passed, 8 warnings in 68.62s (0:01:08) ==================
================= 2230 passed, 8 warnings in 90.95s (0:01:30) ==================
================= 2230 passed, 8 warnings in 65.16s (0:01:05) ==================
```

三轮前端均为 250 passed，4 条依赖契约全部通过。第三轮末尾：

```text
[10/11] Prettier
cd src/web && node_modules/.bin/prettier --check .
Checking formatting...
All matched files use Prettier code style!
[11/11] Vitest
cd src/web && node_modules/.bin/vitest run

 RUN  v5.0.5 /home/shawn/桌面/robot-data-platform.wt/m1-03-dataset-api/src/web


 Test Files  22 passed (22)
      Tests  250 passed (250)
   Start at  08:13:47
   Duration  7.45s (tests 51%, environment 29%, import 20%)
```

**3. 契约变更申请、依赖申请**

均无新增待批准申请。

HTTP 路径、字段及原服务签名保持不变。M0 作业响应转换移至 `api._job_views` 共用，返回含义不变；旧迁移未改写，历史测试仅更新当前 head 和临时未来版本。

**4. 拿不准的地方及剩余事项**

唯一待合并对齐项：

```text
type_name: dataset_sizing
parameters: {"dataset_id": str | null}
```

本分支尚无第 02 张的生产登记，未登记时返回 422；测试通过显式登记的类型替身验证排队及不执行。合并时由执行线对齐登记键、参数模型。

除此之外无剩余跳过项。保持已通过演练的原文返回方式，不增加压缩或流式传输。

**5. 先红后绿记录**

名称省略 `test_`；初绿项如实注明原因。

| 测试 | 记录 |
|---|---|
| `panel_grouping_bounded_examples_and_offline_banner` | 红→绿：实现面板聚合和根状态投影。 |
| `rescan_submits_current_actor_and_never_executes` | 红→绿：接通单数据集扫描提交。 |
| `sizing_submits_all_or_one_without_worker_import` | 红→绿：接通全量、单数据集统计提交。 |
| `submission_failure_rolls_back_job_and_audit` | 初绿：复用 M0 已有原子事务及失败补记。 |
| `layout_persists_across_sessions_and_isolates_accounts` | 红→绿：实现账号布局读写。 |
| `layout_default_idempotence_and_clock_rollback` | 红→绿：修复同值更新时间和回拨问题。 |
| `layout_without_audit_and_deleted_account` | 初绿：布局未接审计，0008 外键级联已生效。 |
| `layout_migration_matches_model_and_preserves_existing_data` | 红→绿：激活并实现 0008。 |
| `layout_invalid_value_and_database_failure` | 红→绿：缺表明确返回 502；验证回滚与锁冲突。 |
| `layout_direct_call_rejects_invalid_value` | 新增，红→绿：领域直接调用先校验，避免非法布局误报 SQL 冲突。 |
| `all_endpoints_with_unreadable_storage_roots` | 扩展后初绿：全部 10 个操作不访问假存储根。 |
| `identity_revalidated_inside_business_transaction` | 扩展后初绿：新增读写接口均复用事务内身份重验。 |