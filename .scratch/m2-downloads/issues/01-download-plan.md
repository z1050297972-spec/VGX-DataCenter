# 下载计划

Status: done

分级：骨架关卡。理由：新领域对象（下载请求、文件清单、下载计划）和对外部服务的数据契约（Hub API 的版本、清单、分页），后面三张票都建在它上面。

## 依据

- M2 spec 第 01 张；spec「负责人决定」第 1–5 条。
- 调研 `docs/research/hf-mirror下载机制.md`：§1.2–1.3（端点与 308）、§4（v3.0 布局与筛选语义）、§5.2 第 1–3 步、§5.3"代理与端点"、§5.4（只用标准库）、末尾"负责人决定（2026-10-28）"。
- ADR 0005、0006；`GLOSSARY.md`；`docs/standards/CODING_STANDARDS.md`。

## 目标

给定仓库类型、仓库编号、版本和筛选，得出一份可以直接交给下载作业的"下载计划"：固定到 commit 的文件清单（路径、大小、校验值）、按筛选留下的文件、待下总量、目标存储根能不能放下；镜像不生效、仓库不可用、gated 没 token 时给出明确的诊断。

## 范围

新建领域包（建议 `rdp.downloads`，名字在骨架里定），只用标准库（`urllib.request`、`json`、`fnmatch`、`hashlib`）：

- **端点探测**：对镜像发 `HEAD /` 和一个 API 请求；任一请求得到指向 `huggingface.co` 的 3xx，就判定"镜像不生效"。请求一律不跟随重定向、不走代理（显式用不带代理的 opener），带超时。
- **解析版本**：数据集和模型两种仓库类型；把分支或 tag 解析成 commit sha，读出 `gated`、`private`、`disabled`。gated 而没设 token：诊断"需要用户处理"。
- **token**：从状态目录里的 token 文件读（文件不存在 = 未设置）；只用于请求头，不出现在日志、诊断、异常文本、作业参数和计划里。
- **列清单**：按 commit 递归列文件树，跟随 `Link: rel="next"` 分页；每个文件记路径、大小、git blob sha1、LFS sha256（有的话）。
- **重试**：TLS/连接错误、429、5xx 有限次重试，带退避；次数和等待写成具名常量。
- **筛选**：包含/排除模式，语义同 `fnmatch.fnmatchcase`（调研 §4.3）；另给"不要视频""不要某几路相机"的便捷筛选，相机列表来自 `meta/info.json`（数据集预览需要先读它，读的方式在骨架里定）。
- **预览信息**：数据集读出 episode 数、帧数、FPS、`robot_type`、`codebase_version`、相机列表（来自 `meta/info.json`）。
- **暂存目录**：按 spec 第 2 条算出 `暂存/下载/<repo 类型>/<repo_id>@<commit 前 12 位>/`（`repo_id` 里的 `/` 怎么落成目录名，骨架里定，要防 `..` 和绝对路径）。
- **容量预检**：待下总量 = 筛选后总量 − 暂存目录里已经完整的文件（只比大小，不算哈希）；对照目标存储根剩余空间，留余量（具名常量，写明理由）。目标必须是可写存储根。

## 不做

- 真正下载、aria2、curl、作业类型登记（第 02 张）。
- 网页和接口（第 03 张）。
- 系统代理、VPN 状态检测（第 04 张）；本票只做"镜像是否生效"的探测函数，第 04 张复用。

## 允许改的受保护文件

无。

## 依赖申请

无（只用标准库）。需要新依赖时停下申请。

## 验收

- 测试不访问网络：HTTP 全部由可注入的传输替身给出，覆盖 308 到官方站、分页三页、429 后成功、重试用尽、gated 无 token、仓库 disabled、清单里 LFS 与非 LFS 文件。
- token 不泄漏：有一个测试断言 token 文本不出现在计划、诊断、异常信息和日志记录里。
- 筛选语义和 `fnmatch.fnmatchcase` 一致（区分大小写、`*` 匹配 `/`、以 `/` 结尾补 `*`）。
- 暂存目录名对恶意 `repo_id`（`..`、绝对路径、空段）报输入错误。
- 容量不够时诊断里写明需要多少、剩多少、在哪个存储根。
- `make check` 全绿。

## 待负责人确认（骨架关卡时一并问）

