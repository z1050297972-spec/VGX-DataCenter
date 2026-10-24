**1. 改动清单**

契约骨架完成。新增函数均保留未实现函数体；运行时异常处理、演示接口和 HealthPage 迁移留待派工 B。未暂存、未提交，未联网或安装依赖。

- [src/rdp/infra/diagnostics.py](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/src/rdp/infra/diagnostics.py)：诊断模型、枚举、渲染、聚合和四类异常契约。
- [src/rdp/api/errors.py](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/src/rdp/api/errors.py)：problem 响应、校验转换、安全异常报告及统一处理边界契约。
- [src/rdp/api/_asgi.py](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/src/rdp/api/_asgi.py)：集中已有 ASGI 调用类型。
- [src/rdp/api/__init__.py](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/src/rdp/api/__init__.py)：登记诊断 OpenAPI 组件，保持现有请求处理行为。
- [src/rdp/jobs/__init__.py](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/src/rdp/jobs/__init__.py)：新增领域包，声明作业结果唯一计算入口。
- [src/rdp/jobs/outcome.py](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/src/rdp/jobs/outcome.py)：四种作业结果及计数边界契约。
- [pyproject.toml](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/pyproject.toml)：仅修改 import-linter，登记 `rdp.jobs` 及依赖方向理由。
- [src/web/src/DiagnosticCard.tsx](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/src/web/src/DiagnosticCard.tsx)：诊断卡片及按需详情回调契约。
- [src/web/src/DiagnosticCard.test.tsx](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/src/web/src/DiagnosticCard.test.tsx)：14 项跳过测试。
- [src/web/src/api/problems.ts](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/src/web/src/api/problems.ts)：生成类型引用、失败响应校验和展示适配契约。
- [src/web/src/api/problems.test.ts](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/src/web/src/api/problems.test.ts)：16 项跳过测试。
- [src/web/src/HealthPage.test.tsx](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/src/web/src/HealthPage.test.tsx)：增加 3 项迁移清单，原测试保留。
- [src/web/src/api/openapi.json](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/src/web/src/api/openapi.json)：由 `make api-types` 重新生成。
- [src/web/src/api/schema.d.ts](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/src/web/src/api/schema.d.ts)：由 `make api-types` 重新生成，未手改。
- [tests/test_diagnostics.py](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/tests/test_diagnostics.py)：32 项跳过测试，包含转换部分成功示例。
- [tests/test_api_errors.py](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/tests/test_api_errors.py)：40 项跳过测试，包含平台缺陷、脱敏和只报告一次。
- [tests/test_job_outcome.py](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/tests/test_job_outcome.py)：16 项跳过测试，包含结果边界及依赖违规清单。
- [tests/diagnostics_demo.py](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/tests/diagnostics_demo.py)：测试专用五类故障演示挂载契约。
- [tests/test_diagnostics_demo.py](/home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework/tests/test_diagnostics_demo.py)：4 项演示隔离测试清单。

**2. `make check`**

最后一次命令：

```text
make check
```

退出码 `0`，十一步全绿。末尾输出原样如下：

```text
================== 232 passed, 92 skipped, 1 warning in 5.29s ==================
[7/11] OpenAPI 过期检查
✨ openapi-typescript 7.13.0
🚀 /tmp/tmp.yhlUtVs9Ro/openapi.json → /tmp/tmp.yhlUtVs9Ro/schema.d.ts [15.1ms]
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


 Test Files  6 passed | 2 skipped (8)
      Tests  19 passed | 33 skipped (52)
   Start at  22:12:40
   Duration  1.05s (environment 51%, tests 24%, import 23%, setup 1%, transform 1%)
```

warning 是已有的 Starlette deprecation warning。检查生成的临时目录已清理。

检查前 `git status --porcelain --untracked-files=all`：

```text
 M pyproject.toml
 M src/rdp/api/__init__.py
 M src/web/src/HealthPage.test.tsx
 M src/web/src/api/openapi.json
 M src/web/src/api/schema.d.ts
?? src/rdp/api/_asgi.py
?? src/rdp/api/errors.py
?? src/rdp/infra/diagnostics.py
?? src/rdp/jobs/__init__.py
?? src/rdp/jobs/outcome.py
?? src/web/src/DiagnosticCard.test.tsx
?? src/web/src/DiagnosticCard.tsx
?? src/web/src/api/problems.test.ts
?? src/web/src/api/problems.ts
?? tests/diagnostics_demo.py
?? tests/test_api_errors.py
?? tests/test_diagnostics.py
?? tests/test_diagnostics_demo.py
?? tests/test_job_outcome.py
```

检查后 `git status --porcelain --untracked-files=all`：

```text
 M pyproject.toml
 M src/rdp/api/__init__.py
 M src/web/src/HealthPage.test.tsx
 M src/web/src/api/openapi.json
 M src/web/src/api/schema.d.ts
?? src/rdp/api/_asgi.py
?? src/rdp/api/errors.py
?? src/rdp/infra/diagnostics.py
?? src/rdp/jobs/__init__.py
?? src/rdp/jobs/outcome.py
?? src/web/src/DiagnosticCard.test.tsx
?? src/web/src/DiagnosticCard.tsx
?? src/web/src/api/problems.test.ts
?? src/web/src/api/problems.ts
?? tests/diagnostics_demo.py
?? tests/test_api_errors.py
?? tests/test_diagnostics.py
?? tests/test_diagnostics_demo.py
?? tests/test_job_outcome.py
```

