# M4.6 验收结果（完成）

## 执行线独立运行的结果

| 验证 | 结果 | 证据 |
|---|---|---|
| G2 工具全套测试 | 29 passed；含官方转换函数对照、AV1/PNG无损包、剔集、统计补算和实际深度加载口径 | `~/.cache/rdp-dispatch/m4.6-07/`，本会话工具输出 |
| G2 真实 task_3405 单归档转换 | 退出0；13集、30,681帧；预览单遍；视频自检全部实际解码 | `~/.cache/rdp-dispatch/m4.6-07/real-accept-uKTVZC/` |
| 真实G2产物平台四层检查 | 结构/计数/视频/内容全部通过，0警告 | 同上 `platform-check2.json` |
| 真实G2产物LeRobot加载 | 0.6.2，首帧/末帧均读出，state169/action40，深度1通道 | 同上 `loader-check.json` |
| 数据盘只读 | 成功验收前后 sda=240、sdb=99704，不变 | 同上 `sectors-before.txt`、`sectors-after.txt` |
| G2完整平台链路 | 两个真实合成归档、真实bwrap、预览→剔除致命集→转换→四层检查→临时入库/规范入口血缘，1 passed | `~/.cache/rdp-dispatch/m4.6-08/g2-drill-review2.log` |
| Alpha原接入完整链路 | 真实两集本地样本，保留649806、剔除650435，临时入库/血缘成功，3 passed | `~/.cache/rdp-dispatch/m4.6-03/alpha-drill-review3.log` |
| 全量make check | 3108后端 + 441前端全部通过，0 skipped；格式/类型/依赖/契约/OpenAPI均通过 | `~/.cache/rdp-dispatch/m4.6-08/final-check.log` |
| 工具登记 | Alpha、G2、MCAP三个均可用 | 执行线真实 `load_tool_registry` 核对 |

## 最终复验

Alpha 部分解压场景的快照误判已修复：前后真实文件快照仍须一致；已有观测不能漏报，缺快照只允许对应强制剔除的 fatal 行，不能放行可转行。执行线独立重跑相关回归 35 passed，完整 Alpha 链路 3 passed（`~/.cache/rdp-dispatch/m4.6-03/alpha-drill-final2.log`）。

最终 `make check` 全部通过：后端 **3120 passed、0 skipped**，前端 **441 passed**；Ruff、类型、依赖、函数契约、OpenAPI、前端全部静态检查通过。证据 `~/.cache/rdp-dispatch/m4.6-08/final-check2.log`。上表 3108 是修复前的一轮全量结果，不替代本次最终复验。

使用/运维手册、README、根目录导读、术语与 ADR 已更新。以上为发布前验收快照；验收后负责人已授权 `merge,update,push`，运行实例版本以升级结果为准。

## 本轮发现并修复的问题

1. Alpha任务ID真实为字符串、未标注集task可为null，原假工具fixture把契约写错。
2. 常规tests不得硬编码真实工具/数据路径；手动验收分离到scripts/drills，未放宽静态路径审计。
3. G2 AV1在PyAV中名为libdav1d，输出重封装必须opaque=True，不找不存在的libdav1d编码器。
4. 真实视频统计count=0为占位，直接官方聚合会NaN；保留原值并按真实加载口径补算，不能伪造count或nan_to_num。
5. 深度不是RGB：补算使用gray12le及LeRobot的反量化路径和默认单位；缺物理量化标定的源数据明确不作标定认证。
6. 平台入库兼容旧video_info及libdav1d→av1；双字段冲突仍拒绝，未知编码不泛化放行。
7. 观测目录mtime不能代表子文件内容，新增受控快照；实际目录枚举必须O_NOATIME且失败不降级。
8. 来源.json只在规范按任务入口，演练不能要求按格式副本重复持有血缘。
9. 手动-I验证只设置sys.path不足以让平台子进程导入工作树；外层还必须显式设置PYTHONPATH=$PWD/src，避免验证到主仓旧代码。

## 边界

- 没有部署、推送、修改生产导航/生产配置；没有NAS写入或全量转换。
- 真实G2仅抽验一个归档，不能推广为404个归档全部通过。
- G2产物保留源video_info；LeRobot提示源未声明depth_unit，因此物理单位追溯仍依赖源数据提供者。统计补算仅保证与指定版本加载值一致。
- 格式验收直接转换真实小归档不是生产清洗入库；生产必须通过预览选择和入库检查。
- 实现来源工作区 `robot-data-platform.wt/m4.6-agibot`；各Codex工作树保留供对比。
