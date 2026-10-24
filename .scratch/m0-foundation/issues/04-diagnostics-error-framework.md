# 诊断与报错框架

Status: in-review

## 依据

- M0 spec 第 04 张。
- 「可观测性与报错规范」（`.scratch/platform-v1/issues/09-observability.md`）Answer：诊断五段、四类报错和 HTTP 状态码、只报告一次、作业结果四种、"总数加样例"。ADR 0004。`CODING_STANDARDS.md` 第 6 条，前端 10.5。
- 代表性故障示例：`.scratch/platform-v1/assets/09-observability/代表性故障示例.md`，本票的测试和演示以它为准。
- 依赖：第 3 张合并以后开工（诊断的文本要写进运行日志）。

## 目标

平台里所有"出了什么问题"的信息，都用同一种诊断对象表达，再由它渲染成日志文本、接口 JSON 和网页上的五段卡片。任何异常在接口边界只报告一次，并且按"该由谁处理"归到四类之一。

## 范围

**诊断对象**（`rdp.infra.diagnostics`；基础层，因为每一层都要用）
- 字段：级别（错误、警告）、类别（输入或数据问题、冲突、外部失败、程序缺陷）、阶段、来源（"平台"或工具名）、对象（有序的键值对）、规则、实际、期望、后果、下一步。不可变。
- 渲染成运行日志的多行文本：首行是一句话摘要，五段作为缩进的明细行（第 3 张留好的写法）。
- 渲染成 JSON（接口和作业记录用），字段名固定，前端的类型由 OpenAPI 生成。
- **聚合**：同一类诊断（同一来源、同一规则）只保留前 N 条样例，总数始终完整。N 是具名常量，见「待负责人确认」第 1 条。

**四类异常**（同一模块）
- 四个基类，各带一条或多条诊断。平台以后所有自定义异常都从这四个之一派生（6.2）。
- HTTP 状态码映射：输入或数据问题 400、404、422（由子类定），冲突 409，外部失败 502，程序缺陷 500。

**接口的统一异常处理**（`rdp.api`）
- 四类异常转成统一的错误响应，格式见「待负责人确认」第 3 条。
- FastAPI 自己的参数校验失败（422），也转成"输入或数据问题"的诊断，每个出错的字段一条。
- 其他意外异常算程序缺陷：响应里只有一句话和错误编号；完整的异常链和 traceback 写进运行日志，并且能通过错误编号在页面上点开看（所有登录账号都能看，09 的结论）。错误编号见「待负责人确认」第 2 条。
- 只在这里记录一次，中间层不打日志（6.3）。

**作业结果**（`rdp.jobs.outcome`，领域层的第一个模块）
- 一个函数，输入是计数（总条目、失败条目、警告数，以及作业是否整体中止），输出四种作业结果之一：成功、带警告成功、部分成功、失败。规则照 09 的定义。别处不允许直接赋值作业结果（6.8），评审时查。
- 这是纯函数，没有数据库和进程。作业框架（第 8 张）直接用它。

**前端**
- 一个诊断卡片组件，五段对照显示，实际和期望放在同一行（10.5）。程序缺陷只显示一句话和错误编号，点开看完整报错。
- 第 2 张的权宜（请求失败时只显示 `Alert`）换成这个组件，去掉那段权宜注释。

**手册**：在使用手册里写一节"怎么看报错"：四类报错各是什么意思、谁该处理、错误编号怎么用。

## 不在本票

- 工具上报协议的解析（M4）；作业日志里的诊断（第 8 张）。本票的诊断对象要能承载这两处，但不实现它们。

## 允许改的受保护文件

| 文件 | 允许做什么 |
|---|---|
| `pyproject.toml` | 只改 import-linter：登记领域层 `rdp.jobs` 的位置（入口层 → 领域层 → 基础层），每条写理由 |

不需要新依赖。

## 验收

1. **代表性故障示例**：示例里的两个故障（转换作业部分成功、平台自身的缺陷），各写一个测试，断言对象身份、实际值、后果和最终的作业结果，不对整段文本做快照（6.11）。
2. **四类映射**：每类异常经接口返回对应的状态码和错误响应；参数校验失败返回 422，每个字段一条诊断；意外异常返回 500，只有一句话和错误编号，响应里没有 traceback。
3. **只报告一次**：一个意外异常在运行日志里只出现一次完整的 traceback，带请求编号。
4. **聚合**：同一类诊断来 N+1 条时，保留 N 条样例，总数是 N+1；不同类的不互相挤占。
5. **作业结果**：四种结果的边界各有测试：0 失败 0 警告、0 失败 1 警告、部分失败、全部失败、整体中止。
6. **前端**：诊断卡片的五段都显示；程序缺陷点开才看到完整报错；第 2 张的 `Alert` 权宜已去掉。
7. **import-linter**：`rdp.jobs` 不 import `rdp.api`、`rdp.ops`；`rdp.infra` 不 import `rdp.jobs`。
8. **先红后绿、文件归属、契约**：同第 2 张的验收第 12 条。
9. **能演示**：Claude 起应用，用一个只在测试配置里打开的演示接口，分别触发四类报错，截图放进 assets。演示接口在生产配置里不存在。

## Claude 的步骤

按 `codex-workflow.md` 3.1–3.7 走，不用拆段：开票 → 派工 A → 骨架关卡交负责人 → 契约提交 → 派工 B → 评审 → 负责人"合并"。违规试验加一项：`rdp.infra` 里 import `rdp.jobs` 被 import-linter 拦住。

## 风险

