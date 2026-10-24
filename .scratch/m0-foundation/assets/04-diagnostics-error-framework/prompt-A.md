你在工单「诊断与报错框架」的工作目录 /home/shawn/桌面/robot-data-platform.wt/m0-04-diagnostics-error-framework（git worktree，分支 t/m0-04-diagnostics-error-framework）里写契约骨架。

先读下面这些。规划文件一律用绝对路径读主仓库目录 /home/shawn/桌面/robot-data-platform 里的版本：工作目录里的副本停在开分支的那一刻，可能已经过期，也可能缺少还没提交的文件（比如工单的 Comments）。
- /home/shawn/桌面/robot-data-platform/AGENTS.md
- /home/shawn/桌面/robot-data-platform/docs/standards/CODING_STANDARDS.md（尤其第 3 条（含 3.5 TSDoc）、第 6 条全部、第 7 条、9.x 的表、10.5）
- 工单 /home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/issues/04-diagnostics-error-framework.md（「范围」「验收」「风险」「允许改的受保护文件」，以及 Comments 里负责人批准的 E1–E3 和执行线开票时记的框架事实）
- 它引用的：/home/shawn/桌面/robot-data-platform/.scratch/platform-v1/issues/09-observability.md 的 Answer（诊断、报错分类、只报告一次、作业结果、工具的上报）；/home/shawn/桌面/robot-data-platform/.scratch/platform-v1/assets/09-observability/代表性故障示例.md（本票的测试以它为准）；/home/shawn/桌面/robot-data-platform/docs/adr/0004-工具与平台统一诊断上报.md；/home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/spec.md 第 04 张那一行
- /home/shawn/桌面/robot-data-platform/GLOSSARY.md 里「诊断与作业结果」一节的术语（诊断、警告、条目、作业结果、上报协议、作业状态）
- 工作目录里已有的代码：`src/rdp/api/__init__.py`（`create_app`、`RequestIdMiddleware`、`_RequestContextApp`，第 3 张）、`src/rdp/infra/logging.py`（`RuntimeFormatter` 的明细行缩进写法、`request_id_context`、`log_context`）、`src/web/src/HealthPage.tsx`（第 2 张的 `Alert` 权宜）、`src/web/src/api/`（OpenAPI 生成的类型）、`Makefile`（`make api-types`）、`pyproject.toml` 的 `[tool.importlinter]`

用 $enterprise-coding。这一步只交契约骨架：
1. 签名、类型和完整契约文档写全：Python 是六项 docstring（AGENTS.md 规则 4，CODING_STANDARDS 第 3 条），函数体只写 `raise NotImplementedError`；pydantic 模型、dataclass、枚举写 `Attributes:`，每个字段写含义、单位、取值范围、默认值。TypeScript 是 TSDoc（CODING_STANDARDS 3.5），函数体只写 `throw new Error("未实现")`。
2. 测试清单写成跳过的测试：pytest 用 `pytest.skip`，测试的 docstring 写明它验证哪条契约行为；Vitest 用 `it.skip`，标题写明它验证哪条契约行为。对着每个函数 docstring 里的每条 `Raises:`、每种返回情况、每项副作用，逐条都有测试（CODING_STANDARDS 7.1），并覆盖工单「验收」第 1–7 条。
3. `make check` 跑到全绿（十一步）。骨架阶段的接口行为不变，所以 OpenAPI 生成文件这一步不该变；如果你的骨架改了 OpenAPI（例如登记了错误响应的模型），用 `make api-types` 重新生成，不要手改生成文件。

