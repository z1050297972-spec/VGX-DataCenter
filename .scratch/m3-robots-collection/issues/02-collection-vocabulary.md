# 采集方式与用途词表

Status: done

分级：直做。和第 01 张同一分支、同一批会话做（共用迁移 `0019_collection_registry`）。按"只做关键测试"。

## 依据

- 「核心领域模型与术语」Q4 和细则 4：词表项可以新增、改名、停用；被引用过的不能删除；新建采集方式时要选对应的数据来源。
- M3 决定记录：场景归数据集（不在这里）；采集方式、用途的初始取值负责人选"按草案"。

## 契约

**数据库**（同一迁移）两张表 `collection_methods`、`collection_purposes`：

| 列 | 规则 |
|---|---|
| `id` | 整数主键，不改、不复用（`AUTOINCREMENT`） |
| `name` | 去首尾空白后 1–32 字符，同一张表内唯一 |
| `data_origin` | 只有采集方式有；取 `真机采集`、`UMI 采集`、`ego 采集`、`仿真生成` 之一（`rdp.jobs.navwrite.policy.DATA_ORIGINS` 去掉"开源下载""未知"；常量在 `rdp.collection` 里另写一份并用测试保证是 DATA_ORIGINS 的子集，因为 collection 不能依赖 jobs） |
| `status` | `active` / `retired` |
| 创建人、创建时间、最后修改人、最后修改时间 | 同第 01 张 |

**初始取值**（迁移写入，创建人记"系统"），按顺序：
- 采集方式：主从臂遥操作（真机采集）、VR 遥操作（真机采集）、UMI 手持（UMI 采集）、头戴相机（ego 采集）、仿真脚本（仿真生成）。
- 用途：训练、评测、演示、试采。

**引用**：被数据集的采集信息引用（第 03 张接上）。本张同第 01 张，引用数函数先恒返回 0。

**接口**（登录即可；写操作记操作日志，新增操作码 `create_collection_term`、`update_collection_term`、`retire_collection_term`、`restore_collection_term`、`delete_collection_term`，操作对象写明是哪个词表、编号和名称）：

- `GET /api/collection-vocabulary` → `{methods: Method[], purposes: Purpose[]}`，按 `id` 升序，含停用的。
- `POST /api/collection-vocabulary/methods`（`{name, data_origin}`）→ 201；`PUT .../methods/{id}`（同）；`POST .../methods/{id}/retire`、`/restore`；`DELETE .../methods/{id}` → 204，被引用 409。
- `purposes` 同上，输入只有 `{name}`。
- `Method`：`id`、`name`、`data_origin`、`status`、`reference_count`、创建/修改人和时间；`Purpose` 同，没有 `data_origin`。
- 改名不影响引用（第 03 张的导航层只存编号）。名称重复 409；不合法 422；不存在 404。

## 范围

1. **后端**：表、迁移（含初始取值）、领域函数、接口、操作码；测试。
2. **前端**：主菜单"机器人"后面加"采集词表"（`/collection-vocabulary`），分"采集方式""用途"两页：表格（编号、名称、对应数据来源〔仅采集方式〕、状态、被引用数）；新增、改名（采集方式可改对应来源）、停用/恢复、删除（被引用时不可用）。
3. **手册**：使用手册加"采集词表"一节（执行线写）。

## 验收

1. 关键测试：迁移后有 5 个采集方式、4 个用途，来源对应正确；新增、改名、停用、恢复、删除；采集方式的来源取"开源下载"被拒；名称重复 409。前端：新增一项后列表出现；被引用数 > 0 时删除不可用。
2. `make check` 全绿、0 skipped。

## Comments

- 2026-11-08 开票（执行线）。
- 2026-11-08 前后端交回（Codex gpt-6-astra medium），执行线 make api-types 后前端续接换成生成类型。make check 全绿：后端 2770 passed、Vitest 386 passed、0 skipped。临时实例实测：新建、MAC 规范化、MAC 重复 409、删除后编号不复用、初始词表、/robots 页面。负责人授权按顺序做完 M3，执行线合并。
