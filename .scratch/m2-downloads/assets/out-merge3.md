状态：全部完成

13 个冲突文件已合并：

- `src/rdp/api/__init__.py`：保留请求体限制、监控采样及双方路由。
- `src/rdp/api/jobs.py`：保留 M2 接口，接入 main 的诊断脱敏。
- `src/rdp/jobs/service.py`：统一角色校验，保留暂存占用检查；M1、M2 专用确认允许成员操作。
- `tests/test_api_database.py`：模拟后续迁移接续 0016。
- `tests/test_data_origin_migration.py`：更新历史迁移包排除范围。
- `tests/test_dataset_api_contract.py`：升级终点统一为 0016。
- `tests/test_datasets_index.py`：当前版本统一为 0016。
- `tests/test_db_migration.py`：统一 head、备份及后续迁移期望。
- `tests/test_jobs_migration.py`：补齐双方完整迁移链。
- `tests/test_navwrite_audit_migration.py`：保留历史审计验证，更新升级终点。
- `tests/test_ops_cli.py`：更新迁移输出期望。
- `tests/test_ops_version_migration.py`：统一唯一 head 和升级终点。
- `tests/test_rebuild_audit_migration.py`：保留审计历史验证，更新升级终点。

迁移已改为 `0013_login_wait_attempts → 0014_download_adjustments → 0015_download_staging → 0016_monitoring`；OpenAPI 和类型已重新生成。六个 M2 类型已显式声明角色，补齐通用接口拒绝和专用接口放行测试。监控图改为 SVG 原生宽高属性，行为不变。

完整检查通过：后端 **2757 passed**，前端 **380 passed**。stylelint 通过 `/tmp` 启动脚本复用 main 已安装的同版本依赖，使用当前工作区规则；未安装、未联网、未暂存、未提交。

`make check` 末尾原样：

```text
 Test Files  41 passed (41)
      Tests  380 passed (380)
   Start at  04:49:09
   Duration  11.82s (tests 57%, import 20%, environment 18%, setup 2%, transform 2%)
```