- **诊断对象的字段以后要加**：M4 的工具上报、M1 的一致性面板都会用它。字段在本票定下来以后，加字段要回到骨架关卡；所以骨架关卡时要对着 M1 的一致性面板（「数据集板块的数据契约」的四组两级）和 09 的工具事件字段，核一遍够不够用。
- **错误编号的查询**：本票只能在运行日志里按编号找到 traceback。网页上点开看完整报错，需要把 traceback 存起来；存在哪里，见「待负责人确认」第 2 条。

## 待负责人确认

1. **同一类诊断保留 10 条样例？** 例如一次转换里 5000 帧超出容差，只保留前 10 帧的明细，加上总数 5000。网页、作业记录、作业日志用同一个数。
   - 建议：10。以后觉得不够，改常量就行。
2. **错误编号就用请求编号，traceback 存进数据库的"报错表"，保留 30 天？**
   - 接口的意外异常，错误编号就是这次请求的请求编号（第 3 张已经放进响应头 `X-Request-ID`），不另造一种编号。作业里的意外异常，用作业编号。
   - traceback 存进数据库，页面按编号点开看，30 天后和运行日志一起清除。数据库在第 5 张才有，所以本票先写进运行日志，存表的那一步放到第 5 张做。
   - 建议：是。
3. **接口的错误响应用 RFC 9457 的 `application/problem+json`？** 这是 HTTP API 报错的标准格式（`type`、`title`、`status`、`detail`），我们在里面加三个扩展字段：类别、诊断列表、错误编号。按"先用现成的"，用标准格式，不自创。
   - 建议：是。

## Comments

- 2026-10-23，起草（主会话）。等负责人过目，回答「待负责人确认」后改成 `ready-for-agent`；第 3 张合并以后才能开票。
- 2026-10-23，负责人批准本票（"都按推荐来"）：
  - **E1**：同一类诊断（同一来源、同一规则）保留 10 条样例，总数完整。
  - **E2**：接口的错误编号就是请求编号，作业里的就是作业编号；完整报错存进数据库保留 30 天，存表的那一步放到第 5 张，本票先写运行日志。
  - **E3**：接口错误响应用 RFC 9457 `application/problem+json`，扩展字段：类别、诊断列表、错误编号。
  - Status 改成 `ready-for-agent`。等第 3 张合并以后再开票。

- 2026-10-24 11:55（+08:00），第 1 步开票（执行线）。扫过 `.scratch/m*/issues/*.md` 的 `Status:` 行：01、02、03 是 done，其余都是 `ready-for-agent`，没有别的实现票在进行中；没有在跑的 `codex exec`。Status 改成 `in-progress`。`git worktree add -b t/m0-04-diagnostics-error-framework ~/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework main`，在 `f19f883`。`uv sync --frozen`、`src/web/` 里 `pnpm install --frozen-lockfile --offline`（0.6 秒）后，基线 `make check` 十一步全绿：ruff 通过；basedpyright `0 errors, 0 warnings, 0 notes`；import-linter `2 kept, 0 broken`；契约检查 `问题总数: 0`；pytest `232 passed, 1 warning`（warning 是第 2 张就有的 starlette `StarletteDeprecationWarning`）；OpenAPI 过期检查"均未过期"；Vitest `19 passed`；用时 11.9 秒。跑前跑后 `git status --porcelain --untracked-files=all` 都为空；`core.hooksPath` 是 `.githooks`。输出在 `<执行线临时目录>/m0-04/baseline-check.txt`。
  - **和本票有关的框架事实**（执行线查过工作目录里 starlette 1.9.0 的源码）：`ServerErrorMiddleware` 调用 `Exception` 处理器、发出 500 以后会 `raise exc` 重新抛出，异常会继续传到外层的 `RequestIdMiddleware` 和 uvicorn，uvicorn 会再记一次 traceback。验收第 3 条"只出现一次 traceback"要在契约里处理这一点，已写进派工 A 的提示。
- 2026-10-24 12:00（+08:00），第 2 步派工 A（新会话）。
  - 提示 `assets/04-diagnostics-error-framework/prompt-A.md`：派工 A 模板，交付 `rdp.infra.diagnostics`（诊断对象、日志文本和 JSON 渲染、聚合、四类异常基类和状态码）、`rdp.api` 的统一异常处理、`rdp.jobs.outcome`、import-linter 登记 `rdp.jobs`、前端诊断卡片组件的契约，以及跳过的测试清单（pytest、Vitest）。要 Codex 在契约里定下并在最终回复里说明的：字段可空与值类型；枚举的英文名、JSON 值、中文名；日志摘要行写法；聚合的输入输出和顺序；程序缺陷带不带诊断；输入或数据问题基类的默认状态码；problem+json 扩展字段名和 `type`；参数校验失败回不回显原值（口令）；日志里的请求行；starlette `ServerErrorMiddleware` 重新抛出时怎么保证只有一次 traceback；Starlette 自己的 404/405 改不改成 problem+json；错误响应怎么进 OpenAPI；演示路由放在哪里（建议放 `tests/`，不加配置项）；作业结果的边界情况；"点开看完整报错"在本票显示什么；非 problem+json 响应怎么显示；诊断字段对着 09 的工具事件、示例里的"错误链"和 M1 一致性面板"两级"核一遍够不够用。允许改的受保护文件只有 `pyproject.toml` 的 `[tool.importlinter]`。`HealthPage` 换组件留给 B。
  - 快照 `refs/rdp/m0-04/A`（`fa70a52`，树和 `f19f883` 相同）。会话 `01a16c0b-b944-7562-888b-dc7fe018c60f`。
  - 命令：在工作目录里 `timeout 60m codex exec -C <工作目录> -s workspace-write -c 'sandbox_workspace_write.network_access=true' -m gpt-6-astra -c 'model_reasoning_effort="high"' --json -o assets/…/out-A.md - < prompt-A.md`。运行日志 `<执行线临时目录>/m0-04/ev-A.jsonl`、`err-A.txt`。
  - 派工前：codex-cli 0.163.0；网关 `10.1.179.3:8088` 直连 200。
