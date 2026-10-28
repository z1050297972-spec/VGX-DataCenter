**1. 改动清单**

10 项评审意见已完成，检查全绿。以下覆盖上一轮和本轮；改动未暂存、未提交。

| 文件 | 改动 |
|---|---|
| `src/rdp/infra/config.py` | 实现存储配置、路径转换及登记校验。 |
| `src/rdp/infra/storage.py` | 实现检查；修正 LF 分行、挂载根判断、可中止等待，集中中文映射与依赖校验。 |
| `src/rdp/jobs/registry.py` | 实现存储声明校验和启动前根名核对。 |
| `src/rdp/jobs/_storage_requirements.py` | 集中登记与执行共用的声明校验。 |
| `src/rdp/jobs/storage.py` | 实现前置检查、中文诊断、控制检查点；删除冗余判断。 |
| `src/rdp/jobs/execution.py` | 接入前置检查，并在等待期间响应取消、停止。 |
| `src/rdp/api/storage.py` | 实现只读接口，复用基础层依赖校验。 |
| `src/rdp/api/storage_schemas.py` | 校验响应一致性，通过 OpenAPI 元数据提供中文映射。 |
| `src/web/src/api/openapi.json` | 经 `make api-types` 生成中文映射元数据。 |
| `src/web/src/api/storage.ts` | 实现请求，增加带单位的缓存常量。 |
| `src/web/src/api/storage.test.ts` | 实现请求、错误、超时和取消测试。 |
| `src/web/src/storage/queries.ts` | 实现账号隔离查询，使用具名缓存常量。 |
| `src/web/src/storage/Pages.tsx` | 实现 antd 页面，使用生成的中文映射。 |
| `src/web/src/storage/Pages.test.tsx` | 实现展示、路由、刷新和账号生命周期测试。 |
| `src/web/src/storage/testSupport.ts` | 提供独立响应样本。 |
| `tests/conftest.py` | 实现 `fake_nav` fixture。 |
| `tests/nav_manifest.py` | 实现清单校验、预检和临时目录展开。 |
| `tests/nav_path_audit.py` | 新增常量折叠、路径分量审计及精确白名单。 |
| `tests/test_storage_config.py` | 实现配置测试。 |
| `tests/test_storage.py` | 实现存储测试，补控制字符和子目录 bind 回归。 |
| `tests/test_jobs_storage.py` | 实现作业测试，补等待中取消/停止及中文诊断断言。 |
| `tests/test_storage_api.py` | 实现接口测试，核对生成的中文映射。 |
| `tests/test_fake_nav.py` | 实现夹具测试，补结构化引用、截短说明和静态审计回归。 |
| `tests/fixtures/nav/manifest.schema.json` | 从清单模型生成格式定义。 |
| `tests/fixtures/nav/manifest.json` | 登记来源与布局；补 `meta/episodes`、历史失效子引用，逐份重写截短说明。 |

以下样本路径均以 `tests/fixtures/nav/samples/` 为前缀。本轮保持这 32 份样本 JSON 内容不变。

