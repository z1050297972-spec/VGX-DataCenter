三条均已完成，本轮只改注释和测试 docstring，未改变行为：

1. [tests/test_api_errors.py](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/tests/test_api_errors.py)：删除“派工B”。按 `git diff 37871e4 --name-only` 搜索全部 20 个文件，未发现“派工”或“在 B 中”。
2. [src/web/src/api/problems.ts](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/src/web/src/api/problems.ts)：状态码注释移至 `statusTable` 正上方；为 `requestId` 补充对应后端 `ProblemResponse.error_id` 的 uuid4 hex 格式说明。
3. [tests/test_diagnostics.py](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/tests/test_diagnostics.py) 和 `tests/test_api_errors.py`：指定的 7 个 docstring 均改为以“验证契约：”开头，其余内容保留。

**`make check` 十一步全绿，退出码 0：pytest 329 passed、Vitest 55 passed，均为 0 skipped。** 未暂存、未提交；检查临时目录已清理。

最后一次命令：

```text
make check
```

末尾输出原样如下：

```text
======================== 329 passed, 1 warning in 5.80s ========================
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.d1RoeddE7A/openapi.json → /tmp/tmp.d1RoeddE7A/schema.d.ts [17.2ms]
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

 RUN  v5.0.5 /home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/src/web


 Test Files  8 passed (8)
      Tests  55 passed (55)
   Start at  00:03:30
   Duration  1.46s (environment 42%, tests 30%, import 27%, transform 1%, setup 1%)
```

运行前的 `git status --porcelain --untracked-files=all`（包含前轮未提交改动）：

```text
 M src/rdp/api/__init__.py
 M src/rdp/api/errors.py
 M src/rdp/infra/diagnostics.py
 M src/rdp/jobs/outcome.py
 M src/web/src/DiagnosticCard.test.tsx
 M src/web/src/DiagnosticCard.tsx
 M src/web/src/HealthPage.test.tsx
 M src/web/src/HealthPage.tsx
 M src/web/src/api/client.ts
 M src/web/src/api/health.test.ts
 M src/web/src/api/openapi.json
 M src/web/src/api/problems.test.ts
 M src/web/src/api/problems.ts
 M src/web/src/api/schema.d.ts
 M src/web/src/useHealth.test.tsx
 M tests/diagnostics_demo.py
 M tests/test_api_errors.py
 M tests/test_diagnostics.py
 M tests/test_diagnostics_demo.py
 M tests/test_job_outcome.py
```

运行后的 `git status --porcelain --untracked-files=all`：

```text
 M src/rdp/api/__init__.py
 M src/rdp/api/errors.py
 M src/rdp/infra/diagnostics.py
 M src/rdp/jobs/outcome.py
 M src/web/src/DiagnosticCard.test.tsx
 M src/web/src/DiagnosticCard.tsx
 M src/web/src/HealthPage.test.tsx
 M src/web/src/HealthPage.tsx
 M src/web/src/api/client.ts
 M src/web/src/api/health.test.ts
 M src/web/src/api/openapi.json
 M src/web/src/api/problems.test.ts
 M src/web/src/api/problems.ts
 M src/web/src/api/schema.d.ts
 M src/web/src/useHealth.test.tsx
 M tests/diagnostics_demo.py
 M tests/test_api_errors.py
 M tests/test_diagnostics.py
 M tests/test_diagnostics_demo.py
 M tests/test_job_outcome.py
```