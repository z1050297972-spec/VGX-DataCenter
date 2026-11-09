# 清洗预览作业、报告存储与接口

Status: done（2026-11-09 08:0x 评审通过，合进集成分支 t/m4.5-cleaning）

分级：直做（在已有作业框架里加类型，契约在第 01 张）。依赖：第 01 张。决定见 `../decisions.md`。

## 背景

第 01 张给出了 `build_cleaning_report`。本票把它做成管理员提交的后台作业，报告存进数据库，并给前端两个接口。转换接入在第 03 张，页面在第 04 张。

## 要做的

### 1. 工具清单挂清洗规则

`tool.toml` 加可选的 `[cleaning]` 表：键是 `robot_model`，值是登记包内清洗规则文件的相对路径（与 `[models]` 同样的路径约束）。键必须都在 `[models]` 里。`tools/mcap2lerobot/tool.toml` 加 `"Galaxea R1 Lite" = "cleaning/r1lite.toml"`。工具列表和详情接口的工具摘要加 `cleaning_models`（有清洗规则的型号），工具库页面不用改（第 04 张一起改）。

### 2. 作业类型

- 每个有 `[cleaning]` 的有效清单生成一个预览类型，类型键由工具名派生（写法照 `conversion_type_name`，前缀自定，例如 `cleaning_preview_`），显示名"清洗预览：<工具名>"。只有管理员能提交；中断恢复方式 INTERRUPT；不要 GPU；不要可写存储根。
- 参数：`dataset_id`、`source_ids`（1–200 个、不重复，与转换一样）、`robot_model`（必须在该工具的 `[cleaning]` 里）。输入选择复用 `rdp.jobs.conversion.parameters.selected_inputs`（同一规范入口、格式 mcap）。
- 执行四个阶段：「核对工具」（重新加载登记，工具状态必须"可用"，记下程序 sha256）→「核对输入」（重读索引、路径必须在已登记存储根内、在线检查，写法照转换作业的 `_prepare_paths`，但不检查可写根和空间）→「读取文件」（调用第 01 张的入口，进度报已读字节/总字节和第几个文件，响应取消）→「生成报告」（写库）。
- 只读：不建暂存目录、不写导航层、不写任何存储根。

### 3. 报告存库

新表（迁移 0022）：作业编号（主键，外键到作业表）、数据集编号、工具名、型号、程序 sha256、工具配置 sha256、清洗规则 sha256、报告 JSON、生成时刻（UTC）。作业成功时在同一事务里写入；失败、取消、中断不写。报告 JSON 用第 01 张的模型序列化，读出时用同一模型校验（版本不认识按缺陷处理）。

### 4. 接口

- `POST /api/jobs/cleaning-preview/{tool_name}`（`operation_id = submit_cleaning_preview_job`）：参数如上，返回新作业（201），写法照 `submit_conversion_job`。
- `GET /api/cleaning-previews/{job_id}`（`operation_id = get_cleaning_preview`）：返回 `{job_id, dataset_id, tool_name, robot_model, binary_sha256, config_sha256, rules_sha256, created_at, report}`；没有这条（作业不存在、未完成或不是预览作业）返回 404。所有登录用户可看。
- 两个接口的响应模型进 OpenAPI，执行线跑 `make api-types` 生成前端类型（实现者不要跑）。

## 不做

- "进行转换"接口和转换作业的改动（第 03 张）；页面（第 04 张）。
- 报告的历史清理（报告随作业保留，以后看量再定，记 followups）。

## 允许改的受保护文件

无（迁移文件是新增）。

## 测试范围（只做关键测试）

在测试里用假存储根（临时目录）放第 01 张那样造的小 MCAP，登记成只读根并在索引里造一个 mcap 数据集。

1. 管理员提交 → worker 执行成功 → 库里有报告 → `GET` 返回的汇总与报告一致。
2. 成员提交返回 403；成员能 `GET`。
3. 型号没有清洗规则 → 提交 422。
4. 输入所在存储根离线 → 作业失败、诊断来自存储检查，库里没有报告。
5. 读文件途中取消 → 作业取消，库里没有报告。
6. 现有测试里的迁移版本、作业类型数量、权限列表按新增同步更新（只改期望值）。

## 验收

1. 测试通过；`make check` 全绿、0 skipped（OpenAPI 快照由执行线更新）。
2. 执行线在副本环境（测试配置、临时状态目录，输入指向 M5 真实样本副本所在目录登记成的只读根）起 web 和 worker，用接口提交一次预览并取回报告；两块数据盘写入扇区不变。

## Comments

- 2026-11-09 06:5x 派工 Codex（gpt-6-astra high，单元 rdp-m45-02，日志 `~/.cache/rdp-dispatch/m4.5-02/`），约 70 分钟交付：`rdp/jobs/cleaning/{job,parameters,records,registration}.py`、`rdp/api/cleaning_previews.py`、迁移 `v0022_cleaning_previews.py`；`ExecutionContext.save_on_success`（报告与成功终态同一事务）；`InputSelection` 抽出供转换和预览共用；工具清单 `[cleaning]`。作业类型键 `cleaning_preview_mcap2lerobot`。
- 执行线补：`tools/mcap2lerobot/tool.toml` 加 `[cleaning]`（Codex 按 AGENTS 规则 3 不改 `tools/`）；注释不能含字面 `[models]`（测试辅助按字符串替换它）。
- 评审追加 1 处（第 04 张需要）：报告加 `rules`（`sync` 和 `checks`，`severe_checks` 与判严重共用 `_checks.SEVERE_CHECKS`）。resume 时沙箱没开本地通信，5 个接口测试由执行线跑。
- `make api-types` 后两个旧前端测试的工具假数据缺 `cleaning_models`，执行线只补了这两处假数据。
- 变异抽查：成员可提交被抓；"不论成败都写报告"没被抓——现有取消测试在读文件途中取消，那时还没登记写入，终态前一刻被取消的窄窗口没有测试覆盖。后果只是保存一份完整报告，不打回，记在这里。
- 检查：`make check` 全绿，后端 2898、前端 414，0 skipped。
- 验收 2（副本环境起 web/worker 提交预览）并入第 05 张的端到端演练，同一环境一起做。

