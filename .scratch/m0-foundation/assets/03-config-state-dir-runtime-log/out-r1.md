八条已修复，改动留在工作区，未暂存、未提交。没有新增依赖、安装或联网操作。

1. **归档删除失败**：[logging.py](/home/shawn/桌面/robot-data-platform.wt/m0-03-config-state-dir-runtime-log/src/rdp/infra/logging.py) 改为逐个跳过删除时的 `OSError`，不阻断写入、切分或其他文件清理；失败归档下次切分或启动再试。补了获批的 `Side Effects` 说明。新增参数化测试覆盖“启动/切分 × 持续权限失败/文件已消失”四种情况，并更新原故障恢复测试。
2. **复用时间工具**：`_local_time` 改用 `ensure_utc(source.now()).astimezone(zone)`，保留时区类型检查；现有异常测试通过。
3. **TOML 位置退路**：[config.py](/home/shawn/桌面/robot-data-platform.wt/m0-03-config-state-dir-runtime-log/src/rdp/infra/config.py) 注明 Python 3.12 缺少行列属性的原因；只提取已知位置格式，否则显示“位置未知”。新增测试验证仍包含文件、`<document>` 和期望。
4. **过时注释**：改为已批准的3650天上限及防误填理由。
5. **并发请求日志测试**：[test_web_app.py](/home/shawn/桌面/robot-data-platform.wt/m0-03-config-state-dir-runtime-log/tests/test_web_app.py) 在两个请求交错前后写业务日志，逐条核对文件中的编号与各自响应头一致、不串号。增强后首次即通过，因为现有实现已满足行为。
6. **测试状态恢复**：[conftest.py](/home/shawn/桌面/robot-data-platform.wt/m0-03-config-state-dir-runtime-log/tests/conftest.py) 一并保存、恢复 `_installed_handlers`，并关闭本次测试新增的 handler。
7. **具名常量**：提取默认状态目录、配置文件相对路径，以及请求编号、字段键、归档日期、安全字符串四个正则，补齐出处和用途注释。
8. **时区读取代价**：仅补注释，说明两三次小文件读取、v1接受的原因，以及按P1不读取 `TZ`；行为未改。

契约对比确认：既有函数的签名、类型和 docstring 仅改了第1条获批补充。契约变更申请、依赖申请均无。

**第1、3条先红后绿**

第1条首次命令：

```text
.venv/bin/pytest tests/test_logging.py::test_expired_archive_delete_errors_preserve_records -q --tb=short
```

首次失败输出节选：

```text
_____ test_expired_archive_delete_errors_preserve_records[denied-startup] ______
tests/test_logging.py:958: in test_expired_archive_delete_errors_preserve_records
    assert all(f"记录 {index}\n" in current for index in range(3, 6)), current
E   AssertionError:
E   assert False
```

```text
E   FileNotFoundError: [Errno 2] No such file or directory: '/tmp/pytest-of-shawn/pytest-116/test_expired_archive_delete_er1/web.log'
```

```text
_____ test_expired_archive_delete_errors_preserve_records[missing-startup] _____
tests/test_logging.py:960: in test_expired_archive_delete_errors_preserve_records
    assert all(f"记录 {index}\n" in archived for index in range(3)), archived
E   AssertionError: 2026-10-21 23:59:00.000+08:00 INFO rdp.test 记录 1
E     2026-10-21 23:59:00.000+08:00 INFO rdp.test 记录 2
```

```text
____ test_expired_archive_delete_errors_preserve_records[missing-rollover] _____
tests/test_logging.py:958: in test_expired_archive_delete_errors_preserve_records
    assert all(f"记录 {index}\n" in current for index in range(3, 6)), current
E   AssertionError: 2026-10-22 00:00:00.000+08:00 INFO rdp.test 记录 4
E     2026-10-22 00:00:00.000+08:00 INFO rdp.test 记录 5
```

```text
4 failed in 0.13s
```

修复后同一测试：`4 passed in 0.09s`。

第3条首次命令：

```text
.venv/bin/pytest tests/test_config.py::test_toml_error_without_position_has_safe_fallback -q --tb=short
```

首次失败输出：

```text
F                                                                        [100%]
=================================== FAILURES ===================================
______________ test_toml_error_without_position_has_safe_fallback ______________
tests/test_config.py:331: in test_toml_error_without_position_has_safe_fallback
    assert "实际 位置未知" in message
E   AssertionError: assert '实际 位置未知' in '配置文件 /tmp/pytest-of-shawn/pytest-117/test_toml_error_without_positi0/changed-message.toml，项 <document>：实际 文案已改变：不应回显的文档片段；期望合法 UTF-8 TOML；拒绝启动，请修正配置'
=========================== short test summary info ============================
FAILED tests/test_config.py::test_toml_error_without_position_has_safe_fallback
1 failed in 0.07s
```

修复后：`1 passed in 0.04s`。

**最终检查**

最后一次命令：

```text
make check
```

十一项全绿，226 passed、无 skipped；唯一 warning 为既有 TestClient 弃用提示。末尾输出原文：

```text
======================== 226 passed, 1 warning in 4.93s ========================
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.QEOOJKJDB9/openapi.json → /tmp/tmp.QEOOJKJDB9/schema.d.ts [11.7ms]
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
   Start at  20:06:13
   Duration  1.02s (environment 42%, tests 29%, import 27%, transform 1%)
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