- 2026-10-24 12:25（+08:00），派工 A 交回，第 3 步审骨架（`codex-workflow.md` 3.3）。
  - 运行：本机时间 21:54–22:14（−06:00），退出码 0，最后一条 `turn.completed`，`out-A.md` 在 assets；stderr 为空，开头的 `disable_response_storage` `error` 是已知现象。运行日志里唯一一处 "stream disconnected" 在 `cat docs/brief/*.md` 的输出里，不是网关断开。
  - **重跑**：工作目录 `make check` 退出码 0，十一步全绿，用时 11.1 秒：basedpyright `0 errors, 0 warnings, 0 notes`；import-linter `2 kept, 0 broken`（layers 合约插入了 `rdp.jobs`，forbidden 合约加了 `rdp.jobs`）；契约检查 `问题总数: 0`；pytest `232 passed, 92 skipped, 1 warning`（warning 同基线）；OpenAPI 过期检查"均未过期"；Vitest `19 passed | 33 skipped`。跑前跑后 `git status --porcelain --untracked-files=all` 相同。输出 `<执行线临时目录>/m0-04/A-done-check.txt`。
  - **文件归属**：工作目录改动 ` M pyproject.toml`、` M src/rdp/api/__init__.py`、` M src/web/src/HealthPage.test.tsx`、` M src/web/src/api/{openapi.json,schema.d.ts}`（`make api-types` 生成），新文件 `src/rdp/api/{_asgi,errors}.py`、`src/rdp/infra/diagnostics.py`、`src/rdp/jobs/{__init__,outcome}.py`、`src/web/src/{DiagnosticCard.tsx,DiagnosticCard.test.tsx}`、`src/web/src/api/{problems.ts,problems.test.ts}`、`tests/{diagnostics_demo,test_api_errors,test_diagnostics,test_diagnostics_demo,test_job_outcome}.py`。受保护文件只动了 `pyproject.toml` 的 `[tool.importlinter]`（+5/−3，两条注释写了理由），`Makefile`、`scripts/`、`.githooks/`、锁文件、前端配置都没动。主仓库目录 `-- src tests` 为空；非规划文件只有负责人的 `Read_First_What're_Files_Meaning?.md`。**通过。**
  - **运行日志**：45 条命令（读规划文件用主仓库绝对路径；读 starlette `middleware/errors.py`、`applications.py` 和 uvicorn `h11_impl.py` 的源码；用 python heredoc 写文件；`make api-types` 4 次；`make check` 6 次，前 4 次失败后修好）。两个旧项目的命中都在 `cat AGENTS.md`、brief 的输出里，没有命令碰它们或 `/mnt`；安装、联网命令的 grep 无结果；`/tmp` 只有 `make check-api-types` 自建自删的临时目录。命令清单 `<执行线临时目录>/m0-04/A-commands.txt`。**通过。**
  - **审骨架**：公开的 `render_diagnostic`、`aggregate_diagnostics`、四类异常的 `__init__`、`validation_diagnostics`、`build_problem`、`format_exception_report`、`handle_error`、`ErrorBoundary.__init__`/`__call__`、`install_error_handlers`、`calculate_outcome`、`mount_diagnostic_demo` 六项齐全，内容合格；`Diagnostic`、`DiagnosticObject`、`DiagnosticGroup`、`ProblemResponse`、三个枚举都有 `Attributes:`；TS 的 `DiagnosticCard`、`readProblemResponse`、`createProblemFetch`、`toFailureView` 的 TSDoc 六项齐全。测试 92 + 33 个跳过，对着每条 `Raises:` 和验收第 1–7 条都找得到（验收 1 两个代表性故障、验收 3 用真实 `ServerErrorMiddleware` 和 uvicorn h11 驱动、验收 4 的 9/10/11 边界、验收 5 的五种边界、验收 7 的反向依赖植入）。新增豁免只有 4 条骨架期的 `eslint-disable-next-line @typescript-eslint/no-unused-vars`，写了理由，B 必须删。没有新依赖，没有契约变更申请。
  - **Codex 定下的要点**：诊断用冻结的 pydantic 模型，十个字段，只有"期望"可空，对象值只收字符串；只报告一次的办法是在请求编号中间件和整个框架栈之间加一层 `ErrorBoundary`，截住 `ServerErrorMiddleware` 重抛的异常，记一次日志后吞掉，流式中途失败和后台任务失败也覆盖；参数校验失败的诊断完全不回显原值；日志的请求行只写方法和路由模板，不写查询串和路径实值；Starlette 自己的 404/405 和 `/api` 兜底 404 保持原来的 JSON；"点开看完整报错"本票显示"请按错误编号在运行日志中查询完整报错"，组件留了一个取详情回调给第 5 张；演示路由在 `tests/diagnostics_demo.py`，生产代码里没有。
  - **评审意见，B 里处理，不用负责人拍板**：
    - `create_app` 里骨架期"提前缓存 OpenAPI、登记组件"的权宜，B 换成 `install_error_handlers` 的按需合并，并删掉 `create_app` docstring 和注释里的骨架期说明。
    - 删 4 条骨架期 `eslint-disable`。
    - `HealthPage` 换成 `DiagnosticCard`、删 `Alert` 权宜和注释（已在测试清单）。
    - 演示（验收 9）：页面目前只调 `/api/health`，要截到四类卡片，`mount_diagnostic_demo` 需要能让演示应用里的 `/api/health` 按选择抛四类之一（仍然只在 `tests/` 里）；B 的提示里补这一条，截图由执行线在沙箱外做。
    - 显式四类异常和参数校验失败在运行日志记 ERROR（6.5"某个操作失败了"），按 Codex 的定。
    - Starlette 的 404/405 保持原格式，前端遇到时显示固定的"请求失败"提示，按 Codex 的定；以后业务的"找不到"用输入或数据问题的 404 子类。
    - 流式响应中途失败时，uvicorn 可能另记一条不带 traceback 的"响应未完成"协议日志；验收 3 说的是 traceback 只有一次，可以接受。
    - 使用手册"怎么看报错"一节归 Claude 写（`docs/` 只由 Claude 改），评审通过后写。
  - 快照 `refs/rdp/m0-04/A-done`（`ae6ed5a`）。
