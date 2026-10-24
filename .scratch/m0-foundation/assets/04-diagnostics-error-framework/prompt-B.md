骨架已获批，契约提交是 `37871e4`（`契约：诊断与报错框架`），内容就是你派工 A 交的骨架。工作目录现在是干净的。

动手前先用绝对路径重读主仓库目录里的两个文件：
- 工单 /home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/issues/04-diagnostics-error-framework.md，Comments 的最后三条是骨架评审意见、关卡摘要和负责人的决定（状态码、D1–D3）。
- /home/shawn/桌面/robot-data-platform/docs/standards/CODING_STANDARDS.md 的 6.2：主会话新写了 HTTP 状态码表，这是状态码的唯一规则来源。

现在按测试清单逐个函数实现，用 $tdd 和 $enterprise-coding：
1. 每次去掉一个测试的跳过，先单独运行它（Python 用 `.venv/bin/pytest tests/<文件>::<测试名>`，前端在 `src/web/` 里用 `node_modules/.bin/vitest run <文件> -t "<标题>"`），看到它失败，再写实现让它通过。评审会在运行日志里逐个核对每个测试都有一次实现前的失败运行。去掉跳过就直接通过的测试，在最终回复里逐个列出并说明原因（例如前一个测试的实现已经覆盖了它）。
2. 已获批的签名、类型和 docstring 不改，下面"已获批的契约变更"列的几处除外。还有别的地方确实要改时停下，在最终回复里写契约变更申请：哪个函数、改什么、为什么。
3. 最后 `make check` 全绿，测试里不留骨架阶段的跳过（pytest 和 Vitest 都没有 skipped）。

已获批的契约变更（负责人在骨架关卡批准，按下面改契约，并先改测试、后改实现）：
- **D1 诊断加可选的"错误链"字段**：`Diagnostic` 加一个可选字段（建议名 `error_chain`，类型是非空白文本的元组，默认空元组），从外到内每层一句话，例如代表性故障示例一的"转换 RB01_20261011103210456.mcap 失败 / 相机 head_left 解码失败 / 无法从 H.264 关键帧读取分辨率：流中没有关键帧"。
  - `render_diagnostic`：非空时在"检查："之后追加"错误链："几行，写法照示例一（第一层跟在"错误链："后面，后面每层另起一行，用"← "开头并对齐）；为空时不输出这几行，原来的六行不变。控制字符照样转义。
  - JSON：字段名固定，进 OpenAPI，`make api-types` 重新生成前端类型。
  - 前端 `DiagnosticCard`：非空时折叠显示，标题写层数（例如"错误链（3 层）"），点开才看到各层；为空时不显示。
  - 聚合、四类异常的规则不变；程序缺陷的响应仍然不带诊断。
  - 改 `Diagnostic` 的 `Attributes:`、`render_diagnostic` 的 `Returns:`、`DiagnosticCard` 的 TSDoc 和 `readProblemResponse` 的校验；`test_model_extra_fields` 里"拒绝 error_chain"那一半改成验证新字段的默认值和校验，渲染和卡片补对应的测试。
- **D2 traceback 保留异常消息和源码行**：`format_exception_report` 输出的异常链和 traceback 保留每层异常的类型和消息、每个栈帧的源码行，和代表性故障示例二一致；不打印局部变量。能直接用标准库 `traceback` 的默认格式就用，不要自己再造一套。删掉"异常消息已隐藏""不调用不可信异常的 `__str__`""不读取源码"这类规定；`__notes__` 照标准库的行为。防口令改靠两处：参数校验失败从不回显原值（`validation_diagnostics` 不变）；我们自己的 pydantic 模型都设 `hide_input_in_errors=True`。改 `format_exception_report` 的 `Returns:`、`Side Effects:` 和模块注释，`test_report_secret_redaction` 改成验证：消息和源码行都在，局部变量的值不在。只报告一次的要求不变。
- **D3**：诊断不加级别，不用改。

