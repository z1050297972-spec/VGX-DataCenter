# 机器人登记

Status: in-progress

分级：直做。领域决定已在「核心领域模型与术语」（`.scratch/platform-v1/issues/13-domain-model.md`）和 `.scratch/m3-robots-collection/decisions.md` 定好。按"只做关键测试"。和第 02 张同一分支、同一批会话做（共用一个迁移）。

## 依据

- 原始需求（`docs/brief/0001` 第 (3) 条）："将两台机器人的信息存储到数据库中，包括他的名称、MAC码、类型、在局域网中的ip、端口等信息"。
- 「核心领域模型与术语」Q1、Q6 和四条细则；M3 决定记录："型号沿用 M1.5 决定，不建型号表"。
- ADR 0005：几秒内做完、只读写数据库的事 Web 当场做（登记机器人不走作业）。

## 契约

**领域包** `rdp.collection`（已在 import-linter 分层里登记在 `rdp.jobs` 之下、`rdp.accounts` 之上；已建空包）。机器人和第 02 张的词表都放这里。

**数据库**（迁移 `0019_collection_registry`，和第 02 张共用一个迁移）表 `robots`：

| 列 | 规则 |
|---|---|
| `robot_id` | 整数主键，平台分配，不改、不复用（SQLite `AUTOINCREMENT`） |
| `name` | 去首尾空白后 1–64 字符，唯一 |
| `robot_model` | 去首尾空白后 1–64 字符；和数据集 `数据集信息.json` 顶层 `robot_model` 是同一套字符串，不建型号表 |
| `serial_number` | 可空；非空时去首尾空白后 1–64 字符，非空值唯一 |
| `macs` | JSON 数组，0–8 项，每项 `{interface: 可空 1–32 字符, mac: "aa:bb:cc:dd:ee:ff"}`；接受 `-` 或 `:` 分隔、大小写不限，存小写冒号形式；同一 MAC 在全部机器人（含停用的）里唯一 |
| `address` | 可空；IPv4、IPv6 或主机名（RFC 1123，≤253 字符） |
| `ssh_port` | 1–65535，默认 22 |
| `ssh_user` | 可空；1–32 字符，不含空白 |
| `status` | `active` / `retired` |
| 创建人、创建时间、最后修改人、最后修改时间 | 照现有"历史身份"的存法（账号删除后显示"张三（已删除）"，见作业提交人） |

平台不存密码，表里没有任何凭据列。

**引用**：机器人"被引用"指被数据集的采集信息引用（第 03 张才有）。本张在领域层留一个查询引用数的函数，现在恒返回 0，第 03 张接上索引；接口和页面照常显示 `reference_count`。

**接口**（登录即可，成员和管理员都能做；每个写操作记一条操作日志，新增操作码 `create_robot`、`update_robot`、`retire_robot`、`restore_robot`、`delete_robot`，操作对象是机器人编号和名称）：

- `GET /api/robots` → `{items: Robot[]}`，按 `robot_id` 升序，含停用的。
- `GET /api/robots/model-options` → `{items: string[]}`：数据集索引里出现过的 `robot_model` 值并上已登记机器人的型号，去重、排序。页面型号输入用它做候选，也允许输入新值。
- `POST /api/robots`（`RobotInput`）→ 201 `Robot`。
- `PUT /api/robots/{robot_id}`（`RobotInput`）→ `Robot`。停用的也能改。
- `POST /api/robots/{robot_id}/retire`、`POST /api/robots/{robot_id}/restore` → `Robot`。
- `DELETE /api/robots/{robot_id}` → 204；`reference_count > 0` 时 409（提示改用停用）。
- `RobotInput`：`name`、`robot_model`、`serial_number`、`macs`、`address`、`ssh_port`（缺省 22）、`ssh_user`。
- `Robot`：`RobotInput` 的全部字段（规范化之后的值）＋ `robot_id`、`status`、`reference_count`、`created_by`、`created_at`、`updated_by`、`updated_at`。身份字段用现有 `HistoricalActorResponse`。
- 输入不合法 422（指明字段）；名称、序列号、MAC 重复 409（指明和哪台机器人重复）；编号不存在 404。

## 范围

1. **后端**：上面的表、迁移、领域函数、接口、操作码；测试。
2. **前端**：右上主菜单"数据集"后面加"机器人"（`/robots`）。页面：表格（编号、名称、型号、序列号、MAC、地址、SSH、状态、被引用数、最后修改）；"新建机器人"、每行"编辑""停用/恢复""删除"（被引用时删除按钮不可用，提示"已被数据集引用，只能停用"）。表单：型号用可输入的下拉（候选来自 `model-options`）；MAC 可增删多行（网卡名可选）；SSH 端口默认 22。停用的行灰显，默认也显示。
3. **手册**：使用手册加"登记机器人"一节（执行线写）。

## 验收

1. 关键测试：
   - 新建、修改、停用、恢复、删除各一次，返回值和操作日志正确；`robot_id` 删除后不复用。
   - MAC 规范化（`AA-BB-CC-DD-EE-FF` 存成 `aa:bb:cc:dd:ee:ff`）；名称、MAC 重复 409；端口 0 或 70000 被拒。
   - `model-options` 含索引里的 `robot_model` 和已登记型号，去重。
   - 前端：新建表单提交后列表出现新行；被引用数 > 0 时删除按钮不可用。
2. `make check` 全绿、0 skipped。

## Comments

- 2026-11-08 开票（执行线；负责人："请按照顺序依次完成这些任务，直至M3结束"）。