1. 演练用的测试存储根怎么登记：`/tmp` 下的目录不是挂载点，过不了"在线"检查。
2. 模型权重下完放哪：权重不进导航层（导航层只管数据集），建议放 `<可写存储根>/权重/<repo_id>@<commit 前 12 位>/`。

## Comments
- 2026-10-30，开票。负责人 2026-10-30 在执行线会话里说"请你开工，可以调用gpt 6.1 terra high，他负责执行你负责监督。各管各的，但是最后要合并到一起，我不想多开分支"。M2 全部票共用分支 `t/m2-downloads`、工作目录 `~/桌面/robot-data-platform.wt/m2-downloads`（从 main `f09feba` 开）。基线 `make check` 全绿，113 秒，输出 `~/.cache/rdp-dispatch/m2-01/baseline-check.txt`。
- 2026-10-30，派工 A。模型 `gpt-6.1-terra` high，会话 `01a18c09-130f-7602-a90f-fb2fac86d3de`，快照 `refs/rdp/m2-01/A`，提示 `assets/01-download-plan/prompt-A.md`，运行日志 `~/.cache/rdp-dispatch/m2-01/ev-A.jsonl`、`err-A.txt`，setsid 派出（PID 817275）。
- 2026-10-30，派工 A 交回（03:07，约 8 分钟）。`out-A.md` 在 assets。执行线的等待脚本写错（pgrep 匹配到自身），到 03:40 才开始评审。
- 2026-10-30，骨架关卡评审。重跑 `make check` 全绿（2483 passed、23 skipped），输出 `~/.cache/rdp-dispatch/m2-01/review-A-check.txt`。文件归属：只新增 `src/rdp/jobs/downloads/{__init__,plan}.py`、`tests/jobs/downloads/test_plan.py`；主仓库 `src tests` 无改动。运行日志：旧项目路径只出现在 Codex 读 AGENTS.md 的原文里；无安装、联网命令；无 `/mnt` 命令。23 个跳过的测试覆盖验收全部条目。快照 `refs/rdp/m2-01/A-done`。结论：建议通过，附三条待负责人定：(1) 每个请求加总时长上限 30 秒、响应体上限 16 MB（CODING_STANDARDS / 7.1"所有等待都有上限"）；(2) 演练存储根用 `/tmp` 下 200 MB ext4 镜像经 `udisksctl loop-setup` 挂载，带 UUID，代码和 ADR 不改；(3) 权重落点 `<可写存储根>/权重/<命名空间>/<仓库>@<commit 前 12 位>/`。已交负责人。
- 2026-10-30，负责人："你把功能搭建好吧，我自己做下载测试，我之后会创建一个单独放权重的目录，让用户自己填位置"。执行线理解为：骨架通过；后续票的骨架关卡预授权（3.0 第 3 条，合并仍等负责人）；(1) 总时长与响应体上限按建议；(2) 不做演练存储根，负责人自己测；(3) 权重落点改为用户选可写存储根 + 填子目录，默认 `<命名空间>/<仓库>@<commit 前 12 位>`。契约提交 `95c3014`（`契约：下载计划`）。
- 2026-10-30，派工 B（含上述三处契约修改，执行线按负责人决定批准）。续接会话 `01a18c09-130f-7602-a90f-fb2fac86d3de`，快照 `refs/rdp/m2-01/B`，提示 `assets/01-download-plan/prompt-B.md`，日志 `~/.cache/rdp-dispatch/m2-01/ev-B.jsonl`，PID 2015629。
- 2026-10-30，派工 B 交回（05:44，约 10 分钟），只完成 6/23 个测试就以"预计超 80 分钟"交检查点（误读提示）。执行线前两次以为 Codex 已退出是等待脚本记错 PID（setsid 再 fork），重试因会话被原进程占用而失败，无副作用，重试文件已删。
- 2026-10-30，派工 B2（续接，不计打回轮）：要求做完剩余 19 个测试；定 `target_subdir` 允许中文和空格（与 repo_id 分开校验）；总时长和响应体上限必须有运行时保障。提示 `assets/01-download-plan/prompt-B2.md`，日志 `~/.cache/rdp-dispatch/m2-01/ev-B2.jsonl`，PID 2151743。
- 2026-10-30，派工 B2 中断：运行约 70 分钟，日志停在 06:54，没有 `turn.completed`；07:28 机器重启，执行线会话也断了。工作区改动都在（新增 `_http_child.py`：HTTP 放子进程里做，用来保证总时长上限）。
- 2026-10-30 19:28，派工 B3（网关断开后的续接，不计打回轮）。快照 `refs/rdp/m2-01/B3`，提示 `assets/01-download-plan/prompt-B3.md`，日志 `~/.cache/rdp-dispatch/m2-01/ev-B3.jsonl`，PID 627341。
- 2026-10-30 19:32，派工 B3 交回：23+ 个测试全部去掉跳过，Codex 自报 `make check` 全绿（2527 passed）。快照 `refs/rdp/m2-01/B-done`。
- 2026-10-30，评审（3.5）：
  1. 重跑：执行线的 `make check` 和变异抽查同时跑了，结果不可信，修复轮后重跑。
  2. 文件归属：只有 `src/rdp/jobs/downloads/{plan,_http_child}.py`、`tests/jobs/downloads/test_plan.py`；主仓库非规划文件无改动。通过。
  3. 对比契约：相对 `95c3014` 的改动只有负责人批准的三处（总时长与响应体上限、`target_subdir`、权重默认路径去掉 `权重/`）。Codex 申请给 `UrllibTransport.request` 的 Side Effects 补"隔离子进程"一句：措辞补充，执行线批准（6.2）。通过。
  4. 变异抽查：`assets/01-download-plan/mutation_probe.py`，结果 `mutation_probe-B-done.txt`。20 个变异抓住 16 个，1 个因匹配两处跳过。漏网 4 个：包含模式"以 `/` 结尾补 `*`"、容量余量（阻塞，进修复清单）；`_request` 的主机校验、父进程响应体上限（等价：另一层有校验并有测试，不打回）。
  5. 运行日志：B、B2、B3 均无旧项目路径、安装或联网命令、`/mnt` 命令，也没有对镜像或官方站的请求。通过。
  6. 两轴评审：执行线人工通读实现（HTTP 子进程、token 读取、重试、分页、预览、筛选、路径校验、容量）。没有硬性违规。遗留：`meta/info.json` 经镜像 `resolve` 时如果被 302 到镜像 CDN，会按"不可用"失败（info.json 是 git 小文件，预计是 200 直出），等负责人实测确认。
  7. 违规试验：检查链没改，不做。
