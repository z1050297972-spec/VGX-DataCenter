1. 改动清单

- [src/rdp/infra/timeutil.py](/home/shawn/桌面/robot-data-platform.wt/m0-01-repo-skeleton-check-chain/src/rdp/infra/timeutil.py)：实现 UTC 转换及无效时区校验，越界异常由标准库传递。
- [scripts/check_contracts.py](/home/shawn/桌面/robot-data-platform.wt/m0-01-repo-skeleton-check-chain/scripts/check_contracts.py)：实现 AST 契约检查、路径处理、诊断输出及退出码。
- [tests/test_timeutil.py](/home/shawn/桌面/robot-data-platform.wt/m0-01-repo-skeleton-check-chain/tests/test_timeutil.py)：实现全部 10 个时间契约测试。
- [tests/test_check_contracts.py](/home/shawn/桌面/robot-data-platform.wt/m0-01-repo-skeleton-check-chain/tests/test_check_contracts.py)：实现全部 46 个检查器测试，通过子进程验证公开边界。
- [Makefile](/home/shawn/桌面/robot-data-platform.wt/m0-01-repo-skeleton-check-chain/Makefile)：接入契约检查，更新为六步。
- [pyproject.toml](/home/shawn/桌面/robot-data-platform.wt/m0-01-repo-skeleton-check-chain/pyproject.toml)：添加 `failOnWarnings = true`，配置测试临时目录自动清理。

已确认三个公开函数的签名、类型和 docstring 与 `b1fec00` 相同；依赖表及 `uv.lock` 未改。旧临时文件已删除，未暂存、未提交。

2. `make check`

最后一次命令：`make check`，退出码 **0**。原样输出：

```text
[1/6] ruff format --check
.venv/bin/ruff format --check .
8 files already formatted
[2/6] ruff check
.venv/bin/ruff check .
All checks passed!
[3/6] basedpyright
.venv/bin/basedpyright
0 errors, 0 warnings, 0 notes
[4/6] import-linter
.venv/bin/lint-imports --no-cache --no-logo

---------
Contracts
---------

Analyzed 5 files, 0 dependencies.
---------------------------------

入口层只能向下依赖基础层 KEPT

Contracts: 1 kept, 0 broken.
[5/6] 契约检查
.venv/bin/python scripts/check_contracts.py src/rdp scripts
问题总数: 0
[6/6] pytest
.venv/bin/pytest
============================= test session starts ==============================
platform linux -- Python 3.12.15, pytest-9.1.1, pluggy-1.7.0
rootdir: /home/shawn/桌面/robot-data-platform.wt/m0-01-repo-skeleton-check-chain
configfile: pyproject.toml
testpaths: tests
collected 56 items

tests/test_check_contracts.py .......................................... [ 75%]
....                                                                     [ 82%]
tests/test_timeutil.py ..........                                        [100%]

============================== 56 passed in 2.75s ==============================
```

运行前 `git status --porcelain --untracked-files=all`：

```text
 M Makefile
 M pyproject.toml
 M scripts/check_contracts.py
 M src/rdp/infra/timeutil.py
 M tests/test_check_contracts.py
 M tests/test_timeutil.py
```

运行后同一命令：

```text
 M Makefile
 M pyproject.toml
 M scripts/check_contracts.py
 M src/rdp/infra/timeutil.py
 M tests/test_check_contracts.py
 M tests/test_timeutil.py
```

3. 契约变更申请、依赖申请

无。

4. 拿不准、需要评审决定的地方

无未决契约问题。

流程上有一处偏差需如实说明：部分后续用例已被前序实现或标准库行为覆盖，启用后首次运行即通过，因此并非全部 56 项都经历独立的红阶段。需要新增实现的行为已先观察失败再实现；最终没有骨架跳过。