"""写导航层的底座（领域层，M1-07、ADR 0005、ADR 0009），属于现有 jobs 领域层。

负责：预览状态的记录与核对、写入规则（JSON 写出、按格式入口生成、编号分配）、
写入日志与原子写、中断后的回滚恢复、"导航层恢复失败"标记、变更记录、
`来源.json` 的读写。不负责：建链、新增数据集、改指向、数据来源标注这四种具体作业
（M1-08、09、10 在本底座上各自加预览作业）；不写 NAS 存储根（等 12 的 1B）。

模块分两侧，边界由 pyproject 的 import-linter 合约保证（规范 1.4）：
- Web 可读侧：models、policy、marker、previews、changes、provenance、jsonio、
  allocation、preview_state、journal（只读写状态目录，不碰导航层）。
- worker 写入侧：atomic、recovery、pipeline、replica 的执行部分。只有 worker 一侧 import，
  Web 和接口不得依赖。
"""
