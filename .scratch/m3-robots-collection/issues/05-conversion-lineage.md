# 登记转换关系（人工血缘）

Status: ready-for-agent

分级：直做。按"只做关键测试"。写导航层，要做副本演练。

Blocked by: 03（顺序上排在 04 之后，和 04 不改同一处时可并行）

## 依据

- 负责人（2026-11-08）问答 3 选"要，写进来源.json"；决定记录："转换产物用血缘连回去……M3 只做人工登记这一条关系；转换作业自动写血缘留到 M4"。
- ADR 0008：血缘写在按任务入口的 `来源.json`，第 2 版只存 `dataset_id`、`dataset_name`、`collection_task_id` 和血缘记录。

## 契约

- **记录格式**：直接用现有 `rdp.jobs.navwrite.provenance.LineageRecord`，不改模型（2026-11-08 和 M4 会话 datasets-d5 对齐，M4 的转换作业写同一个模型）。人工记录的取值：
  - `kind: "转换"`、`status: "来历部分未知"`、`recorded_by.kind: "人工补录"`（带提交人 `account_id`、`account_name`、UTC `at`）。
  - `inputs`：每个输入数据集一项 `{"dataset_id": "dataset-29"}`，**不带 `source_id` 键**（人工登记只到数据集一级）；1–8 个已存在的 `dataset_id`，不能含自己。
  - `outputs: []`；`tool`、`config`、`robot_profile`、`parameters`、`started_at`、`finished_at` 为 `null`；`note` 是用户填的说明（0–500 字符，空写 `null`）；`job_id` 是写入作业编号；`record_id` 照 `append_lineage` 的规则（现有最大编号加 1）。
  - **能删的判定**：`recorded_by.kind == "人工补录"` 的记录能删；其他记录（worker、平台自动写的转换、下载、采集记录）一律只追加。
- **作业**：`nav_lineage_preview`，参数 `{dataset_id, action: "add" | "remove", input_dataset_ids?, note?, record_id?}`：
  - `add` 追加一条人工记录；`remove` 按 `record_id` 删一条，只能删人工补录的记录，其他记录删除返回 422（ADR 0008 只追加规则对它们不变；人工记录可删，ADR 修订已由执行线写）。
  - 走预览 → 确认（`nav_write_apply`）；权限同字段编辑；只改 `来源.json`，其余文件不动，其他键值和顺序不变。
- **索引与显示**：扫描把**所有**血缘记录的 `inputs[].dataset_id` 投影进索引（新迁移），不只认人工记录，这样 M4 工具写的记录不用再改投影和详情页。详情页加"转换关系"一块：上游"由 X 转换"（名称可点，带说明），下游"转换出 Y"（从别的数据集的记录反查）；每条人工记录有"删除"，块里有"登记转换来源"按钮（选数据集，可多选，加说明）。
- `collection_task_id`：采集任务就是数据集本身，这个键不再写有意义的值；读时忽略，写时保持原样（不新增、不删除）。

## 范围

1. **后端**：作业、接口 `POST /api/navigation/lineage/preview`、索引投影、详情接口返回上下游；测试。
2. **前端**：详情页"转换关系"块、登记与删除（预览 → 确认）。
3. **手册**：导航层手册讲人工血缘记录；使用手册"登记转换关系"（执行线写）。

## 验收

1. 关键测试：给 R1_lite_table_withdrawing_lerobot 登记"由 R1_lite_table_withdrawing_mcap 转换"：只改它的 `来源.json`，追加一条记录；扫描后两边详情分别显示上游、下游；删除这条人工记录后还原；非人工补录的记录（夹具里放一条 `recorded_by.kind: "worker"` 的转换记录）删除被拒，且它的输入同样出现在上下游里；输入含自己或不存在的编号 422。
2. **副本演练**（执行线）：在导航层副本上登记一次、删除一次；两块数据盘写入扇区不变。
3. `make check` 全绿、0 skipped。

## Comments

- 2026-11-08 开票（执行线）。
- 2026-11-08 与 M4 会话（datasets-d5）对齐：记录格式改用现有 `LineageRecord`；投影按所有记录的 `inputs[].dataset_id`。
