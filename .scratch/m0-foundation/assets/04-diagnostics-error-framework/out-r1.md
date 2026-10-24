七条均已修复。**`make check` 十一步全绿：pytest 329 passed，Vitest 55 passed，均为 0 skipped。** 本轮增量涉及 9 个文件，未暂存、未提交。

**逐条处理结果**

1. **示例二改走真正的意外异常路径**  
   文件：[tests/test_api_errors.py](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/tests/test_api_errors.py:782)。嵌套函数直接执行 `Path(raw["target"])`，不包装 `TypeError`。完整验证响应、请求编号、单条 ERROR、单份 traceback、原始消息和源码行，移除作业结果断言。  
   新断言首次运行：**通过**，现有意外异常边界已满足要求。另拆出的 `test_explicit_defect_diagnostics_and_cause` 首次也通过。

2. **logger 使用实际模块名**  
   文件：[src/rdp/api/errors.py](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/src/rdp/api/errors.py)、`tests/test_api_errors.py`。改为 import 后的 `logging.getLogger(__name__)`，测试精确断言 `rdp.api.errors`。  
   `test_handler_known_log_once` 首次**失败**，实际仍为 `rdp.api`；修改后通过。随后更新的两个边界测试首次通过，已被 logger 修改覆盖。相关日志名称文档同步更新。

3. **清除过期阶段措辞**  
   文件：`src/rdp/api/errors.py`、[src/web/src/api/problems.ts](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/src/web/src/api/problems.ts:72)，以及三个前端测试文件的注释、标题。仅改措辞，无新增行为测试。  
   文档修改：
   - `install_error_handlers` 首行改为“由 create_app 调用”。
   - `Returns:` 改为中间件栈“返回”既定包装结构，明确请求编号中间件在错误报告边界之外。
   - `createProblemFetch` 的 `@timeSemantics` 删除“派工 B 中”，直接描述当前调用关系。  
   
   已搜索当前全部改动文件，没有遗留上述过期措辞。

4. **后端状态码映射统一为一份**  
   文件：[src/rdp/infra/diagnostics.py](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/src/rdp/infra/diagnostics.py:58)、`src/rdp/api/errors.py`、`tests/test_diagnostics.py`、`src/web/src/api/problems.ts`。新增只读常量 `ALLOWED_HTTP_STATUSES`，异常校验、响应模型校验和 OpenAPI 登记均读取它。前端映射注明修改规范表时须同步更新。  
   状态码测试首次**失败**：常量尚不存在；实现后通过。期望值仍逐项写出，没有从常量反推。

5. **统一卡片展示**  
   文件：[src/web/src/DiagnosticCard.tsx](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/src/web/src/DiagnosticCard.tsx)、`DiagnosticCard.test.tsx`、`HealthPage.test.tsx`。标题增加类别中文名和“来源：”；所有 problem 分支及有编号的 unavailable 显示“错误编号：”；第五段统一为“检查：”。  
   带诊断、无诊断、程序缺陷、unavailable 四项修改后的测试首次均**失败**，分别缺少检查段或编号标签；修复后通过。新增三类别标题测试和页面编号断言首次通过，已被前序组件修改覆盖。  
   `DiagnosticCard.@returns` 相应明确了标题组成、“检查（下一步建议）”、所有 problem 的编号标签，以及 unavailable 的编号显示规则。

6. **补齐真实应用中的 404、422 子类测试**  
   文件：[tests/test_api_errors.py](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/tests/test_api_errors.py:404)。增加 `InputError` 的两个子类，逐项验证状态码、媒体类型、类别和请求编号。  
   新断言首次运行：**通过**，现有异常继承处理已支持；未改实现。

7. **422 日志追加安全字段诊断**  
   文件：`src/rdp/api/errors.py`、[tests/test_api_errors.py](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/tests/test_api_errors.py:914)。追加 `problem.diagnostics` 的五段内容，继续禁止格式化 `RequestValidationError` 本身。  
   `test_validation_log_field_locations_without_values` 首次**失败**：日志只有摘要，没有 `body.password`；修改后通过，同时验证两个字段位置、五段内容及原值不泄漏。  
   文档修改：
   - `handle_error.Side Effects` 明确安全字段诊断追加到同一条 ERROR，不格式化校验异常、不记录原值。
   - `_report_error` docstring 明确校验失败只写安全诊断。

**最终检查**

最后一次命令：

```text
make check
```

退出码 `0`。末尾输出原样如下；工具在零跳过时不打印 skipped 列：

```text
======================== 329 passed, 1 warning in 5.87s ========================
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.MPvxmllm4n/openapi.json → /tmp/tmp.MPvxmllm4n/schema.d.ts [18.3ms]
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
   Start at  23:51:14
   Duration  1.54s (environment 41%, tests 29%, import 27%, transform 2%, setup 1%)
```

保留已有的 Starlette warning；检查临时目录已清理。

运行前的 `git status --porcelain --untracked-files=all`（包含上轮未提交改动）：

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

契约变更申请：**无**。依赖申请：**无**。