本次交付（模块路径按工单）：
- **`rdp.infra.diagnostics`**（基础层）：
  - 诊断对象，不可变。字段按工单：级别（错误、警告）、类别（输入或数据问题、冲突、外部失败、程序缺陷）、阶段、来源（"平台"或工具名）、对象（有序的键值对）、规则、实际、期望、后果、下一步。哪些字段可空、空串算不算合法、对象的值是什么类型（只收字符串，还是也收数字），在契约里定下来。级别、类别用枚举；枚举成员的英文名、JSON 里的取值、中文显示名各是什么，写进 `Attributes:`。
  - 渲染成运行日志的多行文本：首行一句话摘要，五段作为明细行（对照代表性故障示例里的"规则：/实际：/后果：/检查："写法；第 3 张 `RuntimeFormatter` 会给首行以后的每一行加 4 格缩进，所以这里只产出不带缩进的多行消息，不要重复缩进）。摘要里有哪些东西、对象的键值对怎么写、实际和期望怎么写在同一行，定下来。
  - 渲染成 JSON（接口和作业记录用），字段名固定。用 pydantic 模型（已是直接依赖）还是 dataclass 加转换函数，由你定；要求是接口能把它放进 OpenAPI，前端的类型由 `make api-types` 生成，不手写。
  - 聚合：同一类（同一来源、同一规则）只保留前 N 条样例，总数始终完整。N 是具名常量，值 10（E1），注释写含义和出处。聚合的输入输出、各组的顺序、是否按级别分开计数，定下来。不同类的不互相挤占（验收 4）。
  - 四类异常基类（同一模块）：各带一条或多条诊断（程序缺陷带不带诊断，由你定并说明）；平台以后所有自定义异常都从这四个之一派生（6.2）。HTTP 状态码映射：输入或数据问题 400、404、422（由子类定，基类默认值你定），冲突 409，外部失败 502，程序缺陷 500。基础层不能 import fastapi、starlette、uvicorn，状态码用标准库 `http.HTTPStatus`。
- **`rdp.api` 的统一异常处理**（放在 `rdp.api` 下的一个新模块，或者 `__init__.py`，由你定；在 `create_app` 里接上）：
  - 四类异常转成 RFC 9457 `application/problem+json`（E3）：`type`、`title`、`status`、`detail`，加三个扩展字段：类别、诊断列表、错误编号。扩展字段的 JSON 名、`type` 取什么值（`about:blank` 还是平台自己的 URI），定下来。
  - FastAPI 的参数校验失败（`RequestValidationError`）也转成 422 的"输入或数据问题"，每个出错的字段一条诊断。诊断的"实际"要不要回显请求里的原值：想一想第 6 张的登录接口会收口令（CODING_STANDARDS 6.10），定下来并说明。
  - 其他意外异常算程序缺陷：响应里只有一句话和错误编号，没有 traceback；完整的异常链和 traceback 写进运行日志一次（ERROR，`rdp.api`，带请求编号）。错误编号就是这次请求的请求编号（E2，第 3 张的 `request_id_context`，响应头 `X-Request-ID`）。日志里的请求行写什么（方法、路径；查询串要不要写），定下来。
  - **只报告一次**（验收 3）：开票时查过，starlette 1.9.0 的 `ServerErrorMiddleware` 调用 `Exception` 处理器、发出 500 以后会 `raise exc` 重新抛出，异常会继续传到外层的 `RequestIdMiddleware` 和 uvicorn，uvicorn 会再记一次 traceback。你自己核对源码，在契约里写明用什么办法保证整个进程里只有一次完整 traceback（例如在哪一层截住、为什么不会漏掉流式响应中途的异常），并在测试清单里有对应的测试。
  - Starlette 自己的 `HTTPException`（路由不存在 404、方法不对 405 等）和 `/api` 下未知路径的 404（第 3 张的 `_unknown_api`）要不要也改成 problem+json，定下来并说明。
  - 错误响应的 schema 要出现在 OpenAPI 里，前端才能生成类型。怎么登记（每个路由的 `responses`、全局组件），定下来。
  - `create_app` 已获批的签名尽量不改。演示接口（验收 9）"只在测试配置里打开，生产配置里不存在"：第 3 张的配置文件不认识的项会拒绝启动（C1），所以不要加配置项；建议演示路由放在 `tests/` 下，由测试和执行线的演示脚本挂到 `create_app` 返回的应用上，生产代码里没有它。你另有更好的办法也可以，写进第 4 块。演示要能分别触发四类报错和一个参数校验失败。
- **`rdp.jobs.outcome`**（领域层的第一个模块，新建 `rdp.jobs` 包）：
  - 一个纯函数，输入是计数（总条目、失败条目、警告数，以及作业是否整体中止），输出四种作业结果之一：成功、带警告成功、部分成功、失败。规则照 09 的 Answer。作业结果用枚举，成员英文名照 `GLOSSARY.md`（Succeeded、Succeeded with Warnings、Partially Succeeded、Failed）。
  - 边界情况定下来并写进 `Raises:` 或 `Returns:`：负数、失败条目多于总条目、总条目为 0、整体中止但失败条目为 0、部分失败同时有警告。
  - 不 import 数据库、进程、`rdp.api`、`rdp.ops`。
