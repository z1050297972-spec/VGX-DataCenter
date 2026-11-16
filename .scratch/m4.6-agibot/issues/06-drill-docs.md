# 演练与文档（执行线）

Status: done（实现及验收完成；负责人已授权合并、升级、推送）

1. 登记包 `tools/agibot2lerobot/`：`tool.toml`、`configs/agibot_g1.toml`、`configs/agibot_g1_dexhand.toml`、`cleaning/` 两份规则（内容与工具自带的逐字节相同）。
2. 演练（不读数据盘，照 M4.5 的做法）：回环镜像装样本（task 327 两集 + 仿造的共用本体感知归档）当只读根、另一个当测试可写根；演练部署里建数据集和 `agibot_native` 数据块 → 清洗预览 → 报告里剔除一集 → 转换 → 入库检查 → 入库；核对产物、回执、血缘、工具缓存目录、数据盘扇区。
3. 文档：使用手册（AgiBot 转换一节）、运维手册（工具缓存目录、重新登记指纹的步骤）、术语表、ADR 0008 修订节、README。
4. followups：真实数据上的第一次转换、tar 观测任务的解压、dataset-31/30 填型号（都等负责人）。

## Comments

- 执行线收尾：最终后端3120、前端441全绿；Alpha真实本地样本全链路3 passed、G2合成归档真实bwrap全链路1 passed、G2真实task_3405归档13集30681帧四层检查通过。详见 `../assets/verification-results.md`。没有生产部署或推送。
