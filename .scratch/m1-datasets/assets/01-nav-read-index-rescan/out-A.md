**1. 改动清单**

已完成契约骨架，改动留在工作区，未暂存、未提交。

- `Makefile`：仅将 pytest 改为 `-n auto`。
- `src/rdp/jobs/datasets/__init__.py`：声明模块职责和分层边界。
- `src/rdp/jobs/datasets/catalog.py`：两张不可变登记表及扫描预算。
- `src/rdp/jobs/datasets/types.py`：读取快照、入口、链接、数据块和面板类型。
- `src/rdp/jobs/datasets/fingerprint.py`：L12 指纹值对象及采集契约。
- `src/rdp/jobs/datasets/reading.py`：宽松读取、路径推导和记录大小提取契约。
- `src/rdp/jobs/datasets/panel.py`：①②组检查、规则码和聚合契约。
- `src/rdp/jobs/datasets/models.py`：八张索引表的列、约束和索引声明。
- `src/rdp/jobs/datasets/scan_types.py`：两段扫描、替换计划及发布结果类型。
- `src/rdp/jobs/datasets/index.py`：基线读取、替换计划和事务执行契约。
- `src/rdp/jobs/datasets/rescan.py`：作业登记、两段执行与提交复核契约。
- `src/rdp/jobs/datasets/triggers.py`：启动及每 600 秒触发契约。
- `src/rdp/jobs/execution.py`：新增可选提交轮询回调字段。
- `src/rdp/jobs/service.py`：新增系统身份提交函数骨架。
- `src/rdp/infra/db/migrations/pending/__init__.py`：非活动迁移目录。
- `src/rdp/infra/db/migrations/pending/v0007_dataset_index.py`：升级、拒绝降级契约。
- `tests/test_datasets_reading.py`：读取和记录值测试清单。
- `tests/test_datasets_fingerprint.py`：L12 测试清单。
- `tests/test_datasets_panel.py`：①②组逐项测试清单。
- `tests/test_datasets_rescan.py`：扫描、触发、锁及多进程测试清单。
- `tests/test_datasets_index.py`：原子替换、迁移及第 02 张字段测试清单。
- `tests/test_ops_version_migration.py`：保留活动 head 检查，允许隔离的 pending 迁移。
- `tests/setup_support.py`：消除假服务初始化与故障退出的竞争。
- `tests/test_jobs_scheduling.py`：等待终态及资源归还后再断言。

新增测试共 **79 项，全部使用 `pytest.skip`**。新增业务函数和迁移函数均只有 docstring 与 `raise NotImplementedError`。

**2. `make check`**

最终版本连续三次全绿，均使用 32 个 pytest worker。最后一次命令：

```bash
make check > /tmp/m1-01-check-final-3.log 2>&1
```

退出码 `0`，末尾输出原样如下：

```text
================ 2103 passed, 79 skipped, 32 warnings in 36.30s ================
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.554sDUF6ae/openapi.json → /tmp/tmp.554sDUF6ae/schema.d.ts [70.3ms]
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

 RUN  v5.0.5 /home/shawn/桌面/robot-data-platform.wt/m1-01-nav-read-index-rescan/src/web


 Test Files  22 passed (22)
      Tests  250 passed (250)
   Start at  03:28:32
   Duration  7.37s (tests 49%, environment 29%, import 21%)
```

32 条 warning 均为现有 TestClient 依赖弃用提示。临时检查日志已清理。

**3. 契约变更申请、依赖申请**

增量契约申请：

- `ExecutorDependencies.poll_submissions`：可选内部提交回调，默认 `None`，用于接入扫描触发器。
- `JobService.submit_system(...)`：系统身份的非每日提交入口，复用作业与审计事务。

不改变 M0 每日调度、身份、恢复和取消语义。

依赖申请：**无**。

**4. 骨架关卡及拿不准的地方**

**① 数据集索引表结构**

完整类型、空值和约束声明见 [models.py](/home/shawn/桌面/robot-data-platform.wt/m1-01-nav-read-index-rescan/src/rdp/jobs/datasets/models.py)。