- 2026-10-24 12:30（+08:00），**骨架关卡一页摘要**（执行线起草，交主会话转负责人）。
  1. **这张票做什么**：平台所有"出了什么问题"都用同一种诊断对象表达，渲染成日志文本、接口 JSON 和网页卡片；四类异常和 HTTP 状态码；接口边界只报告一次；作业结果由一个函数算出。
  2. **函数清单**：

     | 模块 | 函数 | 职责 | 改动什么 | 什么情况下报错 |
     |---|---|---|---|---|
     | `rdp.infra.diagnostics` | `Diagnostic`（模型） | 不可变诊断：级别、类别、阶段、来源、对象（有序键值对）、规则、实际、期望、后果、下一步；只有"期望"可空 | 无 | 字段缺失、空白、重复对象键、工具来源报"冲突" → pydantic `ValidationError`（不回显输入） |
     | 同上 | `render_diagnostic(d) -> str` | 渲染成日志用的六行：摘要 + 对象/规则/实际与期望/后果/检查 | 无 | 无 |
     | 同上 | `aggregate_diagnostics(ds) -> tuple[DiagnosticGroup, ...]` | 按（来源、规则）分组，每组保留前 10 条样例，总数、错误数、警告数完整 | 消费一次输入 | 混进非诊断项 → `ValueError` |
     | 同上 | `InputError` / `ConflictError` / `ExternalError` / `DefectError` | 四类异常基类，带诊断；状态码 400（子类可 404、422）/409/502/500 | 无 | 诊断为空（缺陷除外）、类别或级别不符、子类改了不允许的状态码 → `ValueError` |
     | `rdp.api.errors` | `build_problem(request, error)` | 异常转成 RFC 9457 `problem+json`：`type`=`about:blank`、`title`、`status`、`detail`，加 `category`、`diagnostics`、`error_id`（=请求编号） | 无 | 请求编号没绑定 → `RuntimeError` |
     | 同上 | `validation_diagnostics(...)` | 参数校验失败 → 每个字段一条 422 诊断，**不回显原值**（防口令） | 无 | 无 |
     | 同上 | `handle_error` / `ErrorBoundary` / `install_error_handlers(app)` | 统一异常处理；意外异常在最外层记一次完整 traceback，不让框架和 uvicorn 再记 | 写运行日志一次 | 中间件栈已建好后再安装 → `RuntimeError` |
     | 同上 | `format_exception_report(e) -> str` | 生成写进日志的异常链和 traceback | 无 | 无（脱敏程度见问题 2） |
     | `rdp.jobs.outcome` | `calculate_outcome(*, total_items, failed_items, warning_count, aborted) -> JobOutcome` | 四种作业结果；中止一律失败；部分失败加警告仍是部分成功；空作业按警告数 | 无 | 负数、失败多于总数、类型不对 → `ValueError` |
     | 前端 | `DiagnosticCard`、`readProblemResponse`、`createProblemFetch`、`toFailureView` | 五段卡片（实际与期望同一行）；程序缺陷只显示一句话和编号，点开才看详情；非 `problem+json` 的失败（断网、代理 HTML）显示固定文案 | 无 | 无（都转成固定提示） |

     `pyproject.toml` 只改 import-linter：`rdp.jobs` 登记为领域层，也不许 import Web 框架。演示路由在 `tests/` 下，生产代码里没有。
  3. **测试清单**（125 个，都先跳过）：诊断 32（字段校验、六行渲染、10 条样例的 9/10/11 边界、不同组不挤占、四类异常构造、示例一"转换部分成功"）；接口 40（四类和校验失败的状态码与媒体类型、不回显口令、日志只记一次——用真实的框架错误中间件和 uvicorn 驱动、流式中途失败、后台任务失败、并发编号不串、OpenAPI 里有错误响应、示例二"平台缺陷"）；作业结果 16（五种边界、非法计数、import-linter 反向依赖被拦）；演示 4；前端 33（卡片五段、缺陷折叠与展开、非 problem 响应、`HealthPage` 换组件）。
  4. **要负责人拍板的**：
     1. **诊断要不要加一个可选的"错误链"字段？** 代表性故障示例一里，工具报的 ERROR 诊断带三层错误链（"转换文件失败 ← 相机解码失败 ← 流中没有关键帧"）。Codex 的方案是错误链只放在异常和日志里，诊断不带。这样平台自己的异常没问题，但 M4 接工具时，工具报的错误链没地方放，到时要加字段、回到骨架关卡。
        - 建议：现在就加，可选，默认空（从外到内的几行文字）；日志里写成"错误链："几行，网页上折叠显示。
     2. **日志里的 traceback 要不要保留原始报错文字？** Codex 为了防止口令进日志，把平台四类以外的异常消息一律换成"异常消息已隐藏"，源码行也去掉。这样示例二那行关键信息 `TypeError: expected str, bytes or os.PathLike object, not NoneType` 就看不到了，排查会很难。
        - 建议：保留异常消息和源码行，和示例二一致（不打印局部变量，标准库默认也不打）。防口令靠两处：参数校验失败从不回显原值；我们自己的模型都设了"报错不回显输入"。
     3. **M1 一致性面板的"需要处理 / 提示"两级怎么对应？** 诊断只有错误、警告两级，表示对作业的影响；面板的两级是"要不要人去处理"，两者不一样（例如存储根离线：面板上"需要处理"，对扫描作业只是警告）。
        - 建议：同意 Codex 的意见，诊断不加级别；M1 在面板条目上另加"处理优先级"，不改诊断对象。
  5. **结论：建议通过**（问题 1、2 按建议在派工 B 里改；问题 3 只影响 M1）。检查都由执行线重跑过：`make check` 十一步 11.1 秒全绿，跑完不留痕迹；文件归属干净；运行日志没有碰旧项目、`/mnt`，没有安装和联网命令；没有新依赖；没打回（0 轮）。负责人说"通过"以后，做契约提交 `契约：诊断与报错框架`，Status 改回 `in-progress`，派工 B。
  - Status 改成 `in-review`，交回主会话。
