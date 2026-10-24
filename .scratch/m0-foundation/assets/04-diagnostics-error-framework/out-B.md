**1. 改动清单**

实现完成，改动留在工作区，未暂存、未提交。未联网、未安装依赖，未修改受保护文件。

- [src/rdp/infra/diagnostics.py](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/src/rdp/infra/diagnostics.py)：实现诊断校验、D1 错误链、日志渲染、聚合和四类异常。
- [src/rdp/jobs/outcome.py](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/src/rdp/jobs/outcome.py)：实现唯一作业结果计算函数及边界校验。
- [src/rdp/api/errors.py](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/src/rdp/api/errors.py)：实现统一响应、参数校验诊断、D2 traceback、单次报告边界及按需 OpenAPI 合并；记录 6.2 状态码表。
- [src/rdp/api/__init__.py](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/src/rdp/api/__init__.py)：接入处理器和错误边界，移除提前缓存权宜。
- [src/web/src/DiagnosticCard.tsx](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/src/web/src/DiagnosticCard.tsx)：实现五段卡片、错误链折叠、缺陷详情按需加载及取消、超时处理。
- [src/web/src/api/problems.ts](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/src/web/src/api/problems.ts)：实现响应校验、传输包装及安全展示适配。
- [src/web/src/api/client.ts](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/src/web/src/api/client.ts)：接入统一请求失败包装器。
- [src/web/src/HealthPage.tsx](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/src/web/src/HealthPage.tsx)：用诊断卡片替换 Alert 权宜。
- [src/web/src/api/openapi.json](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/src/web/src/api/openapi.json)：通过 `make api-types` 生成。
- [src/web/src/api/schema.d.ts](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/src/web/src/api/schema.d.ts)：通过 `make api-types` 生成，未手改。
- [tests/test_diagnostics.py](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/tests/test_diagnostics.py)：实现 34 项诊断测试。
- [tests/test_job_outcome.py](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/tests/test_job_outcome.py)：实现 16 项结果及依赖边界测试。
- [tests/test_api_errors.py](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/tests/test_api_errors.py)：实现 41 项接口测试，包含真实 uvicorn 内存协议驱动。
- [tests/diagnostics_demo.py](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/tests/diagnostics_demo.py)：实现测试专用五类故障演示路由。
- [tests/test_diagnostics_demo.py](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/tests/test_diagnostics_demo.py)：实现 4 项演示隔离测试。
- [src/web/src/DiagnosticCard.test.tsx](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/src/web/src/DiagnosticCard.test.tsx)：实现 15 项卡片测试。
- [src/web/src/api/problems.test.ts](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/src/web/src/api/problems.test.ts)：实现 17 项适配层测试。
- [src/web/src/HealthPage.test.tsx](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/src/web/src/HealthPage.test.tsx)：落实迁移测试，原失败页面测试改验卡片。
- [src/web/src/api/health.test.ts](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/src/web/src/api/health.test.ts)：按统一错误载荷更新断言，保留超时、取消及请求次数检查。
- [src/web/src/useHealth.test.tsx](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/src/web/src/useHealth.test.tsx)：更新错误载荷断言，保留状态和缓存隔离检查。

**2. `make check`**

最后一次命令：

```text
make check
```

退出码 `0`，十一步全绿。pytest **327 passed、0 skipped**；Vitest **54 passed、0 skipped**。零跳过时工具不打印 skipped 列。

末尾输出原样如下：

```text
======================== 327 passed, 1 warning in 5.89s ========================
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.HmN80zP43t/openapi.json → /tmp/tmp.HmN80zP43t/schema.d.ts [17.6ms]
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
      Tests  54 passed (54)
   Start at  23:26:04
   Duration  1.59s (environment 43%, tests 28%, import 26%, transform 1%, setup 1%)
```

warning 是已有的 Starlette deprecation warning。临时 OpenAPI 目录已清理。

跑之前的 `git status --porcelain --untracked-files=all`：

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

