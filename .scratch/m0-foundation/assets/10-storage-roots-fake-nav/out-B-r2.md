**1. 改动清单**

本轮相对 `refs/rdp/m0-10/B-r1-done` 只改以下 5 个文件，未暂存、未提交：

| 文件 | 改动 |
|---|---|
| [src/rdp/infra/storage.py](/home/shawn/桌面/robot-data-platform.wt/m0-10-storage-roots-fake-nav/src/rdp/infra/storage.py) | 第 4 列改为原样字符串；只接受精确 `/`；保留空来源列；结构错误标明列位置。 |
| [tests/test_mountinfo_sample.py](/home/shawn/桌面/robot-data-platform.wt/m0-10-storage-roots-fake-nav/tests/test_mountinfo_sample.py) | 新增真实副本、根字段、错误定位和来源文本回归，共 18 个用例。 |
| [tests/fixtures/storage/mountinfo-sample.txt](/home/shawn/桌面/robot-data-platform.wt/m0-10-storage-roots-fake-nav/tests/fixtures/storage/mountinfo-sample.txt) | 保存 58 行副本，仅替换第 49、50 行第 5 列；其余字节不变。 |
| [tests/test_fake_nav.py](/home/shawn/桌面/robot-data-platform.wt/m0-10-storage-roots-fake-nav/tests/test_fake_nav.py) | 将新增文本夹具纳入路径审计。 |
| [tests/nav_path_audit.py](/home/shawn/桌面/robot-data-platform.wt/m0-10-storage-roots-fake-nav/tests/nav_path_audit.py) | 为 nsfs 标识的纯测试输入和精确断言增加白名单，不豁免文件访问。 |

**2. `make check`**

命令：`make check`，退出码 **0**。

pytest **1811 passed、0 skipped**；Vitest **243 passed、0 skipped**。

pytest 汇总原文：

```text
================= 1811 passed, 1 warning in 125.40s (0:02:05) ==================
```

末尾原文：

```text
[11/11] Vitest
cd src/web && node_modules/.bin/vitest run

 RUN  v5.0.5 /home/shawn/桌面/robot-data-platform.wt/m0-10-storage-roots-fake-nav/src/web


 Test Files  21 passed (21)
      Tests  243 passed (243)
   Start at  22:50:30
   Duration  7.29s (tests 48%, environment 30%, import 21%)
```

状态命令为 `git -c core.quotepath=false status --porcelain --untracked-files=all`；`-c` 只调整中文显示，未修改配置。以下包含前几轮累积改动，前后逐字一致。

运行前：