- 2026-10-23，骨架关卡：负责人回复"1.状态码要记录清楚，并在后续的文档中声明；其他按照你的推荐来"，主会话按通过处理。
  - **状态码**：主会话把完整的状态码表写进 `CODING_STANDARDS.md` 6.2（400、404、422、409、502、500，401/403 留给第 6 张，框架自己的 404/405），并规定"新状态码先改表再改代码"。派工 B 要做到：
    1. `rdp.api.errors` 的模块 docstring 写同一张表，指向 CODING_STANDARDS 6.2。
    2. 一个测试逐项核对四个异常基类（以及输入类允许的 400/404/422）的状态码和表一致；子类改成表外的状态码时报错，有测试。
    3. 每类至少一个接口测试，断言状态码、`Content-Type: application/problem+json`、`category`、`error_id` 等于响应头 `X-Request-ID`。
  - 后续文档：使用手册"怎么看报错"、运维手册"按错误编号查日志"两节由主会话在合并后写，都带这张表的简表；第 6 张合并时把 401/403 补进表里（已在第 6 张记一条）。
  - **D1**：诊断加可选的"错误链"字段，默认空；日志里写成"错误链："几行，网页上折叠显示。契约变更，已获批。
  - **D2**：日志里的 traceback 保留异常消息和源码行，不打印局部变量；防口令靠"参数校验失败不回显原值"和"自己的模型报错不回显输入"。契约变更，已获批。
  - **D3**：诊断不加级别；M1 在一致性面板条目上另加"处理优先级"。
  - 执行线列的"B 里处理"各项照办。
- 2026-10-24 12:55（+08:00），第 4 步契约提交（执行线）。先核对工作目录的树和快照 `A-done` 相同（`236de4c`），再 `git add -A`，普通 `git commit`：`37871e4 契约：诊断与报错框架`，经过钩子，十一步全绿；提交后工作目录干净。D1、D2 和状态码的三件事留给派工 B 改，契约提交用的是 `A-done` 的原样。Status 改回 `in-progress`。
  - 核对了 6.2 的状态码表和骨架契约：400/404/422 归输入或数据问题、409、502、500、框架 404/405 保持原格式，和骨架一致，没有发现冲突。
- 2026-10-24 13:00（+08:00），第 5 步派工 B（续接）。
  - 提示 `assets/04-diagnostics-error-framework/prompt-B.md`：派工 B 模板（逐个测试单独跑、先红后绿，pytest 和 Vitest 都写了单独运行的命令），加上已获批的契约变更 D1（诊断加可选的 `error_chain`，日志写"错误链："几行、网页折叠显示）、D2（traceback 保留异常消息和源码行、不打印局部变量，尽量用标准库 `traceback`）；状态码三件事（`rdp.api.errors` 模块 docstring 写 6.2 的表；测试逐项核对四个基类和表外状态码报错；每类一个接口测试断言状态码、媒体类型、`category`、`error_id` 等于 `X-Request-ID`），并要求和表不一致时停下报告、不改表；评审意见（换掉 `create_app` 的骨架期权宜和说明、删 4 条 `eslint-disable`、`HealthPage` 换卡片、ERROR 级别和框架 404/405 按 Codex 的定、演示由执行线做）。最终回复五块。
  - 演示改由执行线的演示脚本自己把 `/api/health` 换成抛四类之一的路由（脚本放 assets，和第 3 张的 `demo.py` 一样），不用改 `mount_diagnostic_demo` 的契约。
  - 快照 `refs/rdp/m0-04/B`（基于契约提交 `37871e4`，工作目录干净）。
  - 会话 `01a16c0b-b944-7562-888b-dc7fe018c60f`，先 `cd <工作目录>` 再 `timeout 60m codex exec resume -m gpt-6-astra -c 'model_reasoning_effort="high"' -c 'sandbox_mode="workspace-write"' -c 'sandbox_workspace_write.network_access=true' --json -o assets/…/out-B.md <会话> - < prompt-B.md`。运行日志 `<执行线临时目录>/m0-04/ev-B.jsonl`、`err-B.txt`。网关直连 200。