**3. 契约变更申请、依赖申请**

无。以下是本轮新增契约的选择及待评审事项，尚未启用其运行时行为。

**4. 契约选择与需要评审决定的地方**

- **诊断结构**：选冻结 Pydantic 模型，固定字段为 `level/category/stage/source/objects/rule/actual/expected/consequence/next_step`。只有 `expected` 可空，默认 `None`；其余必填。文本拒绝空串、纯空白，不自动裁剪。对象为有序、键不重复的不可变键值对；值只收字符串，数字由生产者转成带明确单位的文本。空对象表示全局问题。这样避免身份被隐式转换，也能直接生成 OpenAPI。

- **枚举**：`ERROR → error → 错误`、`WARNING → warning → 警告`；类别为 `INPUT/input/输入或数据问题`、`CONFLICT/conflict/冲突`、`EXTERNAL/external/外部失败`、`DEFECT/defect/程序缺陷`。工具来源不能产生冲突。

- **文本渲染**：摘要为“来源在阶段发现类别（级别）：规则”；随后固定五行对象、规则、实际与期望、后果、检查。对象保持输入顺序，键和值用 JSON 双引号转义；期望为空时省略期望标签。消息不缩进，由 `RuntimeFormatter` 加四格；控制字符转义，避免额外日志行。

- **聚合**：按 `(source, rule)` 分组，组按首次出现排序，样例保持输入顺序。每组共用前 10 条配额，不按级别另开组；`error_count`、`warning_count` 分别完整计数。跨阶段、类别仍按同一来源和规则合并。内存随组数增长，因此调用方仍须控制规则基数。

- **四类异常**：前三类至少带一条同类别的 ERROR 诊断；`DefectError` 默认空元组，也允许安全的结构化上下文。输入基类默认 400，子类仅可选 400/404/422；其余固定 409/502/500。构造器拒绝类别、级别和状态不匹配。

- **HTTP 格式与隐私**：采用 `about:blank`，`title` 用标准 HTTP 英文短语，`detail` 用中文；扩展字段为 `category/diagnostics/error_id`。错误编号取当前请求编号。参数校验逐项生成诊断，完全不回显 `input/msg/ctx/body`；未声明的动态字段名也遮蔽。日志只记方法和路由模板，不记查询串、路径参数实值、凭据或请求体。

- **只报告一次**：已核对本地 Starlette 和 uvicorn 源码。契约顺序为 `RequestIdMiddleware → ErrorBoundary → 完整 FastAPI 栈`。未知异常处理器只构造响应，外层记录一次并消费重抛；流式中途和后台任务异常也覆盖。**需评审确认**：流式失败保留已发送前缀，不伪造成功结尾；uvicorn 关闭未完成连接时，仍可能另记一条不含 traceback 的协议日志。取消等 `BaseException` 原样传播。

- **完整异常报告的脱敏范围**：保留异常类型、完整链关系及全部栈帧位置，去掉局部变量、源码行、notes；未知异常的原始消息统一隐藏，安全上下文由诊断补充。**需重点评审**：这是为了满足 6.10 的保守选择，会损失第三方异常原文；“完整”指链与栈结构完整。

- **框架 HTTP 错误**：保留 Starlette 的 404/405、`_unknown_api` 和 SPA 回退原行为及响应头，避免改变第 2、3 张已批准契约。领域错误使用四类异常；前端遇到这些非 problem 响应显示统一不可用提示。

- **OpenAPI 与骨架接入**：本轮只在 `create_app` 登记组件并生成类型，未让请求调用占位函数。为此提前缓存了 schema，测试后挂路由需清缓存。派工 B 按 `install_error_handlers` 契约启用处理器和外层边界，并为已知 API 路由登记错误状态的 problem schema；届时替换提前缓存做法。工厂签名不变。

- **作业结果**：整体中止优先为失败；其次全部失败、部分失败；零失败按警告数区分成功和带警告成功。空作业未中止时也按警告数判断；部分失败加警告仍为部分成功。负数、失败数超总数、非严格整数及非 bool 中止标志均拒绝。

- **前端与演示**：卡片类型取生成 schema。非 problem、网络失败及代理 HTML 由适配层转成固定文案，不展示原始错误；有合法响应头编号才保留。缺陷详情默认展开后提示按编号查运行日志；可选回调留给第 5 张，超时定为 5000 毫秒。演示只由 `tests/diagnostics_demo.py` 显式挂载，不加配置项，生产工厂没有演示路由。

- **M4 字段核对**：普通诊断事件的字段均能承载，来源由平台补充。三层错误链保留在异常链与日志中，不放入诊断 JSON；工具“致命错误”的一句话和完整链由 M4 事件信封、后续报错记录承载，不强行编造五段诊断。这部分未来仍需落实存储与关联。

- **M1 两级核对**：**不能直接把“需要处理/提示”等同于“错误/警告”**。例如存储根离线在面板是“需要处理”，对扫描作业却是警告。建议 M1 用面板问题自身的优先级表达这两级，诊断级别继续表达失败影响；本轮没有擅自增加诊断级别或字段。