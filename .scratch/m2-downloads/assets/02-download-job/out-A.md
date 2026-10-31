## 1. 改动清单

**交付的是契约骨架，不是可运行的下载功能。** 下载执行函数仍抛出 `NotImplementedError`；新增验收测试全部跳过。改动留在 `t/m2-downloads` 工作区，未暂存、未提交。

- `src/rdp/jobs/downloads/job.py`：新增下载参数模型、执行器及 aria2 进程/RPC、curl、校验、调参等可注入边界的契约。
- `src/rdp/jobs/registry.py`：登记 `download` 作业类型，恢复方式为 `resume`，并提供依赖注入入口。
- `src/rdp/infra/config.py`：增加 `jobs.aria2c_path`，默认值为 `aria2c`。
- `src/rdp/infra/db/migrations/versions/v0013_download_adjustments.py`：新增调参与下载状态表迁移，`down_revision` 指向 `0012_scene_task_index`。
- `src/rdp/jobs/models.py`：声明与新迁移对应的 ORM 表。
- `tests/test_download_job_contract.py`：新增逐项跳过的契约测试，包括本机 aria2c 与回环 HTTP 服务器集成测试。
- `tests/test_api_database.py`：适配新增迁移后的版本检查。
- `tests/test_audit_migration.py`：将新表排除出历史 0003 表视图。
- `tests/test_data_origin_migration.py`：适配历史迁移包和当前 head。
- `tests/test_dataset_api_contract.py`：更新当前迁移 head 预期。
- `tests/test_datasets_index.py`：更新当前迁移 head 预期。
- `tests/test_db_migration.py`：更新 head 及模拟未来迁移的版本链。
- `tests/test_jobs_migration.py`：更新迁移链和当前 head 预期。
- `tests/test_jobs_registry.py`：更新生产登记类型数量。
- `tests/test_jobs_scheduling_config.py`：加入下载类型登记预期。
- `tests/test_jobs_storage.py`：更新生产类型数量预期。
- `tests/test_navwrite_audit_migration.py`：更新当前迁移 head 预期。
- `tests/test_ops_cli.py`：更新迁移命令输出预期。
- `tests/test_ops_runtime.py`：更新生产登记类型数量。
- `tests/test_ops_version_migration.py`：更新当前迁移 head 预期。
- `tests/test_rebuild_audit_migration.py`：更新当前迁移 head 预期。

## 2. `make check`

最后一次运行的命令：

```bash
make check > /tmp/m2-download-final.log 2>&1; code=$?; tail -25 /tmp/m2-download-final.log; exit "$code"
```

末尾输出原文：

```text
SKIPPED [1] tests/test_download_job_contract.py:168: 契约骨架待实现
=========== 2665 passed, 33 skipped, 8 warnings in 88.61s (0:01:28) ============
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.pL9QXPJTCB/openapi.json → /tmp/tmp.pL9QXPJTCB/schema.d.ts [121.4ms]
OpenAPI 与生成类型均未过期
[8/11] tsc
src/web/node_modules/.bin/tsc --project src/web/tsconfig.json --noEmit
[9/11] ESLint
cd src/web && node_modules/.bin/eslint . --max-warnings 0
[10/11] Prettier
cd src/web && node_modules/.bin/prettier --check .
Checking formatting...
All matched files use Prettier code style!
[11/11] Vitest
cd src/web && node_modules/.bin/vitest run

 RUN  v5.0.5 /home/shawn/桌面/robot-data-platform.wt/m2-downloads/src/web


 Test Files  39 passed (39)
      Tests  370 passed (370)
   Start at  20:19:46
   Duration  11.55s (tests 55%, import 22%, environment 21%, transform 1%)

```

命令退出码为 0。33 项跳过的是下载契约清单；因此检查链全绿**不代表下载验收已通过**。手工创建的临时日志已删除。

## 3. 契约变更申请、依赖申请

- **契约变更申请**：建议允许 aria2 的 `addUri` 指向 worker 在 `127.0.0.1` 上启动的受控下载网关，而不是直接指向镜像 `resolve` URL。网关再向镜像及经逐跳校验的 CDN 请求数据。原因和替代方案的风险见第 4 块；这与工单要求 aria2 直接接收镜像 URI 不一致，**尚需评审决定，当前骨架未解决这一冲突**。
- **依赖申请**：无。

## 4. 拿不准、需要评审决定的地方

1. **aria2 重定向拦截——主要未解决风险。** 仅由 worker 预解析一次跳转有竞态：aria2 真正请求时，服务端仍可能返回新的官方站重定向。本机 `aria2c --help=all` 中未找到足以证明可逐跳阻止该行为的选项。建议的回环网关应逐跳检查每次真实响应，拒绝 `huggingface.co` 及其子域、非 HTTPS 和带用户信息的地址，允许合法镜像/CDN 跳转；支持 Range 续传，并且只向镜像发送 token。aria2 自身仍显式不配置代理。该方案改变了 `addUri` 的 URI，需批准后才能作为实现契约。

2. **curl 跳转处理。** 不使用 `-L`；对每次响应手动检查 `Location` 后再发下一跳，设置有限跳转和重试预算，遇官方站立即失败。token 经受控 stdin 配置传入 curl，不放命令行；跨域不转发 token。为维持*总*限速，建议兜底期间暂停 aria2 传输；限速发生变化时停止并以 `-C -` 和新限速重启 curl。这些行为仍需实现和验收。

3. **校验缓存。** 建议使用暂存目录下的 `.rdp-verified-v1.json`，记录版本、相对路径、预期算法/散列/大小以及设备号、inode、`mtime_ns`、`ctime_ns`；完全匹配才复用，否则重新校验。写入采用同目录临时文件和原子替换，不跟随软链接。它是避免重复散列的优化，**不是抵抗拥有暂存目录写权限者的篡改证明**。

4. **429 降速。** 契约采用每连续 3 次 429 将实际文件并发减半、最低为 1；无新 429 的每个 60 秒稳定期增加 1，最多恢复到用户请求值。每组事件/稳定期只能消费一次；继续使用 aria2 的配置重试间隔。需要在实现时验证可靠的 429 观测来源；不能假设普通 aria2 状态 RPC 一定暴露 HTTP 状态码。上面的受控网关可作为候选观测点。

5. **接口放置。** 建议本票只定义和持久化调参通道；提交下载复用 M0 通用作业提交接口，下载专属的状态读取和调参 HTTP 入口放第 03 张。这样不修改已有 HTTP 接口；第 03 张页面从专属状态读取实际值、速度和文件计数。

6. **数据库结构。** 0013 只新建 `download_adjustments`，不修改既有表。每个作业一行，以 `job_id` 外键关联 `jobs.job_id`；保存请求/应用版本、请求/实际并发和限速，以及速度、总文件数、完成数、失败数和跳过数。版本用于防止旧 RPC 确认覆盖新的调整。另需评审：SQLite `INTEGER` 有上界，而 spec 的非零限速只规定下界；极大整数的表示策略尚未定。

7. **续跑计数与并发上限。** 恢复时需要持久化每个作业已计数的文件检查点，并在上报 M0 累计进度前持久化，以免崩溃后重复计数；具体检查点落盘和恢复顺序仍须在实现阶段完成并测试。另外，登记表的下载类型**默认**并发为 1，但现有配置允许按类型覆盖；骨架目前尚未强制禁止把下载类型覆盖到大于 1，已列为跳过测试。

8. **生产装配状态。** 生产登记表已包含骨架类型，但 worker 尚未装配实际下载依赖，执行器也未实现；评审通过并完成第二步实现前，不应把该登记视为可投入运行的下载能力。