```text
 M src/rdp/api/storage.py
 M src/rdp/api/storage_schemas.py
 M src/rdp/infra/config.py
 M src/rdp/infra/storage.py
 M src/rdp/jobs/execution.py
 M src/rdp/jobs/registry.py
 M src/rdp/jobs/storage.py
 M src/web/src/api/openapi.json
 M src/web/src/api/storage.test.ts
 M src/web/src/api/storage.ts
 M src/web/src/storage/Pages.test.tsx
 M src/web/src/storage/Pages.tsx
 M src/web/src/storage/queries.ts
 M tests/conftest.py
 M tests/fixtures/nav/manifest.schema.json
 M tests/nav_manifest.py
 M tests/test_fake_nav.py
 M tests/test_jobs_storage.py
 M tests/test_storage.py
 M tests/test_storage_api.py
 M tests/test_storage_config.py
?? src/rdp/jobs/_storage_requirements.py
?? src/web/src/storage/testSupport.ts
?? tests/fixtures/nav/manifest.json
?? tests/fixtures/nav/samples/nav/按任务/EgoProDemo/原始路径.json
?? tests/fixtures/nav/samples/nav/按任务/EgoProDemo/子任务.json
?? tests/fixtures/nav/samples/nav/按任务/EgoProDemo/数据集信息.json
?? tests/fixtures/nav/samples/nav/按任务/EgoProStandard/原始路径.json
?? tests/fixtures/nav/samples/nav/按任务/EgoProStandard/子任务.json
?? tests/fixtures/nav/samples/nav/按任务/EgoProStandard/数据集信息.json
?? tests/fixtures/nav/samples/nav/按任务/R1_lite_table_withdrawing_mcap/原始路径.json
?? tests/fixtures/nav/samples/nav/按任务/R1_lite_table_withdrawing_mcap/子任务.json
?? tests/fixtures/nav/samples/nav/按任务/R1_lite_table_withdrawing_mcap/数据集信息.json
?? tests/fixtures/nav/samples/nav/按任务/agibot_world_alpha/原始路径.json
?? tests/fixtures/nav/samples/nav/按任务/agibot_world_alpha/子任务.json
?? tests/fixtures/nav/samples/nav/按任务/agibot_world_alpha/数据集信息.json
?? tests/fixtures/nav/samples/nav/按任务/libero_10/原始路径.json
?? tests/fixtures/nav/samples/nav/按任务/libero_10/子任务.json
?? tests/fixtures/nav/samples/nav/按任务/libero_10/数据集信息.json
?? tests/fixtures/nav/samples/nav/按格式/lerobot/3.0/EgoProDemo/原始路径.json
?? tests/fixtures/nav/samples/nav/按格式/lerobot/3.0/EgoProDemo/子任务.json
?? tests/fixtures/nav/samples/nav/按格式/lerobot/3.0/EgoProDemo/数据集信息.json
?? tests/fixtures/nav/samples/nav/按格式/lerobot/3.0/libero_10/原始路径.json
?? tests/fixtures/nav/samples/nav/按格式/lerobot/3.0/libero_10/子任务.json
?? tests/fixtures/nav/samples/nav/按格式/lerobot/3.0/libero_10/数据集信息.json
?? tests/fixtures/nav/samples/nav/按格式/mcap/EgoProStandard/原始路径.json
?? tests/fixtures/nav/samples/nav/按格式/mcap/EgoProStandard/子任务.json
?? tests/fixtures/nav/samples/nav/按格式/mcap/EgoProStandard/数据集信息.json
?? tests/fixtures/nav/samples/nav/按格式/mcap/R1_lite_table_withdrawing_mcap/原始路径.json
?? tests/fixtures/nav/samples/nav/按格式/mcap/R1_lite_table_withdrawing_mcap/子任务.json
?? tests/fixtures/nav/samples/nav/按格式/mcap/R1_lite_table_withdrawing_mcap/数据集信息.json
?? tests/fixtures/nav/samples/nav/按格式/tar、tar.gz（含分卷）/agibot_world_alpha/原始路径.json
?? tests/fixtures/nav/samples/nav/按格式/tar、tar.gz（含分卷）/agibot_world_alpha/子任务.json
?? tests/fixtures/nav/samples/nav/按格式/tar、tar.gz（含分卷）/agibot_world_alpha/数据集信息.json
?? tests/fixtures/nav/samples/roots/dataset1/libero_v3/libero_10/meta/info.json
?? "tests/fixtures/nav/samples/roots/dataset2/EgoProDemo/EgoProStandard-body/lerobot/Adjust Shelf Labels/5800ed0b-0fd7-438d-89a8-ef23de66723d/meta/info.json"
?? tests/fixtures/storage/mountinfo-sample.txt
?? tests/nav_path_audit.py
?? tests/test_mountinfo_sample.py
```

运行后：

