状态：未完成

本轮批准的 token 审计项已实现，最后一次 `make check` 全绿。**但我不能标记整张工单全部完成**：收尾核对时发现预览暂存大小和作业详情参数展示仍有两处与工单不符，见第 4 节。

## 1. 改动清单

以下为整张票当前工作区的全部改动，每个文件一行：

- `src/rdp/accounts/service.py`：新增作业事务内的管理员身份重验。
- `src/rdp/api/__init__.py`：注册下载 token 路由。
- `src/rdp/api/download_tokens.py`：管理员设置、清除和查询 token，追加脱敏操作日志。
- `src/rdp/api/jobs.py`：下载、预览、调参和暂存作业接口。
- `src/rdp/audit/types.py`：追加设置及清除下载 token 的审计操作码。
- `src/rdp/infra/db/migrations/versions/v0015_download_staging.py`：新增暂存快照表迁移。
- `src/rdp/jobs/_download_cleanup.py`：清理作业入队权限及占用策略。
- `src/rdp/jobs/_inherited_fds.py`：作业线程限定的协调锁描述符继承。
- `src/rdp/jobs/downloads/_delete_child.py`：受限暂存删除子进程。
- `src/rdp/jobs/downloads/cleanup.py`：清理参数、下载互斥包装和清理作业执行器。
- `src/rdp/jobs/downloads/coordination.py`：下载与清理的进程锁。
- `src/rdp/jobs/downloads/preview.py`：worker 下载预览及状态目录摘要。
- `src/rdp/jobs/downloads/staging.py`：worker 暂存扫描及数据库快照。
- `src/rdp/jobs/models.py`：暂存扫描快照模型。
- `src/rdp/jobs/processes.py`：允许下载工具显式继承协调锁，不继承 worker 锁。
- `src/rdp/jobs/registry.py`：登记预览、暂存扫描和清理作业。
- `src/rdp/jobs/service.py`：通用提交和重提路径的清理权限及占用检查。
- `src/web/src/accounts/Pages.test.tsx`：适配管理员页新增 token 状态请求。
- `src/web/src/accounts/Pages.tsx`：管理员 token 控件及外壳下载导航。
- `src/web/src/api/downloadAdjustments.ts`：下载调参客户端。
- `src/web/src/api/downloadToken.ts`：管理员 token 客户端。
- `src/web/src/api/downloads.ts`：下载、预览和暂存作业客户端。
- `src/web/src/api/openapi.json`：通过 `make api-types` 生成。
- `src/web/src/api/schema.d.ts`：通过 `make api-types` 生成。
- `src/web/src/audit/search.ts`：新增 token 审计操作的中文标签。
- `src/web/src/downloads/Pages.test.tsx`：下载表单、预览、路由和删除确认测试。
- `src/web/src/downloads/Pages.tsx`：下载表单及确认流程。
- `src/web/src/downloads/Preview.tsx`：预览和诊断展示。
- `src/web/src/downloads/Staging.tsx`：暂存快照、刷新和删除确认。
- `src/web/src/downloads/search.ts`：下载页搜索参数校验。
- `src/web/src/jobs/DownloadDetail.tsx`：下载速度、计数及动态调参区块。
- `src/web/src/jobs/Pages.test.tsx`：下载详情和调参测试。
- `src/web/src/jobs/Pages.tsx`：接入下载详情区块。
- `src/web/src/router.tsx`：登记下载页路由。
- `tests/test_api_database.py`：适配新迁移 head。
- `tests/test_audit_migration.py`：历史审计迁移夹具排除新表。
- `tests/test_data_origin_migration.py`：适配新迁移 head 和历史夹具。
- `tests/test_dataset_api_contract.py`：适配新迁移 head。
- `tests/test_datasets_index.py`：适配新迁移 head。
- `tests/test_db_migration.py`：适配新迁移 head 及未来版本夹具。
- `tests/test_download_page_api.py`：下载页面相关真实应用和 worker 关键测试。
- `tests/test_jobs_migration.py`：适配新迁移链。
- `tests/test_jobs_registry.py`：适配新增作业类型。
- `tests/test_jobs_scheduling_config.py`：适配新增作业类型。
- `tests/test_jobs_storage.py`：适配新增作业类型。
- `tests/test_navwrite_audit_migration.py`：适配迁移 head 及追加审计操作码。
- `tests/test_ops_cli.py`：适配新迁移 head。
- `tests/test_ops_runtime.py`：适配新增作业类型。
- `tests/test_ops_version_migration.py`：适配新迁移 head。
- `tests/test_rebuild_audit_migration.py`：适配新迁移 head。