| 样本文件 | 上一轮生成内容 |
|---|---|
| `nav/按任务/libero_10/原始路径.json` | 保留全部 1 条数据块，替换路径。 |
| `nav/按任务/libero_10/子任务.json` | 保留全部 10 个任务。 |
| `nav/按任务/libero_10/数据集信息.json` | 保留 14 项快照，替换路径。 |
| `nav/按任务/R1_lite_table_withdrawing_mcap/原始路径.json` | 保留全部 3 个批次。 |
| `nav/按任务/R1_lite_table_withdrawing_mcap/子任务.json` | 保留唯一任务及批次引用。 |
| `nav/按任务/R1_lite_table_withdrawing_mcap/数据集信息.json` | 保留 14 项快照，替换路径。 |
| `nav/按任务/EgoProStandard/原始路径.json` | 保留 4 条数据块和跨盘链接。 |
| `nav/按任务/EgoProStandard/子任务.json` | 保留对应 4 个任务及引用。 |
| `nav/按任务/EgoProStandard/数据集信息.json` | 保留 14 项快照，替换路径。 |
| `nav/按任务/EgoProDemo/原始路径.json` | 保留 2 条数据块。 |
| `nav/按任务/EgoProDemo/子任务.json` | 保留对应 2 个任务及引用。 |
| `nav/按任务/EgoProDemo/数据集信息.json` | 保留 14 项快照，替换路径。 |
| `nav/按任务/agibot_world_alpha/原始路径.json` | 保留 4 条数据块及组件链接。 |
| `nav/按任务/agibot_world_alpha/子任务.json` | 保留 task327 及相关引用。 |
| `nav/按任务/agibot_world_alpha/数据集信息.json` | 保留 14 项快照，替换路径。 |
| `nav/按格式/lerobot/3.0/libero_10/原始路径.json` | 保留与规范副本配对的数据块。 |
| `nav/按格式/lerobot/3.0/libero_10/子任务.json` | 保留对应 10 个任务及视图差异。 |
| `nav/按格式/lerobot/3.0/libero_10/数据集信息.json` | 保留一致的 14 项快照。 |
| `nav/按格式/lerobot/3.0/EgoProDemo/原始路径.json` | 保留对应 2 条数据块。 |
| `nav/按格式/lerobot/3.0/EgoProDemo/子任务.json` | 保留对应 2 个任务及视图差异。 |
| `nav/按格式/lerobot/3.0/EgoProDemo/数据集信息.json` | 保留一致的 14 项快照。 |
| `nav/按格式/mcap/EgoProStandard/原始路径.json` | 保留对应 4 条数据块及格式视图目标。 |
| `nav/按格式/mcap/EgoProStandard/子任务.json` | 保留对应 4 个任务及视图差异。 |
| `nav/按格式/mcap/EgoProStandard/数据集信息.json` | 保留一致的 14 项快照。 |
| `nav/按格式/mcap/R1_lite_table_withdrawing_mcap/原始路径.json` | 保留对应 3 个批次。 |
| `nav/按格式/mcap/R1_lite_table_withdrawing_mcap/子任务.json` | 保留对应任务及视图差异。 |
| `nav/按格式/mcap/R1_lite_table_withdrawing_mcap/数据集信息.json` | 保留一致的 14 项快照。 |
| `nav/按格式/tar、tar.gz（含分卷）/agibot_world_alpha/原始路径.json` | 保留对应 4 条数据块及组件链接。 |
| `nav/按格式/tar、tar.gz（含分卷）/agibot_world_alpha/子任务.json` | 保留 task327 及视图差异。 |
| `nav/按格式/tar、tar.gz（含分卷）/agibot_world_alpha/数据集信息.json` | 保留一致的 14 项快照。 |
| `roots/dataset1/libero_v3/libero_10/meta/info.json` | 保留完整真实元信息。 |
| `roots/dataset2/EgoProDemo/EgoProStandard-body/lerobot/Adjust Shelf Labels/5800ed0b-0fd7-438d-89a8-ef23de66723d/meta/info.json` | 保留完整真实元信息，包括 `robot_type=null`。 |

**2. `make check`**

最后命令：

```text
make check
```

退出码 **0**；pytest **1793 passed、0 skipped**，Vitest **243 passed、0 skipped**。前一次尝试停在新测试的集合类型标注，修正后完成全链检查。

pytest 汇总原文：

```text
================= 1793 passed, 1 warning in 125.68s (0:02:05) ==================
```

末尾原文：

```text
[11/11] Vitest
cd src/web && node_modules/.bin/vitest run

 RUN  v5.0.5 /home/shawn/桌面/robot-data-platform.wt/m0-10-storage-roots-fake-nav/src/web


 Test Files  21 passed (21)
      Tests  243 passed (243)
   Start at  22:08:05
   Duration  7.21s (tests 48%, environment 30%, import 21%)
```

