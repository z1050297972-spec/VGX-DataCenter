# /code-review：M0-04 B-done（快照 16bb2a7，基点 f19f883）

两轴评审由两个只读子 agent 并行完成，在检出 `refs/rdp/m0-04/B-done` 的探针工作目录里跑。下面按原文整理，没有合并或重排。

## Standards

**有据可依的违规（按"硬"处理，但都不大）**

1. `src/rdp/api/errors.py:486-487`：`logger = logging.getLogger(__package__)`。
   - 违反 CODING_STANDARDS 6.4（每个模块写 `getLogger(__name__)`）。
   - 注释说"本票指定统一边界的记录归 rdp.api"，但工单只说处理放在 `rdp.api` 包里，没有指定 logger 名。
   - logger 定义在模块中间，不在 import 之后。
2. 注释停留在派工阶段的说法，违反 4.4 和 4.2（注释不能过期，要写"为什么"）：
   - `errors.py:369`、`:377-378`：`install_error_handlers` 的 docstring 还写着"供 create_app 在派工 B 接入""在 B 中改成 RequestIdMiddleware(ErrorBoundary(...))"。
   - `problems.ts:72`：写着"派工 B 中 createHealthClient 使用本包装器"。
3. `DiagnosticCard.tsx:267` 的 `loadDetails` 和 `ERROR_DETAILS_TIMEOUT_MS` 在生产代码里没有调用方。
   - 按 2.9（新加的抽象要有当前的调用方）算不通过。
   - 骨架关卡已经认可"留给第 5 张"，算获批的例外。

**坏味道（都是判断题）**

- **Duplicated Code / Shotgun Surgery**：6.2 的状态码表在 diff 里有 5 份。
  - `errors.py` 的 docstring 有一份，这是工单要求的。
  - 另外 4 份是代码里的映射：`diagnostics.py:433-442`、`errors.py:87-92`、`errors.py:516`、`problems.ts:233-240`。
  - 建议后端只在 `diagnostics.py` 留一份映射，其他地方都引用它。
- **Duplicated Code**：四个异常基类的 `__init__` 和 docstring 几乎逐字相同。可以抽一个私有公共基类。
- **Repeated Switches**：`(InputError, ConflictError, ExternalError[, DefectError])` 这组 isinstance 元组在 `errors.py` 里反复出现。
- **跨语言重复**：
  - `problems.ts` 的 `requestId` 正则抄了后端的 pattern，其实可以从 apiSchema 读。
  - 必填字段清单是手写的。
  - "冲突只能由平台报告"这条规则在前端又写了一遍。
- **展示口径不一致**：
  - 级别的中文名在后端写在函数内部，类别的中文名却集中定义，同一个文件里口径不一。
  - 前端卡片硬编码"错误/警告"。
  - 第五段标签：后端写"检查："，前端写"下一步："。
  - 前端卡片不显示类别。

**没发现问题的方面**

- 1.3：领域层没有引入 Web 类型。
- 6.8：`calculate_outcome` 是唯一的计算处。
- 6.3：三处边界之外不打日志。
- 6.10：参数校验失败不回显原值，日志不记查询串。
- 5.3 / 10.3：常量带单位后缀。
- 10.1 / 10.4：只用相对路径，不直接调用 `fetch`。
- 没有新增豁免；`pyproject.toml` 只改了 import-linter 那一段，并写了理由。

## Spec

**结论**：功能主体都在，没有阻断性问题。要改的有 1 处（示例二的测试），另有 2 处小毛病和几处可以接受的超范围。

**(a) 缺失或不完整**

1. `test_handler_mappings_and_media` 的 docstring 写的是 400/404/422/409/502/500，实际只测了 InputError 基类的 400、参数校验的 422 和另外三类。
   - 404 子类只在 `build_problem` 单测里测到，没有走真实 ASGI。
   - 按"每类至少一个"不算违规，但 docstring 和实际不符。

**(b) 超出范围（都不大，多数在骨架关卡已接受）**

- `loadDetails` 回调和 5 秒超时。
- traceback 的循环引用标记。
- `_validation_location` 按路由声明逐段比对字段路径。
- `ProblemResponse.error_id` 写死成 uuid4 hex 的正则：按 E2，作业的错误编号是作业编号，以后复用这个模型时格式对不上。现在只影响接口。

**(c) 看似实现但有问题**

1. **示例二（验收 1「平台自身的缺陷」）**。示例写的是"解析代码没有处理这种情况"，也就是一个没预料到的 `TypeError` 直接冒到边界。测试却把它包成两层 `DefectError` 再抛，走的是显式缺陷处理器，没有走 `ServerErrorMiddleware → ErrorBoundary` 这条真正的意外异常路径。
   - 作业结果的断言（`calculate_outcome(total=1, failed=1, aborted=True)`）和场景对不上：示例二是一次接口请求，没有作业。
   - `DefectError` 的消息固定是"程序缺陷"，所以 traceback 链里的中间层只剩这四个字，可读的上下文丢了。
2. **用词不一致**：网页写"下一步："，日志写"检查："。日志的请求行写的是路由模板，不是实际路径；这是骨架关卡已接受的隐私取舍。

**核对通过的**

- E1、E3、D1、D2、D3。
- 6.2 的状态码表写进了模块 docstring；表外的子类状态码在实例化时报错，有测试。
- 每类异常都有接口测试，断言了 `Content-Type`、`category`，以及 `error_id` 等于 `X-Request-ID`。
- 只报告一次：用真实 uvicorn h11 驱动测过。
- 作业结果的五种边界。
- `Alert` 权宜已经删掉。
- `pyproject.toml` 只改了 import-linter。

（Spec 子 agent 借用工单工作目录的 `.venv` 跑测试时，有 2 个 import-linter 用例因为子进程起不来而失败。这是借环境造成的；执行线在工作目录里跑 `make check` 时它们都通过了。）

**合计**：Standards 3 条违规加若干坏味道，最重的是 logger 名和过期注释；Spec 1 条要改，是示例二没走意外异常路径。
