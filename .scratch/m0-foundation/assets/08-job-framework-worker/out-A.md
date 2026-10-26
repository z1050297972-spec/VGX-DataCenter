**1. 改动清单**

无文件改动，契约骨架未交付。发现现有审计表无法表示作业对象，触发你规定的停工条件。临时检查日志已删除。

**2. `make check`**

最后运行命令，退出码 `0`：

```bash
make check > /tmp/rdp-m0-08-baseline-check.log 2>&1
```

pytest 汇总原文：

```text
================== 1265 passed, 1 warning in 74.04s (0:01:14) ==================
```

末尾输出原文：

```text
 Test Files  14 passed (14)
      Tests  179 passed (179)
   Start at  04:00:28
   Duration  6.35s (tests 54%, environment 28%, import 17%)
```

pytest、Vitest 均为 **0 skipped**。这是未改动代码的基线检查。

```bash
git status --porcelain --untracked-files=all
```

输出为空，工作区干净。

**3. 契约变更申请、依赖申请**

契约变更申请：

- [审计表约束](/home/shawn/桌面/robot-data-platform.wt/m0-08-job-framework-worker/src/rdp/audit/models.py:44) 目前只允许 `account/audit_settings`。申请在 `0004` 中扩展为 `account/audit_settings/job`，保留历史记录、索引及编号不复用语义，不改旧迁移。
- `ObjectRef.kind`、`ObjectResponse.kind` 同步增加 `job`，更新校验和生成类型。作业对象不参与对象账号筛选；作业编号、类型和状态进入规定的明细白名单，参数不进入明细。

依赖申请：无。  
已合并代码的公开签名实际改动：无。

**4. 需要评审决定的地方**

是否批准上述审计对象扩展，使本票可以修改已有审计表的 CHECK 和 API 对象类型？

需要确认的依据是你本轮规定的停工条件：“要改已有的对外行为……已有表结构”。现有数据库约束、领域类型和响应模型都没有作业对象；仅增加操作枚举和明细字段无法满足“作业不是账号”的要求。