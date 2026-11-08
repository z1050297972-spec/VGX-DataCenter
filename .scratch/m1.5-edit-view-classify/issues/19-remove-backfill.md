# 去掉"回填数据集信息"功能

Status: in-progress

分级：直做。负责人已当面决定（见下）。只删功能，不新增领域对象。按"只做关键测试"。

## 依据

负责人（2026-11-08）：

> 可以把回填数据集信息的东西删掉了把

第 15 张的上线回填已在真实导航层跑完（2026-11-06：fps 62 份、data_origin 70 份、来源.json 升版 35 份），之后 FPS 和数据来源都由负责人在编辑器里维护。回填本来就定为"只用这一次"。

## 范围

**去掉**：
1. 作业类型 `nav_information_backfill_preview` 及其构建、注册、参数（`jobs/navwrite/backfill.py`、`backfill_parameters.py`）、接口 `POST /api/navigation/backfill/preview`（`api/backfill.py`）、权限登记；对应测试删掉（`tests/test_information_backfill*.py`），写死作业类型数量的旧测试按新数量改。
2. 前端：`datasets/InformationBackfill.tsx`、`api/informationBackfill.ts`、数据中心工具栏的"回填数据集信息"入口；`Sizes.tsx` 说明里"例如回填、编辑字段之后"改成"例如编辑字段之后"。
3. 手册：使用手册"回填数据集信息（管理员）"一节和其他提到回填的句子；导航层手册、运维手册里提到回填的地方（运维手册"筛选字段升级"一段改成只讲迁移后重新扫描）。

**保留**：
- 已执行的迁移 `0018_information_filters` 及更早迁移的文件不改（只改注释也不要）。
- 扫描照旧读 `meta/info.json` 的 `robot_type`、`fps`，用于一致性面板的型号/FPS 比对提示（`_info_compare.py`）。`models.py` 里给比对用的字段保留，注释里"和回填"去掉即可。
- 读 `来源.json` 时对旧版的兼容（如果有）不动。
- 历史作业记录、操作日志、变更记录不动；作业列表里已有的回填作业照常能看。

## 验收

1. 关键测试：提交 `nav_information_backfill_preview` 返回"作业类型不存在"（或 422），`POST /api/navigation/backfill/preview` 不再存在；比对提示（INFO_ROBOT_MODEL_DIFFERS / INFO_FPS_DIFFERS）现有测试保持通过；工具栏没有"回填数据集信息"。
2. `make check` 全绿、0 skipped。

## Comments

- 2026-11-08 开票（执行线；负责人点名）。ADR 0006 已追加修订节。