- 2026-10-24 13:50（+08:00），派工 B 交回，第 6 步评审（`codex-workflow.md` 3.5），逐项结论：
  1. **重跑**：运行本机时间 22:53–23:30（−06:00），退出码 0，最后一条 `turn.completed`，stderr 为空，没有网关断开（运行日志里唯一一处 "stream disconnected" 在 `cat` brief 的输出里）。工作目录 `make check` 十一步全绿，13.1 秒；pytest `327 passed, 1 warning`（warning 同基线），Vitest `54 passed`，都没有跳过；跑前跑后 `git status` 相同。**通过。**
  2. **文件归属**：工作目录只有 `src/`、`tests/` 下 20 个文件的改动（含 `make api-types` 生成的 `openapi.json`、`schema.d.ts`），没有新文件；受保护文件和锁文件对契约提交的 diff 为空。主仓库目录 `-- src tests` 为空，非规划文件只有负责人的 `Read_First_What're_Files_Meaning?.md`。**通过。**
  3. **对比契约**（对 `37871e4`）：签名和类型没变；docstring 的改动只有已获批的 D1（`Diagnostic` 加 `error_chain`、`render_diagnostic` 的 Returns、`DiagnosticCard`/`readProblemResponse` 的 TSDoc）、D2（`format_exception_report` 首行、Returns、Side Effects、模块注释）、状态码表（`rdp.api.errors` 模块 docstring），以及评审意见要求的 `create_app`、`HealthPage` 去掉骨架期说法。新增的都是私有辅助函数。**通过。**
  4. **先红后绿**：执行线从运行日志解析每个测试第一次单独运行的结果（`<执行线临时目录>/m0-04/B-redgreen.txt`）：pytest 95 个里 53 个先红、42 个一开始就绿，和 Codex 自报的表逐个一致；Vitest 先红、先绿也和自报一致。Codex 如实交代了 5 个前端测试第一次运行是被自己前一步的语法错误挡住的（不算有效的红），修好后其中 1 个出现了有效的功能失败。一开始就绿的比例高（约 45%），所以加做**变异抽查**（`assets/…/mutation_probe.py`，输出 `mutation_probe-B-done.txt`）：12 个变异覆盖 13 个一开始就绿的测试（聚合配额变全局、警告计成错误、对象排序、期望为空也输出、边界记完日志后重新抛出、响应已开始仍补发 500、吞掉 BaseException、日志写实际路径和查询串、校验诊断回显原值、traceback 打印局部变量、部分失败有警告判成带警告成功、中止且部分失败判成部分成功），**12 个全部被抓到**。**通过。**
  5. **运行日志**：543 条命令；没有一条碰两个旧项目或 `/mnt`；安装、联网命令的 grep 无结果；`/tmp` 下只有 `make check-api-types` 自建自删的临时目录和 pytest 的 `tmp_path`。命令清单 `<执行线临时目录>/m0-04/B-commands.txt`。**通过。**
  6. **两轴评审**：快照 `refs/rdp/m0-04/B-done`（`16bb2a7`），在探针工作目录里跑 `/code-review`（基点 `f19f883`），原文整理在 `assets/…/code-review-B-done.md`。本票不是同步、录制、转换模块，不跑 `algorithm-code-review`。要改的：示例二的测试没走意外异常路径；logger 名违反 6.4；三处注释还停在派工阶段；后端有 3 份状态码映射；网页卡片不显示类别、错误编号没标签、第五段叫法和日志不一致；接口测试 docstring 写了 404/422 子类但没走真实应用；422 的日志看不出哪个字段。**不通过**，进修复清单。坏味道里"四个异常基类重复、isinstance 元组反复出现"按判断题记下，本轮不要求改。
  7. **违规试验**：脚本 `assets/…/violation_probe.sh`（照第 3 张，加了工单规定的"`rdp.infra` 里 import `rdp.jobs`"，以及"`rdp.jobs` 里 import `rdp.api`""`rdp.jobs` 里 import `fastapi`"），输出 `violation_probe-B-done.txt`。基线全绿、跑完不留痕迹；12 种违规各失败在对应那一步，其中三条 import-linter 违规都被拦住；带理由的豁免照常全绿；普通 `git commit` 带 print 的代码被钩子拒绝。**15 项全部通过。**
  8. **演示**（验收第 9 条）：执行线在沙箱外 `vite build` 到临时目录，写了 `assets/…/demo.py`：`tests/diagnostics_demo.py` 挂演示接口；页面只调 `/api/health`，所以脚本按 `DEMO_HEALTH` 把它换成抛四类之一的路由，诊断内容照代表性故障示例写；生产代码里没有演示接口。`127.0.0.1:8600` 起五次（正常、输入、冲突、外部、缺陷），每次 `curl` 后用无头 Chrome 截图，SIGINT 停服务，退出码都是 0，stdout、stderr 都是 0 字节，8600 已释放。
     - `curl`（`demo-B-done-curl.txt`）：演示接口 input 400、conflict 409、external 502、defect 500、validation 两种 422，都是 `application/problem+json`，`error_id` 等于 `X-Request-ID`；缺陷响应里没有 traceback。
     - 运行日志（`demo-B-done-web.log`，偏移 −06:00）：每个错误请求只有一条 ERROR，带 `method`、路由模板 `path` 和 `request_id`；外部失败带"错误链："三行；意外的 `TypeError` 只有一份 traceback，保留了原始消息和源码行（D2）。
     - 截图 `demo-B-done-page-{ok,input,conflict,external,defect}.png`：五段卡片、实际与期望同一行、错误链折叠（3 层）、缺陷只显示一句话和编号加"完整报错"按钮。截图暴露的展示问题进了修复清单第 5 条。
     - 演示功能本身**通过**；r1 改了卡片以后重新截图。
  - **和 6.2 状态码表不一致的地方，报主会话，执行线没有改，也没让 Codex 改**：`/api` 下方法不对（例如 `POST /api/health`）返回的是 404 `{"detail":"Not Found"}`，不是表里写的框架 405。原因是第 3 张为 `/api/{path}` 登记了覆盖所有方法的兜底路由（`_unknown_api`），main 上就是这样，不是本票引入的。要么表里这一行改成"404（方法不对也是 404）"，要么另开一张票让兜底路由返回 405，请负责人定。