跑之后的 `git status --porcelain --untracked-files=all`：

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

**3. 契约变更申请、依赖申请**

无。已批准签名和类型未改，D1 新字段除外。

按 D1、D2 修改的文档：

- **D1 — `Diagnostic.Attributes`**：新增 `error_chain`，说明“从外到内每层一句非空白文本”“默认空元组，不接受 null”“JSON 输出有序字符串数组，不包含 traceback”。
- **D1 — `render_diagnostic.Returns`**：说明非空链在检查行后追加“错误链：”；后续层前置八格及“← ”，控制字符转义；空链保持六行。
- **D1 — `DiagnosticCard.@returns`**：新增“错误链（N 层）”折叠入口、展开顺序及空链无入口。
- **D1 — `readProblemResponse.@returns`**：新增错误链只接受非空白文本数组，省略时规范为空数组，保留外到内顺序。
- **D1 — 诊断模块注释**：把“错误链仅在异常中”改为诊断可通过 `error_chain` 承载文本错误链。
- **D2 — `format_exception_report` 首行**：改为保留异常消息和源码行、不打印局部变量的完整报告。
- **D2 — `format_exception_report.Returns`**：保留每层类型、消息、源码行，notes 沿用标准库；删除隐藏消息、不调用 `__str__` 等规定。
- **D2 — `format_exception_report.Side Effects`**：改为只读栈帧对应源文件取得源码行，不改变异常和 logging 状态。
- **D2 — 接口错误模块注释**：说明使用标准库 traceback，参数校验不回显原值，自有模型使用 `hide_input_in_errors=True`。

另外按评审意见更新了 `create_app` 和 `HealthPage` 文档，删除四条骨架期 ESLint 豁免。

**4. 拿不准、需要评审决定的地方**

状态码与 6.2 表不一致的地方：**无**。

有一处执行流程偏差需要如实交代：**5 个清单测试首次被前序编辑的语法错误阻断**，不能算有效的功能红灯。修复后逐个补跑，其中字段校验测试先出现功能失败再实现，其余已被前序实现覆盖；原 HealthPage 失败页面测试也曾受同一语法错误影响。下面逐项标明，未把编译失败冒充功能验证。

**5. 先红后绿**

以下每行记录首次单独运行结果。所有测试最终通过。前端标题省略统一的“验证契约：”前缀。

`tests/test_job_outcome.py`

| 测试 | 首次结果 |
|---|---|
| `test_enum_terms` | 通过：骨架枚举已有定义。 |
| `test_succeeded` | 失败：`NotImplementedError`。 |
| `test_succeeded_with_warnings` | 失败：错误返回成功。 |
| `test_partially_succeeded` | 失败：错误返回成功。 |
| `test_partial_with_warnings` | 通过：前一项已实现部分失败优先。 |
| `test_all_failed` | 失败：错误返回部分成功。 |
| `test_aborted_without_item_failures` | 失败：中止仍返回成功。 |
| `test_aborted_overrides_partial` | 通过：前一项已实现中止优先。 |
| `test_empty_job` | 通过：此前分支已正确处理空作业。 |
| `test_negative_counts` | 失败：未拒绝负数。 |
| `test_failed_exceeds_total` | 失败：未拒绝失败数超总数。 |
| `test_count_types` | 失败：接受 bool 等非法类型。 |
| `test_aborted_type` | 失败：接受非 bool。 |
| `test_pure_and_no_clock` | 通过：已有实现为无副作用纯函数。 |
| `test_layers_forbid_reverse_dependencies` | 通过：骨架已有分层合约。 |
| `test_layers_forbid_framework_dependencies` | 通过：骨架已有 forbidden 合约。 |

`tests/test_diagnostics.py`