- **import-linter**（本票允许改的受保护文件只有 `pyproject.toml` 的这一处）：在 `layers` 合约里把 `rdp.jobs` 登记成领域层（入口层 → 领域层 → 基础层），并把 `rdp.jobs` 加进"基础层不得依赖 Web 框架"那条 forbidden 合约的 `source_modules`（注释里已经留了位置），每条写理由。验收 7：`rdp.jobs` 不 import `rdp.api`、`rdp.ops`；`rdp.infra` 不 import `rdp.jobs`。
- **前端**（`src/web/src/` 下）：
  - 一个诊断卡片组件：输入或数据问题等带诊断的报错显示五段（对象、规则、实际与期望在同一行、后果、下一步），另显示级别、阶段、来源；程序缺陷只显示一句话和错误编号，点开才看完整报错（10.5）。props 的类型从生成的 OpenAPI 类型取，不手写结构。
  - 本票接口不返回 traceback（验收 2），traceback 存表在第 5 张（E2），所以本票里"点开看完整报错"能显示什么，由你提一个方案写进第 4 块（例如组件接收一个可选的取详情回调，本票显示"按编号在运行日志里查"），契约照方案写。
  - 把请求失败（`fetch` 抛出的 problem+json）转成组件输入的那一层（例如 `src/web/src/api/client.ts` 里），契约写清楚：响应不是 problem+json（例如网络断开、代理返回 HTML）时怎么显示。
  - `HealthPage` 去掉 `Alert` 权宜、改用新组件，这一步留给派工 B 做；骨架阶段只在测试清单里列出对应的跳过测试。
- **测试**：放在 `tests/` 下，每个模块一个测试文件；验收 1 的两个代表性故障各一个测试（断言对象身份、实际值、后果和最终的作业结果，不对整段文本做快照，6.11）。前端测试和组件放在一起（照第 2 张的写法）。

要特别注意的地方：
- 不需要新依赖。要是觉得需要，停下来写依赖申请。
- 诊断对象的字段在本票定下来以后，以后加字段要回到骨架关卡（工单「风险」）。所以请对着两处核一遍够不够用，结果写进第 4 块：① 09 的 Answer 里工具上报的"诊断"事件字段和"致命错误"事件（一句话加完整错误链）；② 代表性故障示例一的 ERROR 诊断带"错误链"三层，示例二的程序缺陷带错误链和 traceback——错误链是放在诊断对象里，还是只在异常和日志里，你的方案是什么。另外 M1 一致性面板（/home/shawn/桌面/robot-data-platform/.scratch/platform-v1/issues/11-dataset-contract.md 的「一致性面板（Q14）」）的问题分"需要处理"和"提示"两级，而工单的诊断级别只有错误、警告两级，看看是否够用，不够的话写进第 4 块，不要自己加级别。
- 日志、报错、接口响应里不写口令、令牌、cookie、私钥，也不把整份请求体写进日志（6.10）。
- 中间层不打日志；只在 `rdp.api` 的统一异常处理处记录一次（6.3）。
- 作业结果只能由那一个函数得出（6.8），模块注释写明。
- 不要写 `.git/info/exclude`（所有工作目录共用）。

边界：
- 只改 `src/`、`tests/`。本票允许改的受保护文件：`pyproject.toml`（只改 `[tool.importlinter]`：登记领域层 `rdp.jobs`，每条写理由；别的段不动，依赖表不动）。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。
- 不安装任何东西，不访问网络（沙箱为了跑测试开了网络权限，但这张票用不到网络；评审会查运行日志，出现安装或联网的命令整轮打回）。需要新依赖时停下，在最终回复里写依赖申请（AGENTS.md 规则 7）。
- 自己在 `/tmp` 或别处建的试验文件，交付前删掉。测试只用临时目录，不碰真实的 `~/.config/rdp`、`~/.local/share/rdp`。

最终回复分四块：
1. 改动清单：每个文件一行，写做了什么。
2. `make check`：最后一次运行的命令和末尾输出，原样贴出（pytest 那步要能看出 passed 和 skipped 的数目，Vitest 那步要能看出 skipped 的数目）。再原样贴出跑之前和跑之后的 `git status --porcelain --untracked-files=all`。
3. 契约变更申请、依赖申请：没有就写"无"。
4. 拿不准、需要评审决定的地方，包括上面要你"定下来"的每一处：你定的是什么、为什么。