- 2026-10-24 13:55（+08:00），**修复清单（r1）**。Status 改成 `changes-requested`。
  1. 示例二的测试改成未包装的 `TypeError` 经真实应用冒到边界：断言 500、媒体类型、`category`、空诊断、`error_id` 等于 `X-Request-ID`、响应里没有 traceback；日志里只有一条 ERROR 和一份 traceback，带原始消息和源码行；去掉作业结果的断言并写明原因。（`tests/test_api_errors.py`）
  2. `getLogger(__package__)` 改成 `getLogger(__name__)`，放在 import 之后（6.4）。（`src/rdp/api/errors.py`）
  3. 删掉过期的"派工 B""在 B 中"说法，只写现在的行为。（`errors.py` 的 `install_error_handlers`，`problems.ts`）
  4. 后端的状态码映射只留一份：`rdp.infra.diagnostics` 里一个公开的具名常量，注明以 6.2 为准，三处都从它取；前端那份保留，注明对应 6.2。（新增一个公开常量，不改任何函数的含义，执行线批准）
  5. 卡片标题显示类别中文名；所有 problem 卡片显示"错误编号：…"；第五段标签统一成"检查："，和日志、示例一致。（`DiagnosticCard.tsx`；TSDoc 里的展示细节，执行线批准，汇报时告诉负责人）
  6. `test_handler_mappings_and_media` 补上 404、422 子类经真实应用返回的用例。
  7. 422 的运行日志追加各字段的诊断（只有字段位置，没有原值），并补测试。
- 2026-10-24 13:58（+08:00），派工 r1（续接，第 1 轮打回）。提示 `assets/…/prompt-r1.md`（修复轮模板，七条）；快照 `refs/rdp/m0-04/r1`（`6b3241c`，树和 `B-done` 相同）；会话 `01a16c0b-…`，先 `cd <工作目录>` 再续接，命令同派工 B，`-o assets/…/out-r1.md`。运行日志 `<执行线临时目录>/m0-04/ev-r1.jsonl`、`err-r1.txt`。Status 改回 `in-progress`。
- 2026-10-24 14:20（+08:00），派工 r1 交回，评审（3.5），逐项结论：
  1. **重跑**：运行本机时间 23:41–23:54（−06:00），退出码 0，最后一条 `turn.completed`，stderr 为空。运行日志里有一次 `Reconnecting... 1/5 (stream disconnected before completion: Upstream request failed)`，codex 自己重连后跑完，没有中断，不算网关故障。工作目录 `make check` 十一步全绿，12.8 秒；pytest `329 passed, 1 warning`，Vitest `55 passed`，没有跳过；跑前跑后 `git status` 相同。**通过。**
  2. **文件归属**：这一轮改了 9 个文件，都在 `src/`、`tests/` 下；受保护文件没动；主仓库目录干净（只有负责人的文件）。**通过。**
  3. **对比契约**：签名没变。新增公开常量 `ALLOWED_HTTP_STATUSES`（修复清单第 4 条，执行线批准）。docstring 改了措辞的有：`install_error_handlers`、`handle_error` 和 `ErrorBoundary.__call__` 里的 logger 名、`handle_error` 的 Side Effects（422 日志）、`DiagnosticCard` 的 `@returns`（展示细节，修复清单第 5 条）、`createProblemFetch` 的 `@timeSemantics`。都在修复清单范围内。**通过。**
  4. **先红后绿**：Codex 报告第 2、4、5、7 条的测试先红后绿，执行线在运行日志里核对一致。第 1、6 条只改测试，第一次运行就是绿的，因为它们验证的是已有行为。执行线把变异抽查扩到 15 个（`mutation_probe-r1-done.txt`），新加 3 个专门针对这两条：示例二走意外异常路径时边界重新抛出、缺陷响应的 detail 带异常原文、输入类子类的状态码一律 400。**15 个全部被抓到。** **通过。**
  5. **运行日志**：60 条命令；没碰两个旧项目或 `/mnt`；没有安装和联网命令；`/tmp` 只有检查链自建自删的临时目录。**通过。**
  6. **两轴评审**：快照 `refs/rdp/m0-04/r1-done`（`80adc5b`），只看增量，原文在 `assets/…/code-review-r1-done.md`。第 1、2、4、5、6、7 条 done。第 3 条 partial：`tests/test_api_errors.py:753` 的 docstring 还留着"派工B"。另有两条判断：`problems.ts` 的 6.2 注释贴错了位置；7 个新测试的 docstring 不以"验证契约："开头。**不通过（只差注释）**，进 r2。
  7. **违规试验**：`violation_probe-r1-done.txt`，**15 项全部通过**。
  8. **演示**：在 r1-done 上重做，`demo-r1-done-{curl.txt,web.log}`、`demo-r1-done-page-{ok,input,conflict,external,defect}.png`。卡片标题现在显示"错误 · 输入或数据问题 · 读取数据集 · 来源：平台"，所有卡片都有"错误编号：…"，第五段叫"检查："。422 的日志列出了字段位置 `query.count`，没有原值；logger 名是 `rdp.api.errors`。服务退出码都是 0，8600 已释放，临时的 `dist/` 和状态目录已删。**通过。**
