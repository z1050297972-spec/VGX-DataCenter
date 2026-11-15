# 前端：AgiBot 的预览入口、报告页和工具库展示

Status: blocked（依赖第 01 张的接口形状；执行线在第 01 张合并后生成好类型再派）

分级：直做。与第 03、04 张并行（只动 `src/web/`）。只用 antd。

## 要做的

1. **清洗预览入口**（`src/web/src/datasets/Conversion.tsx`）：现在只认 mcap。改成按工具的 `input_format` 匹配数据集里同格式的数据块：
   - 数据集有 `agibot_native` 数据块且存在 `input_format === "agibot_native"`、`preview_by_tool`、有清洗型号的工具时，同样显示入口。
   - `preview_by_tool` 的工具：数据块单选（文案"选择一个任务的观测目录"），选项显示路径末两级（如 `observations/327`）；mcap 仍是 1–200 个多选。
   - 型号初值：数据集的 `robot_model` 在工具清洗型号里就用它，否则第一个。
2. **报告页**（`src/web/src/cleaning/`）按 `report.source_format` 分支；`"mcap"` 的显示完全不变：
   - `agibot_native`：概览里"保留帧 / 基准帧"改成"可转帧数"；文件表改叫"Episode"，列为 episode ID、帧数、时长、大小、体检问题（`fatal_issues` 的 `actual`）、数值问题（标签）、处理（保留/剔除开关；有体检问题的固定剔除、不可改）；不显示话题对齐表、基准话题、对齐规则。
   - 「清洗流程」卡片（`Process.tsx`）和规则说明（`Rules.tsx`）：`agibot_native` 时写这套流程——①体检：视频、深度图、本体感知是否齐全，帧数是否一致，维度是否与配置相符，不过的集不能转；②数值检查：非有限值、整段静止（默认剔除），长时间静止、跳变、超限（只提示），阈值取 `report.rules.checks`；③人工确认保留/剔除；④转换只转保留的集，视频不重新编码；⑤转完核对每集帧数；⑥入库检查。不要写死阈值数字。
   - 「进行转换」（`Convert.tsx`）：`agibot_native` 只发 `excluded_files`（开关关掉的集的 `file_index`），`excluded_episodes` 发空数组；空间百分比初值取工具的 `default_space_ratio_percent`。
3. **工具库页**（`src/web/src/tools/Pages.tsx`）：工具详情显示"预览方式"（工具执行 / 平台解析）和默认空间百分比。不显示指纹（负责人此前要求不显示 SHA-256）。
4. **作业详情**：`agibot2lerobot-events` 的进度分项（逐集处理、数据分片、视频分片）用现有分项组件能正常显示即可，确认不需要改；需要改才改。

## 不做

后端；新依赖。

## 允许改的受保护文件

无。

## 测试范围（只做关键测试）

1. 有 `agibot_native` 数据块和对应工具时出现入口，数据块是单选；提交的参数正确。
2. `agibot_native` 报告：不渲染话题对齐表；有体检问题的集开关禁用且为剔除；关掉一个集后提交，请求体的 `excluded_files` 含它且 `excluded_episodes` 为空。
3. mcap 报告页现有测试照常通过。

## 验收

`make check` 前端部分全绿。

## Comments