- 2026-10-30，修复轮 r1（第 1 轮打回）：补"斜杠补星"和"容量余量"两个测试，加上批准的 docstring 补充。快照 `refs/rdp/m2-01/r1`，提示 `assets/01-download-plan/prompt-r1.md`，PID 1097896。
- 2026-10-30 19:44，r1 交回。变异抽查复跑（`mutation_probe-r1-done.txt`）：只剩两个等价变异漏网。日志无违规。快照 `refs/rdp/m2-01/r1-done`。实现提交 `0e9d39d`（`实现：下载计划`），钩子跑全量 `make check` 全绿（132 秒）。第 01 张完成，等 M2 整体合并。
- 2026-10-30，在分支上合并 main（`2cf390d`，M1、M1.5 全部）：没有冲突。提交合并时钩子连续三次被 M1/M1.5 的页面 Vitest 超时挂掉（JsonViewer、DataOrigin、FieldEditing、FileViewer、Repoint），单独跑能过，当时 load 8–18，M1 线的 Codex 正在跑 pytest。已按约定通知 M1 线（datasets-f5），对方确认是已知的不稳定用例，会开票处理。后台循环等到 load < 4 再提交合并。
- 2026-11-01，负责人在执行线会话里说"合并"。分支先合入 main 最新改动（`9683de1`：解决 13 个冲突；迁移按和 M1 线的约定改号，0013_download_adjustments → 0014，链是 0013_login_wait_attempts → 0014 → 0015 → 0016；M2 的 6 个作业类型按 M0 第 13 张 D2 声明提交角色；按 main 新增的 ESLint 规则改了监控页的 SVG），钩子全绿；再按 3.7 合进 main：`b4d7997`（`合并：M2 开源下载……`），钩子全绿（2757 passed / Vitest 380）。工作目录、分支 `t/m2-downloads`、快照 `refs/rdp/m2-*` 已删除。