| 测试 | 首次结果 |
|---|---|
| `test_level_and_category_values` | 失败：模型校验器未实现。 |
| `test_model_required_fields` | 通过：Pydantic 已执行必填约束。 |
| `test_model_text_constraints` | 通过：骨架已有文本约束。 |
| `test_model_extra_fields` | 失败：尚无 `error_chain`。 |
| `test_model_object_values` | 通过：骨架已有严格字符串约束。 |
| `test_model_duplicate_keys` | 失败：未拒绝重复键。 |
| `test_model_tool_conflict` | 失败：未拒绝工具来源的冲突。 |
| `test_model_deep_immutability` | 通过：冻结模型和元组已生效。 |
| `test_json_round_trip` | 通过：Pydantic 序列化及 D1 字段已覆盖。 |
| `test_json_validation_error_privacy` | 通过：骨架已配置隐藏输入。 |
| `test_render_six_lines` | 失败：渲染未实现。 |
| `test_render_object_order` | 通过：六行渲染实现已保留对象顺序。 |
| `test_render_global_and_no_expectation` | 通过：六行渲染实现已覆盖空对象及空期望。 |
| `test_render_control_characters` | 失败：控制字符产生额外行。 |
| `test_render_formatter_indentation` | 通过：渲染与现有 formatter 已正确分工。 |
| `test_render_pure` | 通过：渲染实现不修改输入或记录日志。 |
| `test_aggregate_empty` | 失败：聚合未实现。 |
| `test_aggregate_limit_boundary` | 失败：尚未生成分组。 |
| `test_aggregate_groups_independent` | 通过：前一项按组实现已覆盖。 |
| `test_aggregate_levels_categories_stages` | 通过：前一项已分别计数、共用样例配额。 |
| `test_aggregate_one_pass` | 通过：已有实现单次消费。 |
| `test_aggregate_invalid_item` | 失败：抛出 AttributeError，未按契约拒绝。 |
| `test_aggregate_iterator_failure` | 通过：已有实现原样传播迭代异常。 |
| `test_input_error_contract` | 失败：构造器未实现。 |
| `test_conflict_error_contract` | 失败：构造器未实现。 |
| `test_external_error_contract` | 失败：构造器未实现。 |
| `test_defect_error_contract` | 失败：构造器未实现。 |
| `test_exception_empty_and_container_validation` | 失败：未拒绝非法容器和空诊断。 |
| `test_exception_level_and_category_validation` | 失败：未拒绝级别、类别不匹配。 |
| `test_exception_subclass_status_validation` | 失败：未拒绝表外状态码覆盖。 |
| `test_exception_context_no_logging` | 通过：已有异常构造实现不打日志，保留 cause。 |
| `test_representative_conversion_partial_success` | 通过：诊断、D1 和作业结果实现已覆盖。 |
| `test_render_error_chain` | 失败：未输出错误链。 |
| `test_render_unicode_line_boundaries` | 失败：DEL 等字符未转义。 |

`tests/test_api_errors.py`

