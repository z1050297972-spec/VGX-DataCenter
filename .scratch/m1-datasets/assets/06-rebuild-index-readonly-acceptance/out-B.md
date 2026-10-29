**1. 改动清单**

后半段完成，仅改三个文件：

- `src/rdp/ops/rebuild.py`：清空、发布、成功审计同事务；发布失败保留旧索引；扫描失败明确提示空索引和重跑命令。
- `src/rdp/jobs/datasets/rebuild.py`：按空基线扫描，不读取旧损坏索引。
- `tests/test_ops_rebuild_index.py`：补齐竞争、发布失败、审计失败及空索引提示测试，删除全部跳过标记。

未提交、未访问 `/mnt` 或真实部署；临时检查日志已清理。

**2. `make check`**

连续三轮退出码均为 **0**，均 **0 skipped**：

```text
================= 2288 passed, 8 warnings in 81.20s (0:01:21) ==================
================= 2288 passed, 8 warnings in 81.65s (0:01:21) ==================
================= 2288 passed, 8 warnings in 79.26s (0:01:19) ==================
```

每轮前端均为 251 passed。第三轮末尾：

```text
All matched files use Prettier code style!
[11/11] Vitest

 Test Files  23 passed (23)
      Tests  251 passed (251)
   Start at  09:42:03
   Duration  7.55s (tests 47%, environment 31%, import 21%, setup 1%)
```

**3. 契约变更申请、依赖申请**

无新增申请。按本轮要求调整事务边界；已批准的操作码、审计对象、迁移 0009 和 OpenAPI 均未改动。无新增依赖。

**4. 执行线须知、剩余事项**

命令仍为：

```bash
.venv/bin/python -m rdp rebuild-index
```

失败行为明确区分：

- 重建期间启动 worker：按 M0 语义立即拒绝，退出 **2**。
- 发布或成功审计失败：事务回滚，旧索引及大小统计保留，补记失败日志。
- 扫描阶段失败：沿用本轮确认的“删掉重建”语义，清空索引并输出：**“索引现在是空的，修好原因后重跑 rdp rebuild-index。”**

数据库若持续不可写，失败日志也可能无法落库，此时会报告补记失败。代码部分无剩余跳过项；手册和真实实测数字由执行线继续。

**5. 先红后绿**

| 测试 | 记录 |
|---|---|
| `test_rebuild_publication_failure[publication]` | 红：旧索引丢失 → 绿 |
| `test_rebuild_publication_failure[audit]` | 红：旧索引丢失 → 绿 |
| `test_rebuild_scan_failure_is_audited` | 新增提示断言跑红：缺少空索引提示 → 绿 |
| `test_rebuild_lock_race` | 首次即绿：前半段已有全程持锁；真实 worker 入口竞争时退出 2，无需新增实现 |