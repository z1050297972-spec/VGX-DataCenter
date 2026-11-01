状态：未完成

13 个冲突文件已合并；迁移已改号，OpenAPI 和类型已重新生成。未 `git add`、未提交，索引保持原样。

- `src/rdp/api/__init__.py`：保留请求体限制、监控采样及双方路由。
- `src/rdp/api/jobs.py`：保留 M2 接口和 main 脱敏逻辑，补齐响应身份参数。
- `src/rdp/jobs/service.py`：合并类型角色授权、暂存清理管理员及占用校验。
- `tests/test_api_database.py`：模拟后续迁移改为接续 0016 的 0017。
- `tests/test_data_origin_migration.py`：历史包排除新增迁移，升级期望保持 0016。
- `tests/test_dataset_api_contract.py`：升级终点统一为 0016。
- `tests/test_datasets_index.py`：当前版本统一为 0016。
- `tests/test_db_migration.py`：统一 head、备份版本及模拟后续迁移。
- `tests/test_jobs_migration.py`：保留双方迁移，补齐完整新链。
- `tests/test_navwrite_audit_migration.py`：保留历史审计验证，升级终点统一为 0016。
- `tests/test_ops_cli.py`：迁移输出期望统一为 0016。
- `tests/test_ops_version_migration.py`：唯一 head 和升级终点统一为 0016。
- `tests/test_rebuild_audit_migration.py`：保留审计历史验证，升级终点统一为 0016。

唯一失败是范围外的 `tests/test_followups_cleanup.py`：期望生产类型为 14 个，合并后实际为 20 个。已请求允许更新该测试；依据你限定的修改边界，暂未改动。前端检查尚未执行。

`make check` 末尾原样：

```text
=========================== short test summary info ============================
FAILED tests/test_followups_cleanup.py::test_production_submission_roles_and_member_write_rejection
============ 1 failed, 2755 passed, 8 warnings in 89.80s (0:01:29) =============
make: *** [Makefile:33: check] Error 1
```