| 测试 | 首次结果 |
|---|---|
| `test_problem_schema_fields` | 失败：模型校验器未实现。 |
| `test_problem_schema_invalid` | 失败：未拒绝状态、类别不匹配。 |
| `test_problem_serialization` | 通过：Pydantic 与前两项实现已覆盖。 |
| `test_validation_each_field` | 失败：转换函数未实现。 |
| `test_validation_locations` | 失败：字段位置均为兜底“请求”。 |
| `test_validation_no_secret_echo` | 通过：前序转换已不使用原值及动态键。 |
| `test_validation_empty_errors` | 失败：空错误列表没有兜底诊断。 |
| `test_validation_pure` | 通过：转换实现只读元数据。 |
| `test_build_input_variants` | 失败：problem 构造未实现。 |
| `test_build_conflict` | 失败：摘要使用输入问题文案。 |
| `test_build_external` | 失败：缺少外部失败映射。 |
| `test_build_defect` | 失败：缺少缺陷映射。 |
| `test_build_validation` | 失败：校验异常错误映射为缺陷。 |
| `test_build_missing_request_id` | 失败：未抛契约要求的 RuntimeError。 |
| `test_build_pure` | 通过：此前构造实现无副作用。 |
| `test_report_complete_chain` | 失败：报告函数未实现。 |
| `test_report_group_and_cycle` | 失败：缺少循环引用标记。 |
| `test_report_secret_redaction` | 通过：前一实现已采用 D2 标准库格式，保留消息和源码、不打印局部变量。 |
| `test_handler_mappings_and_media` | 失败：工厂尚未安装处理器。 |
| `test_handler_known_log_once` | 失败：未记录 ERROR。 |
| `test_handler_request_log_privacy` | 通过：报告实现已只取方法和路由模板。 |
| `test_handler_no_io` | 通过：处理器只构造响应和记录日志。 |
| `test_boundary_construct` | 失败：构造器未实现。 |
| `test_boundary_normal_and_protocol_passthrough` | 失败：调用边界未实现。 |
| `test_boundary_no_response_fallback` | 失败：异常直接逃逸。 |
| `test_boundary_server_error_rethrow_once` | 通过：前序边界实现已消费重抛。 |
| `test_boundary_stream_failure_once` | 通过：前序边界已跟踪响应开始状态。 |
| `test_boundary_background_failure_once` | 通过：边界已覆盖整个下游调用。 |
| `test_boundary_exception_group_once` | 通过：边界和完整报告实现已覆盖异常组。 |
| `test_boundary_cancel_and_exit` | 通过：只捕获 Exception，未吞 BaseException。 |
| `test_boundary_fallback_send_failure` | 通过：补救发送位于捕获体之外，不递归处理。 |
| `test_boundary_report_dependency_failure` | 通过：报告依赖异常直接传播。 |
| `test_boundary_concurrent_ids` | 通过：已有请求上下文与局部响应状态实现已覆盖。 |
| `test_install_handlers` | 失败：安装函数未实现。 |
| `test_install_after_start` | 失败：未拒绝启动后安装。 |
| `test_preserve_framework_http_errors` | 通过：未覆盖框架 HTTP 处理器。 |
| `test_schema_components_and_generation` | 失败：移除骨架缓存后尚未合并组件。 |
| `test_schema_routes_in_implementation` | 失败：缺少错误响应定义。 |
| `test_install_isolation_and_cache` | 通过：前序安装实现已限定目标应用并清缓存。 |
| `test_representative_platform_defect` | 通过：诊断、报告、接口和结果函数已实现；随后补全身份及三层链断言。 |
| `test_validation_nested_dictionary_keys` | 失败：动态键被误识别为值模型字段。 |

`tests/test_diagnostics_demo.py`

| 测试 | 首次结果 |
|---|---|
| `test_mount_demo_only_in_tests` | 失败：挂载函数未实现。 |
| `test_demo_five_errors` | 失败：请求落到兜底 404。 |
| `test_demo_route_order_and_schema` | 失败：未拒绝重复挂载。 |
| `test_demo_no_external_effects` | 通过：已有演示实现仅使用内存对象。 |

`src/web/src/api/problems.test.ts`