状态码（负责人："状态码要记录清楚，并在后续的文档中声明"）。照 CODING_STANDARDS 6.2 的表做三件事：
1. `rdp.api.errors` 的模块 docstring 写同一张表（状态码、类别、什么时候用），并写明以 CODING_STANDARDS 6.2 为准、新状态码先改那张表再改代码。
2. 一个测试逐项核对四个异常基类的状态码和表一致（输入或数据问题 400，子类只能选 400、404、422；冲突 409；外部失败 502；程序缺陷 500）；子类用了表外的状态码时构造报错，也要有测试（每类至少一个表外的例子，例如输入类用 403、冲突类用 400）。可以合并进现有的 `test_exception_subclass_status_validation`，也可以单独写一个，测试 docstring 写明它对应 6.2 的表。
3. 每类至少一个接口测试：经过真实的应用返回，断言状态码、`Content-Type` 是 `application/problem+json`、`category` 字段，以及响应体里的 `error_id` 等于响应头 `X-Request-ID`。参数校验失败（422）也要有一个。
- **你的实现和这张表有任何不一致的地方（例如 422 的用法、框架自己的 404/405），不要改表，也不要自己改成和表一致：停下来，在最终回复第 4 块写清楚哪里不一致。**

评审意见（不改含义，照做）：
- `create_app` 里骨架期"提前缓存 OpenAPI、只登记组件"的权宜，换成 `install_error_handlers` 的按需合并；删掉 `create_app` 的 docstring 和函数体里所有骨架期的说明（"工单 04 骨架额外登记……""派工 B 的接入契约见……"那几句和对应注释），只写接入以后的行为。`create_app` 的签名不变。
- 删掉 4 条骨架期的 `eslint-disable-next-line @typescript-eslint/no-unused-vars`。
- `HealthPage` 换成 `DiagnosticCard`：删掉 `Alert` 的 import、权宜注释和"请求失败的 Alert"相关的 TSDoc 说法；原来"失败页面显示 Alert"的测试改成验证卡片。第 2 张的成功、加载、超时行为不变。
- 显式的四类异常和参数校验失败在运行日志记 ERROR；Starlette 自己的 404/405 保持原格式（和 6.2 表的最后一行一致）。
- 演示由执行线在沙箱外做（起应用、截真实页面），你不用起服务器；`tests/diagnostics_demo.py` 按契约实现即可。
- 测试不依赖本机时区（本机是 −06:00，负责人决定保持现状），不改进程的全局时区；测试结束后恢复全局 logging 状态。驱动 uvicorn 的测试用内存 transport，不监听端口。

边界：
- 只改 `src/`、`tests/`。本票允许改的受保护文件：`pyproject.toml`（只改 `[tool.importlinter]`；派工 A 已经改好，B 里应当不用再动）。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。
- 不安装任何东西，不访问网络（沙箱为了跑测试开了网络权限，但这张票用不到网络；评审会查运行日志，出现安装或联网的命令整轮打回）。需要新依赖时停下，在最终回复里写依赖申请（AGENTS.md 规则 7）。
- 自己在 `/tmp` 或别处建的试验文件，交付前删掉。测试不碰真实的 `~/.config/rdp`、`~/.local/share/rdp`，不写 `.git/info/exclude`。

最终回复分五块：
1. 改动清单：每个文件一行，写做了什么。
2. `make check`：最后一次运行的命令和末尾输出，原样贴出（pytest 和 Vitest 那两步要能看出 passed 和 skipped 的数目，应当没有 skipped）。再原样贴出跑之前和跑之后的 `git status --porcelain --untracked-files=all`。
3. 契约变更申请、依赖申请：没有就写"无"。另外逐条列出你按 D1、D2 改了哪些 docstring/TSDoc 的哪几句。
4. 拿不准、需要评审决定的地方，包括和 6.2 状态码表不一致的地方（没有就写"无"）。
5. 先红后绿：每个测试一行，写它第一次运行的结果（失败的原因，或者为什么一开始就通过）。
