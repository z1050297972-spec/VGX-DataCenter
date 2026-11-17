# 09：长预览产生警告后切换阶段失败

Status: done

分级：已定位缺陷，直接回归修复。负责人要求“请修复，测试通过后 merge,update,push”，已授权本票通过验收后的提交、合并、升级和推送；不包含重跑真实数据任务。

## 真实证据

生产4235efa，作业1451（G2预览）运行242秒。工具退出0、输出预览JSON后，平台 `_tool_report -> _stage(context,4) -> ProgressReporter.report -> _validate_advance` 抛DefectError。30秒未解析到工具进度时产生提示性警告，旧进度 warning_count=1；_stage把它重置成0，违反累计计数不能倒退的契约。已有JSON被finally清理，报告未保存。

执行线已用该作业的只读进度快照，在内存调用实际_stage+实际_validate_advance，复现相同错误。只把新阶段warning_count恢复为旧值，其余相同即可通过。阶段3→4合法，其他两个累计计数均0→0。

## 修复范围

- `src/rdp/jobs/cleaning/job.py`：阶段切换保留 warning_count、failed_items、total_items 等累计事实；阶段局部done/total可重置。只有新报告真实计数更大时更新累计total_items，不把实际警告清零。
- 核对同文件 `_ReadingProgress` 是否有相同清零问题，必要时以同一条最小规则修复，保证MCAP和两类AgiBot路径不回退。
- 不修改通用ProgressReporter的单调约束，不吞DefectError、不靠重新跑工具绕过问题、不关闭30秒警告。
- 不改变报告JSON/工具CLI/业务质量规则，不修改依赖、生产配置、数据库或原始数据。

## 回归（必须先红后绿，秒级，不真等30秒）

1. 用真实ProgressReporter/ExecutionContext到清洗_stage调用边界：旧阶段3、done=1、total=None、warning_count=1，转4保持警告且成功；failed_items/total_items也不能倒退。先跑红记录输出。
2. 模拟真实外部工具预览生命周期：通过现有受管终端机制/假时钟产生无进度警告，工具成功返回合法报告，后续生成报告、成功事务保存均成功；不要仅测试没有真实累计校验的stub。
3. 无警告/首阶段行为不变；Alpha/G2以及MCAP相关回归不退化。
4. 需要时补读取进度的累计警告保留测试。

只做关键测试，不加罕见防御分支。Codex只改src/tests，不提交/不uv/不安装/不部署/不读真实数据。执行线独立复跑、评审、合并关卡全量检查、官方升级脚本并核对服务、push前fetch。失败升级不绕过权限或活跃任务检查。

## 评审与复验

- Codex先红：阶段切换3 failed、Alpha/G2真实上报器预览链路2 failed、读取进度2 failed；均在累计倒退校验抛DefectError。
- 修复仅16行生产代码改动，保留累计warning/failed/total_items，阶段局部进度仍重置；没有降低全局约束或关闭无进度警告。
- 执行线独立复测69 passed（含HTTP、进度契约、Alpha/G2预览）；对作业1451的只读快照回放实际_stage+实际_validate_advance，阶段3→4、warning1→1，PASS。
- 没有重跑生产任务、没有修改原始数据或生产数据库。提交及合并的全量检查由标准钩子执行，升级沿用正式脚本，不绕过活跃任务检查。

## Comments

- 2026-11-17，发布状态核对：实现 e16ca9e，合并 c2f9e1a；升级日志 m4.6-09/upgrade-confirmed.log 末尾 EXIT=0，部署版本核验一致。两远端 main 后续已推进到包含本票的 09e5bd6。 详细证据见 `docs/brief/0015-环境事实更新-工作区与双远端发布.md`。本轮只更新文档，不取消作业、不重试部署。