| 测试标题 | 首次结果 |
|---|---|
| readProblemResponse 合法四类 problem | 失败：未实现。 |
| readProblemResponse Content-Type 大小写、参数及成功响应 | **语法失败**；修复后通过，媒体类型判断已在此前编辑中实现。 |
| readProblemResponse HTML、空体、坏 JSON、已消费 body | **语法失败**；修复后通过，读取失败处理已在此前编辑中实现。 |
| readProblemResponse 缺字段、额外字段、非法对象值和重复键 | **语法失败**；修复后再次单跑，出现有效的字段校验失败，再实现。 |
| readProblemResponse 非法 uuid、状态类别及缺陷诊断 | 失败：非法载荷未被拒绝。 |
| readProblemResponse 只读克隆 | 通过：此前实现已使用 clone。 |
| createProblemFetch 创建不发送请求 | 失败：未实现。 |
| createProblemFetch 2xx/3xx 返回原响应 | 通过：前一项传输包装已覆盖。 |
| createProblemFetch 4xx/5xx problem 拒绝 | 失败：Promise 仍成功返回响应。 |
| createProblemFetch 网络、超时、取消 | 失败：原始异常未转换。 |
| createProblemFetch 代理 HTML 与错误编号 | 失败：未保留合法响应头编号。 |
| createProblemFetch 透传 Request 和 AbortSignal | 通过：前序包装已原样传参。 |
| toFailureView 合法 cause | 失败：未实现。 |
| toFailureView 未知值和恶意 getter | 失败：getter 异常逃逸。 |
| toFailureView 不展示原始 message | 通过：前序兜底实现已覆盖。 |
| readProblemResponse 补齐默认字段 | 失败：缺省字段被拒绝。 |
| D1 错误链校验、默认值及工具冲突 | 失败：非法错误链未被拒绝。 |

`src/web/src/DiagnosticCard.test.tsx`

| 测试标题 | 首次结果 |
|---|---|
| 五段及级别、阶段、来源，实际期望同一行 | 失败：未实现。 |
| 对象顺序、全局对象和空期望 | 通过：首项渲染实现已覆盖。 |
| 无诊断的非缺陷摘要和编号 | 失败：未显示摘要。 |
| 程序缺陷折叠摘要 | 通过：前一项无诊断摘要分支已覆盖。 |
| 无回调时展开运行日志提示 | 失败：没有展开按钮。 |
| 首次展开加载详情 | 失败：没有加载状态或回调调用。 |
| 回调同步抛错、异步拒绝 | 失败：未捕获拒绝、未显示固定提示。 |
| 折叠再展开复用结果 | 通过：前序 requested 状态已避免重复加载。 |
| 编号或回调改变、忽略旧结果 | 失败：更换回调后仍显示旧加载状态。 |
| 卸载取消请求 | 通过：前序 effect 清理已覆盖。 |
| 4999/5000 毫秒超时边界 | 失败：未设置详情超时。 |
| unavailable 文案和可选编号 | 失败：未显示编号。 |
| HTML 和详情按纯文本显示 | 通过：已有 JSX 文本渲染已覆盖。 |
| 不修改 URL、存储或主动请求 | 通过：已有展示和按需加载边界已覆盖。 |
| D1 错误链层数和折叠 | 失败：没有错误链入口。 |

`src/web/src/HealthPage.test.tsx`

| 测试标题 | 首次结果 |
|---|---|
| 用 DiagnosticCard 替代 Alert，显示 problem | 失败：页面仍显示旧 Alert。 |
| 网络断开和代理 HTML 的固定文案 | **语法失败**；修复后通过，前序适配与页面接入已覆盖。 |
| 成功、缓存行为保持 | **语法失败**；修复后通过，原成功和缓存实现未改。 |
| 原失败页面测试改验诊断卡片 | 修改后首次被同一语法错误阻断；修复后通过，页面已完成替换。 |

`src/web/src/api/health.test.ts`

| 测试标题 | 首次结果 |
|---|---|
| 传输异常保留失败，不伪装成功 | 失败：旧断言要求原异常身份；按获批统一载荷更新。 |
| HEALTH_TIMEOUT_MS 到期中止且不重试 | 失败：旧断言要求原始异常文字；保留时间和次数断言，更新文案断言。 |
| 已取消不请求、运行中取消传播 | 失败：旧断言要求原始运行中取消文字；保留取消传播断言，更新文案断言。 |

`src/web/src/useHealth.test.tsx`

| 测试标题 | 首次结果 |
|---|---|
| 加载、成功和失败状态正确 | 失败：旧断言要求原异常身份；更新为统一载荷断言。 |
| 不同客户端不共享缓存 | 失败：旧断言要求原异常身份；保留缓存隔离检查，更新载荷断言。 |