| 表 | 列 | 键、约束与索引 |
|---|---|---|
| `dataset_scans` | `scan_id, job_id, scope, requested_dataset_id, started_at, navigation_finished_at, committed_at, navigation_elapsed_s, lock_held_s, storage_stage, is_current` | PK `scan_id`；编号、范围与请求编号配对、非负耗时、阶段枚举、布尔检查；部分唯一索引保证至多一个当前代次 |
| `dataset_scan_roots` | `scan_id, name, path, uuid, nfs_export, writable, online, reason, checked_at` | PK `(scan_id,name)`；扫描 FK；挂载来源互斥；在线、离线原因和检查时间配对 |
| `datasets` | `dataset_id, name, canonical_entry_path, scan_id, fingerprint, data_origin, recorded_size_bytes, size_bytes, size_checked_at` | PK `dataset_id`；扫描 FK；来源固定 `unknown`；大小非负、统计时间配对；索引 `(name,dataset_id)`、`scan_id` |
| `dataset_entries` | `path, dataset_id, scan_id, view, format, version, name, dataset_roots, provenance_present, fingerprint, recorded_size_bytes, size_bytes, size_checked_at, aria2_count, incomplete_count` | PK `path`；可空数据集 FK、扫描 FK；视图/格式/版本组合检查；大小、计数和时间配对；树索引 `(view,format,version,name)`，另索引两个 FK |
| `dataset_documents` | `entry_path, name, payload, schema_version, sha256` | PK `(entry_path,name)`；入口 FK；三文件名、有效版本、64 位摘要检查 |
| `dataset_links` | `entry_path, ordinal, name, source_path, source_type, derived_entry_path, observed_target, storage_root_name, status, checked_at, size_bytes, size_checked_at` | PK `(entry_path,ordinal)`；入口 FK；序号非负、状态枚举、检查/统计时间配对；索引 `(status,entry_path)` |
| `dataset_sources` | `entry_path, ordinal, source_id, original_path, direct_path, derived_entry_path, format, version, validation_status, storage_root_name, status, checked_at, robot_type, fps, fps_rounded, codebase_version, meta_checked_at` | PK `(entry_path,ordinal)`；入口 FK；状态/时间及 FPS 检查；索引 `(source_id,entry_path)`、`(robot_type,entry_path)`、`(fps_rounded,entry_path)` |
| `dataset_findings` | `owner_key, group, severity, rule, scan_id, total, samples` | PK `(owner_key,group,severity,rule)`；扫描 FK；组别、级别、正计数检查；索引 `(group,severity,rule)`、`scan_id` |

入口删除级联删除文档、链接和数据块；仍被引用的扫描代次不得删除。所有时刻使用 `UTCDateTime`。第 02 张需要的字段已包含；迁移仍在 `pending/`。

**② L12 指纹签名**

```python
def fingerprint_dataset(
    nav_root: Path,
    dataset_id: str | None,
    *,
    known_entry_paths: tuple[str, ...],
    checkpoint: Callable[[], None],
) -> DatasetFingerprint:
```

返回深度不可变、可比较、可通过 Pydantic JSON 往返序列化的值对象。覆盖所有入口的 JSON 原字节摘要、完整条目名及 `readlink`；保留旧入口路径以检出删除、改名和改身份。不可验证状态不能用于证明“未改变”。

**③ 两张登记表的位置**

放在 `catalog.py` 的不可变代码常量中：

- 格式目录：`lerobot`、`mcap`、压缩包目录到 `archives` 的映射。
- 非数据集目录：包含 L7 的 `已移除`。

理由：它们决定导航协议和扫描边界，应随规则评审，不能由部署配置静默改变。

**设计调整和评审关注点**

- 模块采用 `rdp.jobs.datasets`，直接受现有 import-linter 合约约束，无需修改受保护配置。
- 原子发布：最终复核与事务提交连续持锁；失败保留旧索引。
- 第二段契约明确返回 `NOT_RUN`；本次仍统一只交函数骨架。
- 完全无法识别编号的入口采用可空 `dataset_id`、按路径展示；首次不可读只存损坏占位，不能覆盖已有可用投影。建议关卡重点核对这项。
- `VGX_video` 仍按未知顶层目录报告，未擅自登记。

多进程暴露的是两处**时序竞争**，未发现跨测试共享目录或端口冲突：假服务尚未安装信号处理器就被终止，以及作业终态提交早于资源归还。均已在测试侧修正，未关闭 xdist、未放宽断言。