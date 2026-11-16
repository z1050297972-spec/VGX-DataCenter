# G2 本地手动演练

常规 `tests/` 不依赖本机工具或 conda。这里显式调用本机 G2 工具和其 `tests/factory.py`，缺失依赖或 namespace 权限时直接失败，不默认跳过。

在仓库根目录执行完整链路：

```bash
g2_drill_root=$(mktemp -d "$PWD/scripts/drills/.g2-run-XXXXXX")
PYTHONPATH=$PWD/src .venv/bin/pytest -q \
  scripts/drills/test_g2_cli_platform.py::test_real_g2_ingest_preserves_lineage \
  --basetemp "$g2_drill_root"
```

演练目录必须是新建的私有目录；pytest 会管理 `--basetemp`。不能使用宿主 `/tmp`，生产 bwrap 会把它替换为私有 tmpfs。失败现场保留在该目录，排查后可删除本次目录。

完整链路只注入 OS 挂载观察。两个真实合成归档经真实 bwrap 预览、原生剔集和转换，在同一个临时数据库执行四层检查与真实入库；不搬运或伪造作业终态。血缘从 `DatasetRow.canonical_entry_path` 读取，两个视图分别验证链接。namespace 被拒绝时保留失败，由有权限的执行线运行，不能去掉沙箱重跑。

其余真实 CLI 回归也已迁入这里，可把上述测试路径改为 `scripts/drills/` 运行全部。辅助回归有针对取消等外部边界的控制；完整链路使用生产默认执行能力。

演练只在临时登记副本同步当前工具配置、规则和真实 launcher/tree 指纹，不修改工作树登记包或工具本体。工具最终定版后，工作树登记配置同步和最终指纹重算由执行线完成。
