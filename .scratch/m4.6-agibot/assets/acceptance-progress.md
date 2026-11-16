# 接入验收记录（进行中）

2026-11-15 负责人要求完成剩下任务。开发和验收继续；不合并 main、不部署、不推送、不做全量转换、不改生产导航层或生产配置。

## 已独立验证

- 第04张：执行线重跑 test_conversion_agibot / test_conversion_job / test_conversion_cleaning，27 passed（含HTTP）。
- 第05张：tsc 通过；cleaning/Pages、datasets/Conversion、tools/Pages 三组 Vitest，20 passed。
- 第03张发现真实契约错误：工具 task_id 为数字字符串，task 对未标注集为 null；修正后执行线用隔离解释器 (-I -B) 跑真实本地样本契约测试，2 passed。第一次用普通 pytest 启动因缺 -I 被测试防护拒绝，已按要求重跑。
- 03/04/05 工作区改动已汇入 m4.6-agibot，尚未提交。
- 工具登记包 tools/agibot2lerobot 已由执行线按当前工具配置和真实摘要生成；load_tool_registry 显示 agibot2lerobot、mcap2lerobot 均可用。
- G2工具预览单遍缓存修复已完成（默认4GiB，超限两遍且记录 passes）；preview --report-only 与精简结果事件已完成。执行线重跑完整工具测试，19 passed（包含官方转换函数的合成数据对照）。

## 尚未通过的检查

Alpha汇总 make check：3056 passed、2个可选真实样本测试 skipped、3 failed：
1. tests/test_agibot_preview_local_integration.py 包含实际工具挂载路径，违反常规tests禁止真实挂载访问的静态检查。已要求03将手动验收移到 scripts/drills，不修改审计规则或白名单。
2. OpenAPI快照过期的两个断言，统一接入完成后重新生成并复验。
没有宣称全量检查通过。

## G2真实小归档验收

- 输入 task_3405 的 389111_389369.tar.gz（约5GB），在bwrap中只读输入，只写本地系统盘验收目录。
- 目录 /home/shawn/.cache/rdp-dispatch/m4.6-07/real-accept-K2krID。
- preview已完成；convert失败 UnknownCodecError: libdav1d（AV1 decoder 名称被用于输出流构造）。真实编码不在原合成测试覆盖内。
- 前后 sda 写入扇区240不变、sdb 99704不变。
- 已只读复制第一个4MB视频到该目录 sample-av1.mp4供Codex复现；修复单元 rdp-m46-07e。
- 此次仅格式验收，未将未经人工清洗选择的产物入库；不连接真实平台。

## 当前后台任务及后续顺序

- rdp-m46-08：G2平台接入（新08票，在m4.6-08；含完整Alpha集成基础）。同时修复仅检查目录mtime的漏洞：新增保留输入文件元信息快照并在转换前验证；补启动器身份在预览核对中的缺口。
- rdp-m46-03c：移出手动本地测试；补Alpha真实工具、临时数据库/导航层下的端到端演练脚本。工作在m4.6-03，接回时只取相对上轮的增量，不能覆盖集成分支其他票。
- rdp-m46-07e：G2真实AV1无损重封装修复及回归。
- 上述单元日志均在 /home/shawn/.cache/rdp-dispatch/m4.6-0N/，已设后台等待任务完成后通知当前会话。
- 07修复后重跑小归档验收及平台四层检查、实际加载；更新G2登记指纹。
- 08回报后审核增量，将其改动与03演练脚本合入集成工作区；生成OpenAPI，跑全量检查和两条端到端验收；再补正式手册和总结。
- G2源码将因AV1修复变化，08登记摘要必须以最后一次复验时实际内容为准。

## 仍须明确的事实边界

- dataset-30不能照旧笔记填G1：所查2026样本为g2a，且目录内还包含仿真数据。
- 真实归档只抽样验证，不能把一个task_3405的格式/维度结论推广到404个归档。
- 所有报告必须区分Codex自述与执行线复跑；只有退出码0且相应产物检查通过才算验收通过。
