**1. 本轮改动清单**

- 删除自定义统计键，commands 改用 `catalog.SIZING_TYPE`。
- HTTP、commands 共用正式 `sizing.SizingParameters`；删除重复的 `SizingRequest`。
- 删除测试替身登记，统一使用 `production_registry()`，保留排队、当前提交人及未执行断言。
- 新增参数模型对齐测试，通过 `make api-types` 更新 OpenAPI 和前端类型。

**2. `make check` 结果**

退出码 0，**0 skipped**；4 条依赖契约全部通过。

```text
================= 2276 passed, 8 warnings in 70.54s (0:01:10) ==================
```

末尾输出：

```text
 Test Files  22 passed (22)
      Tests  250 passed (250)
   Start at  08:40:20
   Duration  7.43s (tests 50%, environment 29%, import 20%, transform 1%)
```

**3. 契约变更申请、依赖申请**

无额外申请、无新增依赖。

按正式模型，省略 `dataset_id` 与显式 null 都表示全量。OpenAPI 组件采用 `RescanParameters`，即 `SizingParameters` 的实际别名目标。

**4. 剩余事项与合并状态**

本轮对齐完成，无剩余阻塞。queries、schemas 的禁入契约未放宽。

`MERGE_HEAD` 保持 `5c9bc2f04a4737ba4a85408c14bc73632806183a`；Git 索引哈希前后相同。未暂存、未提交，合并状态保留。

**5. 本轮先红后绿**

| 测试 | 记录 |
|---|---|
| `test_all_endpoints_with_unreadable_storage_roots` | 红→绿：复现重复登记，删除替身后通过。 |
| `test_sizing_openapi_matches_production_parameters` | 红→绿：发现仍引用重复模型，改用正式模型后通过；另验证默认全量及非法参数 422。 |
| `test_rescan_submits_current_actor_and_never_executes` | 改用生产登记后初绿，验证 queued、无启动时间/进度/结果。 |
| `test_sizing_submits_all_or_one_without_worker_import` | 改用生产登记后初绿，全量和单数据集均仅排队，持久记录一致。 |