- 2026-10-24 14:22（+08:00），**修复清单（r2）**，只改注释和测试 docstring。Status 先改成 `changes-requested`，再改回 `in-progress`。
  1. `tests/test_api_errors.py:753` 的 docstring 去掉"派工B"；在本票改过的文件里再搜一遍，不留。
  2. `problems.ts` 的 6.2 注释挪到 `statusTable` 上方，`requestId` 正则另写一句注释。
  3. 本票新写的 7 个测试 docstring 统一以"验证契约："开头。
  - 派工 r2（续接，第 2 轮打回）。提示 `assets/…/prompt-r2.md`；快照 `refs/rdp/m0-04/r2`；命令同 r1，`-o assets/…/out-r2.md`，运行日志 `<执行线临时目录>/m0-04/ev-r2.jsonl`。
- 2026-10-24 14:40（+08:00），派工 r2 交回，评审（3.5）。运行本机时间 00:01–00:10（−06:00），退出码 0，`turn.completed`，stderr 为空，没有网关断开；8 条命令，没有碰旧项目或 `/mnt`，没有安装和联网命令。
  1. **重跑**：`make check` 十一步全绿，12.9 秒；pytest `329 passed`，Vitest `55 passed`，没有跳过；跑前跑后 `git status` 相同。**通过。**
  2. **文件归属**：这一轮只改了 `tests/test_api_errors.py`、`tests/test_diagnostics.py`、`src/web/src/api/problems.ts`；主仓库目录干净。**通过。**
  3. **对比契约**：r2 → r2-done 的增量只有注释和测试 docstring，没改代码。**通过。**
  4. **先红后绿**：本轮没改行为，不适用；r1-done 的 15 个变异仍然有效。
  5. **运行日志**：见上。**通过。**
  6. **评审**：增量很小，执行线逐行看过（快照 `refs/rdp/m0-04/r2-done`，`f56958d`）。三条都改了：`派工B` 已删，在本票 20 个文件里搜"派工""在 B 中"没有结果；6.2 注释已挪到 `statusTable` 上方，`requestId` 另有注释；7 个 docstring 都以"验证契约："开头（其中一处冒号后多了个空格，不影响）。**通过。**
  7. **违规试验**、8. **演示**：代码和 r1-done 一样，沿用 r1-done 的结论（15 项通过；截图 `demo-r1-done-*`）。
- 2026-10-24 14:42（+08:00），**实现提交**（执行线）。先核对工作目录的树和快照 `r2-done` 相同，再 `git add -A`，普通 `git commit`：`e9ac279 实现：诊断与报错框架`，经过钩子，十一步全绿；提交后工作目录干净。打回 2 轮（r1 七条，r2 三条注释）。Status 改成 `in-review`，交回主会话，等负责人说"合并"。
- 2026-10-24 14:45（+08:00），**完工汇报**（执行线起草，交主会话转负责人）。
  - **改了什么**：
    - **诊断对象**（`rdp.infra.diagnostics`）：十个字段，加上可选的错误链（D1）；渲染成日志用的多行文本；按"来源 + 规则"聚合，每组保留 10 条样例，总数完整。
    - **四类异常**：状态码只在一处定义（`ALLOWED_HTTP_STATUSES`），和 CODING_STANDARDS 6.2 的表一致。`rdp.api.errors` 的模块 docstring 抄了一份这张表。
    - **接口统一异常处理**：返回 `application/problem+json`，`error_id` 就是请求编号。参数校验失败每个字段一条诊断，不回显原值。意外异常只在最外层记一次完整 traceback，保留异常消息和源码行（D2），uvicorn 不再重复记。
    - **作业结果**：`rdp.jobs.outcome.calculate_outcome`。`rdp.jobs` 在 import-linter 里登记为领域层。
    - **前端**：诊断卡片（五段、类别、错误编号、错误链折叠，程序缺陷点开才看详情），`HealthPage` 的 `Alert` 权宜已换掉。
    - 演示路由只在 `tests/` 里，生产代码里没有。
  - **测试**：pytest 从 232 到 329，Vitest 从 19 到 55，都没有跳过。先红后绿逐个核对过；一开始就绿的测试用 15 个变异抽查，全部被抓到；违规试验 15 项通过（含工单规定的"`rdp.infra` import `rdp.jobs`"被拦住）；演示截图在 assets。
  - **风险**：
    - 只报告一次，靠的是在 Starlette 的错误中间件外面再包一层边界，并覆盖 `build_middleware_stack`。升级 FastAPI/Starlette 时要重跑那几个用真实 uvicorn 驱动的测试。
    - 流式响应中途失败时，uvicorn 可能另记一条不带 traceback 的协议日志。
    - 网页上"点开看完整报错"现在只提示"按编号在运行日志里查"，真正显示 traceback 要等第 5 张存表。组件已经留好了取详情的回调和 5 秒超时。
    - `ProblemResponse.error_id` 只接受 uuid4 hex。以后作业的错误编号用作业编号（E2），到时候复用这个模型要放宽格式。
    - 坏味道（没要求改）：四个异常基类的构造函数几乎一样，"是不是四类之一"的判断在 `errors.py` 里重复了几次；以后加子类多了，可以抽一个私有公共基类。
  - **要负责人知道的**：`/api` 下方法不对（例如 `POST /api/health`）返回 404，不是 6.2 表里写的框架 405。这是第 3 张的兜底路由造成的，main 上就是这样。要么改表，要么另开票，请负责人定。
  - **下一张**：负责人说"合并"以后由主会话合并（3.7），然后写使用手册"怎么看报错"和运维手册"按错误编号查日志"两节。下一张实现票按 spec 顺序是第 5 张「数据库与迁移」（E2 的报错表存储在那张做）。
