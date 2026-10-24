评审发现下面的问题，逐条修复，别处不动。规划文件照旧读主仓库目录 /home/shawn/桌面/robot-data-platform 里的版本（工单 Comments 最后一条是这份修复清单）。改测试时照样先看到它红，再改实现；只改测试本身的条目（第 1、6 条）在最终回复里说明新断言第一次运行的结果。

1. 问题：代表性故障示例二的测试没有走真正的意外异常路径。示例二是"解析代码没有处理 null"，也就是一个未预料的 `TypeError` 直接冒到接口边界；现在的测试把它包成两层 `DefectError` 再抛，走的是显式缺陷处理器，没有经过 `ServerErrorMiddleware → ErrorBoundary`。另外，它断言了 `calculate_outcome(...)`，但示例二是一次接口请求，没有作业。
   位置：`tests/test_api_errors.py` 的 `test_representative_platform_defect`（约第 768 行起）。
   期望：测试路由里不包装，直接让一个 `TypeError`（照示例二，`Path(raw["target"])`，`target` 为 `None`）从嵌套函数冒出来，经过真实的应用（`create_app` 加测试路由）返回。断言：500；`application/problem+json`；`category` 是 `defect`；`diagnostics` 为空；`error_id` 等于 `X-Request-ID`；响应体里没有 `Traceback`、`TypeError` 和文件路径。运行日志里：这个请求只有一条 ERROR，带同一个请求编号；只有一份 traceback，里面有 `TypeError` 的原始消息和出错的源码行（D2）。去掉作业结果的断言，在测试 docstring 里写明"示例二是接口请求，没有作业结果；作业结果由示例一的测试覆盖"。显式 `DefectError` 带诊断、带 cause 的情况，如果别的测试没覆盖到，可以另写一个测试，不要和示例二混在一起。

2. 问题：`logger = logging.getLogger(__package__)` 违反 CODING_STANDARDS 6.4（每个模块写 `logger = logging.getLogger(__name__)`），而且定义在模块中间。
   位置：`src/rdp/api/errors.py` 约第 486 行。
   期望：改成 `getLogger(__name__)`，放在 import 之后。相应的测试按 logger 名 `rdp.api.errors` 断言，或者断言 logger 名以 `rdp.api` 开头，二选一，在测试里写明。

3. 问题：注释和文档还停在派工阶段的说法上（CODING_STANDARDS 4.2、4.4：注释不能过期）。
   位置：`src/rdp/api/errors.py` 的 `install_error_handlers` docstring（"供 create_app 在派工 B 接入""在 B 中改成 RequestIdMiddleware(ErrorBoundary(...))"）；`src/web/src/api/problems.ts` 约第 72 行（"派工 B 中 createHealthClient 使用本包装器"）。整个 diff 里再搜一遍"派工 B""骨架""在 B 中"之类的字样。
   期望：只写现在的行为，例如"create_app 调用本函数""RequestIdMiddleware 包在 ErrorBoundary 之外"。这类改动只改措辞，不改含义。

4. 问题：后端代码里有 3 份类别到状态码的映射：`diagnostics.py` 的 `_validate_exception` 里的 `allowed`、`errors.py` 的 `ProblemResponse._validate_problem` 里的 `allowed`、`_document_problem_responses` 里的 `(400, 404, 422, 409, 502, 500)`。CODING_STANDARDS 6.2 要求"新状态码先改表再改代码"，代码里只能有一处要跟着改。
   位置：上面三处。
   期望：在 `rdp.infra.diagnostics` 里定义一个公开的具名常量（类别 → 允许的 `HTTPStatus` 元组；注释写含义，并写明以 CODING_STANDARDS 6.2 为准），三处都从它取。`errors.py` 模块 docstring 里那张表照留（工单要求）。前端 `problems.ts` 里做运行时校验的那份保留，在注释里写明它对应 6.2、改表时要一起改。状态码测试（6.2 表逐项核对）改成核对这个常量和四个基类，仍要逐项写出期望值，不能从常量推出期望值。

5. 问题：网页卡片有三处和代表性故障示例、日志不一致：不显示类别；错误编号只有一串十六进制，没有标签，而且带诊断的卡片根本不显示编号（6.2：每个错误响应都带 `error_id`，用来在运行日志里找完整报错）；第五段在日志里叫"检查："，在网页上叫"下一步："。
   位置：`src/web/src/DiagnosticCard.tsx`。
   期望：
   - 每条诊断的标题行显示级别、类别中文名、阶段、来源，例如"错误 · 外部失败 · 解码 · 来源：mcap2lerobot"。
   - 所有 problem 卡片（带诊断的、不带诊断的、程序缺陷）都显示"错误编号：<编号>"；unavailable 有编号时也这样写。
   - 第五段标签和日志、示例一致，用"检查："。
   - 改 TSDoc 和对应测试，测试先红后绿。类别中文名和后端一致（输入或数据问题、冲突、外部失败、程序缺陷）。

6. 问题：`test_handler_mappings_and_media` 的 docstring 写的是 400/404/422/409/502/500 都经真实 ASGI 验证，实际 404 子类和 422 子类只在 `build_problem` 的单测里测到。
   位置：`tests/test_api_errors.py` 的 `test_handler_mappings_and_media`。
   期望：补上 `InputError` 的 404 子类和 422 子类经真实应用返回的用例，同样断言状态码、`application/problem+json`、`category`、`error_id` 等于 `X-Request-ID`。

7. 问题：参数校验失败（422）的运行日志只有一句"请求参数不符合要求，请查看诊断。"，看不出是哪个字段出错。
   位置：`src/rdp/api/errors.py` 的 `_report_error`。
   期望：参数校验失败时，把 `problem.diagnostics`（只含字段位置，不含原值）照五段渲染追加到日志；仍然不格式化 `RequestValidationError` 本身，不出现原值。补一个测试：日志里有字段位置，没有请求里的原值（例如口令）。`handle_error` 的 `Side Effects:` 说法如果要跟着改，只改措辞。

修完后 `make check` 全绿，pytest 和 Vitest 都没有 skipped。

边界：
- 只改 `src/`、`tests/`。本票允许改的受保护文件：`pyproject.toml`（只改 `[tool.importlinter]`；本轮应当不用动）。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。
- 不安装任何东西，不访问网络（沙箱为了跑测试开了网络权限，但这张票用不到网络；评审会查运行日志，出现安装或联网的命令整轮打回）。需要新依赖时停下，在最终回复里写依赖申请（AGENTS.md 规则 7）。
- 自己在 `/tmp` 或别处建的试验文件，交付前删掉。不写 `.git/info/exclude`。

最终回复：逐条写处理结果，每条附改动的文件和新测试第一次运行的结果；`make check` 最后一次运行的命令和末尾输出，原样贴出，再原样贴出跑之前和跑之后的 `git status --porcelain --untracked-files=all`。契约变更申请：没有就写"无"；第 3、5、7 条改了哪些 docstring/TSDoc 的哪几句，逐条列出。
