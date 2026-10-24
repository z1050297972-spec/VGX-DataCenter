1. **清理查询失败**：在 [logging.py](/home/shawn/桌面/robot-data-platform.wt/m0-03-config-state-dir-runtime-log/src/rdp/infra/logging.py) 的 `_delete_expired` 调用处捕获查询过程的 `OSError`，跳过本次清理，使启动标记正常清除、切分边界正常推进、活动文件正常重开。`getFilesToDelete` 及既有契约未改。新增测试覆盖“启动/切分 × iterdir/is_file/is_symlink”六种情况，验证记录完整、不逐条重试、下次切分恢复清理。
2. **常量私有化**：[config.py](/home/shawn/桌面/robot-data-platform.wt/m0-03-config-state-dir-runtime-log/src/rdp/infra/config.py) 两个默认路径常量及内部引用均加 `_`，原注释不变，确认没有外部引用。

本轮只改上述两个源码文件及 `tests/test_logging.py`。无契约变更申请、无依赖申请，改动未提交。

**第1条首次失败输出**

命令：

```text
.venv/bin/pytest tests/test_logging.py::test_expired_archive_query_errors_preserve_records -q --tb=short
```

输出原文：

```text
FFFFFF                                                                   [100%]
=================================== FAILURES ===================================
_____ test_expired_archive_query_errors_preserve_records[iterdir-startup] ______
tests/test_logging.py:997: in test_expired_archive_query_errors_preserve_records
    assert all(f"查询故障记录 {index}\n" in current for index in range(3, 6)), current
E   AssertionError: 
E   assert False
E    +  where False = all(<generator object test_expired_archive_query_errors_preserve_records.<locals>.<genexpr> at 0x7dd28d4665e0>)
_____ test_expired_archive_query_errors_preserve_records[iterdir-rollover] _____
tests/test_logging.py:996: in test_expired_archive_query_errors_preserve_records
    current = (tmp_path / "web.log").read_text(encoding="utf-8")
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
../../../.local/share/uv/python/cpython-3.12.15-linux-x86_64-gnu/lib/python3.12/pathlib.py:1027: in read_text
    with self.open(mode='r', encoding=encoding, errors=errors) as f:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
../../../.local/share/uv/python/cpython-3.12.15-linux-x86_64-gnu/lib/python3.12/pathlib.py:1013: in open
    return io.open(self, mode, buffering, encoding, errors, newline)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E   FileNotFoundError: [Errno 2] No such file or directory: '/tmp/pytest-of-shawn/pytest-129/test_expired_archive_query_err1/web.log'
_____ test_expired_archive_query_errors_preserve_records[is_file-startup] ______
tests/test_logging.py:997: in test_expired_archive_query_errors_preserve_records
    assert all(f"查询故障记录 {index}\n" in current for index in range(3, 6)), current
E   AssertionError: 
E   assert False
E    +  where False = all(<generator object test_expired_archive_query_errors_preserve_records.<locals>.<genexpr> at 0x7dd28d4a2420>)
_____ test_expired_archive_query_errors_preserve_records[is_file-rollover] _____
tests/test_logging.py:996: in test_expired_archive_query_errors_preserve_records
    current = (tmp_path / "web.log").read_text(encoding="utf-8")
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
../../../.local/share/uv/python/cpython-3.12.15-linux-x86_64-gnu/lib/python3.12/pathlib.py:1027: in read_text
    with self.open(mode='r', encoding=encoding, errors=errors) as f:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
../../../.local/share/uv/python/cpython-3.12.15-linux-x86_64-gnu/lib/python3.12/pathlib.py:1013: in open
    return io.open(self, mode, buffering, encoding, errors, newline)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E   FileNotFoundError: [Errno 2] No such file or directory: '/tmp/pytest-of-shawn/pytest-129/test_expired_archive_query_err3/web.log'
____ test_expired_archive_query_errors_preserve_records[is_symlink-startup] ____
tests/test_logging.py:997: in test_expired_archive_query_errors_preserve_records
    assert all(f"查询故障记录 {index}\n" in current for index in range(3, 6)), current
E   AssertionError: 
E   assert False
E    +  where False = all(<generator object test_expired_archive_query_errors_preserve_records.<locals>.<genexpr> at 0x7dd28d431000>)
___ test_expired_archive_query_errors_preserve_records[is_symlink-rollover] ____
tests/test_logging.py:996: in test_expired_archive_query_errors_preserve_records
    current = (tmp_path / "web.log").read_text(encoding="utf-8")
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
../../../.local/share/uv/python/cpython-3.12.15-linux-x86_64-gnu/lib/python3.12/pathlib.py:1027: in read_text
    with self.open(mode='r', encoding=encoding, errors=errors) as f:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
../../../.local/share/uv/python/cpython-3.12.15-linux-x86_64-gnu/lib/python3.12/pathlib.py:1013: in open
    return io.open(self, mode, buffering, encoding, errors, newline)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E   FileNotFoundError: [Errno 2] No such file or directory: '/tmp/pytest-of-shawn/pytest-129/test_expired_archive_query_err5/web.log'
=========================== short test summary info ============================
FAILED tests/test_logging.py::test_expired_archive_query_errors_preserve_records[iterdir-startup]
FAILED tests/test_logging.py::test_expired_archive_query_errors_preserve_records[iterdir-rollover]
FAILED tests/test_logging.py::test_expired_archive_query_errors_preserve_records[is_file-startup]
FAILED tests/test_logging.py::test_expired_archive_query_errors_preserve_records[is_file-rollover]
FAILED tests/test_logging.py::test_expired_archive_query_errors_preserve_records[is_symlink-startup]
FAILED tests/test_logging.py::test_expired_archive_query_errors_preserve_records[is_symlink-rollover]
6 failed in 0.13s
```

修复后同一测试：`6 passed in 0.02s`。

**最终检查**

最后一次命令：

```text
make check
```

十一项全绿：232 passed、无 skipped；唯一 warning 为既有 TestClient 弃用提示。末尾输出原文：

```text
======================== 232 passed, 1 warning in 4.86s ========================
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.gqGcwh0LYo/openapi.json → /tmp/tmp.gqGcwh0LYo/schema.d.ts [11.9ms]
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

 RUN  v5.0.5 /home/shawn/桌面/robot-data-platform.wt/m0-03-config-state-dir-runtime-log/src/web


 Test Files  6 passed (6)
      Tests  19 passed (19)
   Start at  20:14:29
   Duration  1.05s (environment 43%, tests 29%, import 27%, transform 1%, setup 1%)
```

运行前，`git status --porcelain --untracked-files=all`：

```text
 M src/rdp/api/__init__.py
 M src/rdp/infra/config.py
 M src/rdp/infra/logging.py
 M src/rdp/infra/state.py
 M tests/test_config.py
 M tests/test_logging.py
 M tests/test_state.py
 M tests/test_web_app.py
?? tests/conftest.py
```

运行后，同一命令输出：

```text
 M src/rdp/api/__init__.py
 M src/rdp/infra/config.py
 M src/rdp/infra/logging.py
 M src/rdp/infra/state.py
 M tests/test_config.py
 M tests/test_logging.py
 M tests/test_state.py
 M tests/test_web_app.py
?? tests/conftest.py
```