## 2. `make check`

最后一次命令为 `make check`，退出码 0，末尾输出原样如下：

```text
 RUN  v5.0.5 /home/shawn/桌面/robot-data-platform.wt/m2-downloads/src/web


 Test Files  40 passed (40)
      Tests  378 passed (378)
   Start at  02:12:28
   Duration  10.74s (tests 57%, import 22%, environment 19%, transform 1%, setup 1%)
```

本轮第一次全链检查因既有审计操作码集合测试尚未纳入两个新增值而失败；更新该测试后重跑全绿。没有并发运行多份 `make check`。

## 3. 依赖申请

无。

## 4. 设计选择、未完成项和风险

**仍未完成的工单项：**

1. [Preview.tsx](src/web/src/downloads/Preview.tsx#L126) 将 `capacity.complete_bytes` 标为“已在暂存区”。该值只累计大小已完整匹配的文件，**不含未完成的续传文件**；因此不能当作暂存区实际总大小。
2. [DownloadDetail.tsx](src/web/src/jobs/DownloadDetail.tsx#L42) 只显示实际并发和总限速，尚未显示工单要求的其余下载参数。

其余主要设计选择：

- token 由 Web 写入状态目录，权限 `0600`；设置和清除各追加一条新操作码的日志，不记录 token、状态、IP 或请求编号。现有日志模型要求对象字段，因此该字段重复操作人的账号身份，不保存额外凭据属性。
- token 文件替换与 SQLite 日志提交处于同一个请求流程，但**文件系统与数据库不是同一个原子事务**；若文件替换后数据库提交失败或进程崩溃，二者可能不一致。
- 预览由 worker 复用 `build_plan`，摘要保存在状态目录；暂存列表由 worker 扫描后存数据库。Web 不读取存储根。
- 暂存占用按存储根、仓库类型和仓库保守判断；删除入队后，worker 仍在进程锁内重新检查，不能把旧快照当作删除许可。
- 迁移使用 `0015_download_staging`，暂接 `0013_download_adjustments`，按你的说明留待执行线合并时统一改号。
- 浏览器演练按你的最新指示交由执行线；本轮未访问网络。

## 5. 先红后绿

以下为本票新增测试各自首次运行的结果；随后均通过：

- `test_submit_download`：405，下载提交接口尚不存在。
- `test_download_adjustment`：404，调参接口尚不存在。
- `test_token_admin_only_and_never_echoed`：404，token 接口尚不存在；后续扩展时也先复现了非法换行 token 被接受。
- `test_submit_and_read_preview`：405，预览提交接口尚不存在。
- `test_staging_list_worker_snapshot`：无法导入尚不存在的快照模型。
- `test_staging_delete_admission`：成员通用提交错误地返回 201，而非 403。
- `test_delete_staging_worker`：无法导入尚不存在的删除子进程模块；后续扩展时先复现了排队作业可误删。
- `test_token_changes_are_audited_without_secret`：未查到设置和清除两条操作日志。
- `表单默认隐藏高级参数，展开后显示默认值和范围`：下载路由尚不存在。
- `预览展示版本、数据集元数据和容量快照`：下载路由尚不存在。
- `真实 Router 解析 preview_job_id 并按编号读取预览`：下载路由尚不存在。
- `管理员删除暂存前必须确认，取消不发送请求，使用中目录不能删除`：删除按钮尚不存在。
- `下载详情展示速度与计数，并提交并发和限速后等待实际生效`：下载详情速度尚未显示。

改动均留在工作区，未执行 `git add` 或提交。