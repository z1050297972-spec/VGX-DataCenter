# RobotProfile 转正：读取与校验

Status: in-progress

分级：直做。内容和取舍在 ADR 0007 和两份草样里已经定了，本票只把它落成文件和代码；字段细节在评审时对照 0007、0008 核对。负责人 2026-11-09："可否派出若干agent协作执行？不要对机器人做任何操作"。合并前要负责人说"合并"。

## 依据

- ADR 0007（`docs/adr/0007-RobotProfile按型号共用且只写事实.md`）：按型号一份 TOML，只写事实，带版本号，放平台仓库，修改走评审。
- 草样：`.scratch/platform-v1/assets/14-robot-profile/r1lite.toml`、`autolife.toml`。
- 事实：`docs/brief/0007-环境事实更新-机器人.md`、`docs/brief/0008-环境事实更新-机器人补测.md`（R1 Lite 话题清单、QoS、就绪条件；AutoLife 话题）。
- M5 地图：`.scratch/m5-live-preview/map.md` 的 D7。

## 要做的

1. **两份 Profile 文件**：平台仓库根目录 `profiles/r1lite.toml`、`profiles/autolife.toml`，从草样转正：
   - 草样里"略"的部分写全：R1 Lite 的右臂、右夹爪，以及 0007/0008 话题清单里有的躯干、底盘关节组和其余相机（头部右路）；话题名、类型、频率逐条照抄 0007/0008，不凭印象补。
   - `model` 用和机器人登记、数据集 `robot_model` 同一套字符串（例如 `Galaxea R1 Lite`），以现有 `tools/mcap2lerobot/tool.toml` 和机器人登记里的写法为准。
   - **还不知道的事实**（草样里写"待补测"的）一律省略对应的键，不写占位字符串；关节名未知时写 `joint_count`。文件里用注释写明"待补测，见规划票 18"。
2. **读取与校验**（领域层，例如 `rdp.robots.profile` 或放进现有 `rdp.collection`，按 import-linter 的分层选）：
   - pydantic 严格模型，`extra="forbid"`，覆盖 ADR 0007 列的全部字段：身份（`profile`、`version`、`model`、`robot_type_labels`）、ROS 图（distro、rmw、发现方式、QoS）、就绪条件（`check`、`value`、`reason`）、关节组（名字、关节名或个数、单位、观测来源、目标来源或"无目标"）、相机（名字、话题、编码、分辨率、标称帧率、时间戳来源与是否可信）。
   - 来源 = 话题 + 取法（`JointState.position` 或 JSON 路径）+ 标称频率 + 时间戳来源 + 是否可信 + `may_be_silent`。
   - 校验：同一份里关节组名、相机名不重复；关节名和 `joint_count` 二选一；有关节名时，观测和目标的取法要能给出同样个数（能静态判断的才判）；`model` 在 `profiles/` 下唯一。
   - 平台启动时读一次 `profiles/`（路径和 `tools/` 一样从部署目录取），坏文件让启动失败并给出完整诊断（文件、键路径、规则、实际与期望），不静默跳过。
   - 提供"按型号找 Profile"的函数；找不到返回 None，不报错（型号可以没有 Profile）。
3. **只读接口**：`GET /api/robot-profiles`（列表：profile、version、model、未知项个数）和 `GET /api/robot-profiles/{profile}`（全文，结构化 JSON）。所有登录账号可读。重新生成 OpenAPI 和前端类型。本票不改前端页面。

不做：
- 前端展示（02 或 04 再做）；
- 和工具配置核对（M4 README 写了"暂不做"）；
- 单台机器人覆盖 Profile（ADR 0007：v1 不支持）。

## 允许改的受保护文件

无。`profiles/` 是新目录，不属于受保护文件。如果部署、升级脚本要把 `profiles/` 带进部署目录而必须改 `scripts/`，停下来写申请。

## 验收

1. 两份文件都能读进来，接口返回的 R1 Lite 关节组至少有左右臂、左右夹爪，每组有观测和目标；AutoLife 的未知项个数大于 0。
2. 坏文件（多一个未知键、关节名和个数同时缺）让读取失败，诊断写出文件名和键路径。
3. 按型号找：`Galaxea R1 Lite` 找到 r1lite；不存在的型号返回 None。
4. 最后一次 `make check` 全绿、0 skipped。

## Comments

- 2026-11-09 开票（执行线），M5 第一批，与 02 并行。
- 2026-11-09 01:51 派工（执行线）：工作目录 `robot-data-platform.wt/m5-01-*`，Codex gpt-6-astra high，systemd 单元 `rdp-m5-01`，日志 `~/.cache/rdp-dispatch/m5-01/`。同时并行：另一张实现票和一份联网调研（Lichtblick 自托管、机器人侧组件，`~/.cache/rdp-dispatch/m5-research/`）。
