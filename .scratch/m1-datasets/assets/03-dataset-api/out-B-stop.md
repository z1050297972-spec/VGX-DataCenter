已触发你明确规定的停止条件：**既有 `JobService` 会间接引入存储根访问模块**。本轮已停下，尚未完成第一段检查点。

**1. 改动清单**

仅修改 [pyproject.toml](/home/shawn/桌面/robot-data-platform.wt/m1-03-dataset-api/pyproject.toml:153)：

- 移除对整个 `rdp.jobs.datasets` 的禁入。
- 删除三条 ignore。
- 保留指定六个禁入模块及 `allow_indirect_imports = false`。

未修改业务实现、未暂存或提交。

**2. `make check` 结果**

ruff、basedpyright 通过；import-linter 失败。**未进入 pytest，因此没有本轮 pytest 汇总行。**

末尾输出原样：

```text
rdp.jobs.dataset_browser is not allowed to import rdp.jobs.storage:

-   rdp.jobs.dataset_browser.service -> rdp.jobs.service (l.29)
    rdp.jobs.service -> rdp.jobs.registry (l.31)
    rdp.jobs.registry -> rdp.jobs.execution (l.27)
    rdp.jobs.execution -> rdp.jobs.storage (l.49)


make: *** [Makefile:29: check] Error 1
```

**3. 契约变更申请、依赖申请**

- 依赖申请：无。
- 需要执行线决定如何拆开浏览契约对 M0 作业服务的依赖；本轮没有自行改变已批准签名，也没有恢复豁免或绕开检查。

**4. 阻塞与剩余工作**

阻塞来自 [浏览服务第 29 行](/home/shawn/桌面/robot-data-platform.wt/m1-03-dataset-api/src/rdp/jobs/dataset_browser/service.py:29) 导入 `JobRequest、JobService`：

```text
dataset_browser.service
→ jobs.service
→ jobs.registry
→ datasets.rescan
→ infra.storage
```

另有 `registry → execution → jobs.storage`。因此即使只实现读取接口，当前服务依赖也已经违规；这次报错链路并非 `reading` 或 `fingerprint` 引起。

尚未进行：

- 第一段全部只读接口实现及行为测试。
- 布局审计操作码、字段和前端展示的删除。
- 第二段面板、作业提交、布局偏好及 OpenAPI 收尾。
- 0008 仍在 pending，未激活。

**5. 先红后绿**

36 项测试均未解除跳过、未单独执行，尚未进入红绿循环；没有“第一次就绿”的项目。当前红灯是收窄契约后的 import-linter，按你的停止指令保留了失败现场。