```text
 M src/rdp/api/storage.py
 M src/rdp/api/storage_schemas.py
 M src/rdp/infra/config.py
 M src/rdp/infra/storage.py
 M src/rdp/jobs/execution.py
 M src/rdp/jobs/registry.py
 M src/rdp/jobs/storage.py
 M src/web/src/api/openapi.json
 M src/web/src/api/storage.test.ts
 M src/web/src/api/storage.ts
 M src/web/src/storage/Pages.test.tsx
 M src/web/src/storage/Pages.tsx
 M src/web/src/storage/queries.ts
 M tests/conftest.py
 M tests/fixtures/nav/manifest.schema.json
 M tests/nav_manifest.py
 M tests/test_fake_nav.py
 M tests/test_jobs_storage.py
 M tests/test_storage.py
 M tests/test_storage_api.py
 M tests/test_storage_config.py
?? src/rdp/jobs/_storage_requirements.py
?? src/web/src/storage/testSupport.ts
?? tests/fixtures/nav/manifest.json
?? tests/fixtures/nav/samples/nav/按任务/EgoProDemo/原始路径.json
?? tests/fixtures/nav/samples/nav/按任务/EgoProDemo/子任务.json
?? tests/fixtures/nav/samples/nav/按任务/EgoProDemo/数据集信息.json
?? tests/fixtures/nav/samples/nav/按任务/EgoProStandard/原始路径.json
?? tests/fixtures/nav/samples/nav/按任务/EgoProStandard/子任务.json
?? tests/fixtures/nav/samples/nav/按任务/EgoProStandard/数据集信息.json
?? tests/fixtures/nav/samples/nav/按任务/R1_lite_table_withdrawing_mcap/原始路径.json
?? tests/fixtures/nav/samples/nav/按任务/R1_lite_table_withdrawing_mcap/子任务.json
?? tests/fixtures/nav/samples/nav/按任务/R1_lite_table_withdrawing_mcap/数据集信息.json
?? tests/fixtures/nav/samples/nav/按任务/agibot_world_alpha/原始路径.json
?? tests/fixtures/nav/samples/nav/按任务/agibot_world_alpha/子任务.json
?? tests/fixtures/nav/samples/nav/按任务/agibot_world_alpha/数据集信息.json
?? tests/fixtures/nav/samples/nav/按任务/libero_10/原始路径.json
?? tests/fixtures/nav/samples/nav/按任务/libero_10/子任务.json
?? tests/fixtures/nav/samples/nav/按任务/libero_10/数据集信息.json
?? tests/fixtures/nav/samples/nav/按格式/lerobot/3.0/EgoProDemo/原始路径.json
?? tests/fixtures/nav/samples/nav/按格式/lerobot/3.0/EgoProDemo/子任务.json
?? tests/fixtures/nav/samples/nav/按格式/lerobot/3.0/EgoProDemo/数据集信息.json
?? tests/fixtures/nav/samples/nav/按格式/lerobot/3.0/libero_10/原始路径.json
?? tests/fixtures/nav/samples/nav/按格式/lerobot/3.0/libero_10/子任务.json
?? tests/fixtures/nav/samples/nav/按格式/lerobot/3.0/libero_10/数据集信息.json
?? tests/fixtures/nav/samples/nav/按格式/mcap/EgoProStandard/原始路径.json
?? tests/fixtures/nav/samples/nav/按格式/mcap/EgoProStandard/子任务.json
?? tests/fixtures/nav/samples/nav/按格式/mcap/EgoProStandard/数据集信息.json
?? tests/fixtures/nav/samples/nav/按格式/mcap/R1_lite_table_withdrawing_mcap/原始路径.json
?? tests/fixtures/nav/samples/nav/按格式/mcap/R1_lite_table_withdrawing_mcap/子任务.json
?? tests/fixtures/nav/samples/nav/按格式/mcap/R1_lite_table_withdrawing_mcap/数据集信息.json
?? tests/fixtures/nav/samples/nav/按格式/tar、tar.gz（含分卷）/agibot_world_alpha/原始路径.json
?? tests/fixtures/nav/samples/nav/按格式/tar、tar.gz（含分卷）/agibot_world_alpha/子任务.json
?? tests/fixtures/nav/samples/nav/按格式/tar、tar.gz（含分卷）/agibot_world_alpha/数据集信息.json
?? tests/fixtures/nav/samples/roots/dataset1/libero_v3/libero_10/meta/info.json
?? "tests/fixtures/nav/samples/roots/dataset2/EgoProDemo/EgoProStandard-body/lerobot/Adjust Shelf Labels/5800ed0b-0fd7-438d-89a8-ef23de66723d/meta/info.json"
?? tests/fixtures/storage/mountinfo-sample.txt
?? tests/nav_path_audit.py
?? tests/test_mountinfo_sample.py
```

**3. 契约补充和 docstring 改动**

- `MountRecord.filesystem_root`：**`Path → str`**。保存解码后的原文，不规范化；只有精确 `/` 才表示整个文件系统。
- `MountRecord.source` 文档明确允许空串。
- `parse_mountinfo.Args` 补充挂载根也使用四种内核转义解码。
- `Returns` 明确第 4 列保留文本、空来源不替换成 `none`。
- `Raises` 限定结构性错误，并明确错误消息指出字段位置。

均属于本轮要求的契约补充；无新增依赖申请。

**4. 复查结论及拿不准的地方**

无待决事项。复查结论：

- 删除了对第 4 列的绝对路径要求，没有增加 nsfs 特例白名单。
- 删除了 `all(fields)` 的额外非空约束。来源是文件系统专有/dummy 文本，空值仍占据一列；缺列仍由字段数检查拒绝。
- 分隔符从固定六列之后查找，避免误认根文本中的 `-`。
- 保留 LF 分行、四种转义、未知可选字段忽略及叠层规则，未改其他业务逻辑。
- 原件 **58 行对应 57 个不同挂载点**：`binfmt_misc` 有两层，测试明确核对最后一条。
- 空来源用例是补充构造数据，不声称出现在该 58 行副本中。本轮未做真实挂载实验、未读取真实 `/proc`，也没有安装或联网。

**5. 先红后绿**

| 测试 | 第一次运行 | 最终结果 |
|---|---|---|
| `test_real_mountinfo_sample_preserves_nsfs_and_online_disks` | nsfs 第 4 列触发绝对路径错误。修复后又核实了测试行数口径：58 行、去重后 57 条。 | 通过 |
| `test_registered_root_requires_exact_slash` | 5 例已通过字符串修复；根文本 `-` 被误认分隔符而失败。 | 6 例通过 |
| `test_structural_mountinfo_error_names_column` | 7 例缺少正确列号；第 5 列用例已由前一步修复。 | 8 例通过 |
| `test_opaque_mount_source_does_not_poison_registered_disk` | 空串来源失败；`none`、`-` 首次通过原有文本保存逻辑。 | 3 例通过 |
| `test_no_real_mount_access_static` | 新 nsfs 标识被视为路径文本。增加两条精确测试数据白名单，并审计新夹具路径字段。 | 通过 |