状态命令使用 `git -c core.quotepath=false status --porcelain --untracked-files=all`，仅调整中文显示，未修改 Git 配置。前后输出逐字相同。

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
?? tests/nav_path_audit.py
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
?? tests/nav_path_audit.py
```

**3. 契约变更、依赖申请及文档修改**

额外待批准的契约变更申请：**无**。依赖申请：**无**。

按评审要求完成的接口补充：

- `StorageAccessChecker.check` 和 `check_storage_before_job` 增加必填关键字 `checkpoint: Callable[[], None]`。
- `MountRecord` 增加 `filesystem_root`，保存 mountinfo 第 4 列。
- 基础层公开 `validate_mount_inspector`，供 API 和存储检查共用。

docstring/TSDoc 修改：

| 位置 | 修改内容 |
|---|---|
| `parse_mountinfo.Args` | 明确“记录仅以 LF 分隔”，其他所列字符属于字段内容。 |
| `LinuxMountSource.read_mountinfo.Returns` | 补充“不转换 CR 或 CRLF”。 |
| `MountRecord.Attributes` | 增加 `filesystem_root` 的含义。 |
| `MountInspector.inspect.Returns` | 补充挂载根必须为 `/`，不接受子目录 bind。 |
| `StorageAccessChecker.check` | 补充 checkpoint 参数、控制异常传播、放弃后的副作用及 50 ms 等待片段。 |
| `check_storage_before_job` | 补充 checkpoint、取消/停止异常；Side Effects 明确启动 daemon 线程；时间语义覆盖等待期间。 |
| `execute_job.Side Effects` | “检查前后”改为“检查前后及等待中”。 |
| `validate_mount_inspector` | 新增完整六项契约。 |
| `useStorageRoots.@timeSemantics` | 使用 `STORAGE_STALE_TIME_MS`、`STORAGE_GC_TIME_MS` 说明零缓存时间。 |
| `NavManifest.Attributes`（上一轮） | “非数据集目录骨架”改为“非数据集目录结构”，无含义变化。 |

**4. 需要评审决定的地方**

无新增待决事项。

- 中文映射只在后端定义一次，通过生成的 OpenAPI `x-display-labels` 元数据供页面使用；没有新增 HTTP 响应字段。
- 上一轮采用一次性样本生成脚本，`/tmp/rdp10-generate.py` 已删除；本轮没有留下临时脚本。
- 已开始的内核读取仍无法强行中止；取消/停止会结束调用方等待，并禁止迟到线程继续后续检查。
- 真机核对及浏览器演示沿用执行线已通过的结果，本轮未访问真实存储或启动服务器。

**5. 先红后绿**

本轮：

| 项目 | 测试 | 第一次运行结果 |
|---|---|---|
| 1 | `test_non_lf_characters_do_not_split_mount_records` | 4 例均失败：字段被切开；CR 还被读取适配器转换。修复后通过。 |
| 2 | `test_waiting_storage_check_obeys_control_signal` | 停止、取消两例均未在 0.75 秒内返回。修复后通过。 |
| 3 | `test_subdirectory_bind_is_source_mismatch` | ext4、NFS 两例均错误在线。修复后通过。 |
| 4 | `test_structured_references_exist_or_are_recorded_missing` | 缺少 `meta/episodes`，且 alpha 子引用未逐条登记失效。补齐后通过。 |
| 5 | `test_truncation_notes_describe_each_dataset` | 说明没有自身数据集名，并套用了无关描述。改写后通过。 |
| 6 | `test_offline_fails` | 三种 `actual` 都是英文枚举值。统一中文映射后通过。 |
| 10 | `test_mount_path_audit_detects_literal_and_computed_paths` | 漏检 `Path("/mnt")`。加强审计后通过。 |

第 7–9 项为规范修改，使用对应既有测试回归；精确白名单补充测试首次通过。

上一轮按文件汇总：

| 测试文件 | 首次结果及直接通过原因 |
|---|---|
| `test_storage_config.py` | 配置转换与主要校验先失败再实现；路径边界、超时范围、冻结模型和诊断隐藏首次通过，因为复用了既有校验或批准模型声明。 |
| `test_storage.py` | 解析、适配器、异常分类和超时主要用例先失败；没挂载、设备不匹配、可选字段、访问顺序相关后续分支等首次通过，已由前一切片覆盖。 |
| `test_jobs_storage.py` | 拒绝写只读根、离线、登记校验和等待后控制检查先失败；正常路径、空声明、许可顺序、恢复及资源隔离首次通过，复用了已实现检查和既有执行器。只读失败测试最初误读结果字段，修正后先确认业务失败再实现。 |
| `test_storage_api.py` | 装配、返回字段、未配置状态、响应一致性先失败；认证、强制改密、错误映射及 OpenAPI 首次通过，沿用了现有入口设施。 |
| `test_fake_nav.py` | 展开、链接、占位符、清单及安全预检先失败；布局细节、真实元信息、追溯、隔离等首次通过，因为样本已按选择生成，展开逻辑已覆盖。 |
| `api/storage.test.ts` | 请求函数先失败；超时、取消、默认传输直接复用既有设施。500 用例最初误用了不支持 500 的样本工厂，修正合法响应后通过。 |
| `storage/Pages.test.tsx` | 页面、字段、原因、按钮、诊断和加载状态先失败；无轮询、路由重入及部分原因展示已由前一切片覆盖。账号切换用例最初在 401 后仍模拟已登录，修正会话失效模拟后通过。 |