骨架已获批（执行线按负责人授权过关卡），契约提交是 `9b71070`。关卡决定见工单最后一条 Comment，其中有两处要在本轮改：

1. **禁入契约收窄**：只禁存储根访问相关的模块，即 `rdp.jobs.storage`、`rdp.infra.storage`、`rdp.api.storage`。`rdp.jobs.execution`、`rdp.jobs.worker`、`rdp.jobs.registry` 照旧禁。
   - 不再整体禁 `rdp.jobs.datasets`，删掉那三条 ignore。
   - 详情接口判断"索引过期"时，直接复用第 01 张的 `rdp.jobs.datasets.reading` 和 `fingerprint`，不要另写一套读取或指纹逻辑。
   - 保持 `allow_indirect_imports = false`。如果某个要复用的模块会间接引入存储根访问，就停下来在第 4 块说明，不要绕开。
2. **布局偏好不写操作日志**：去掉 `SET_DATASET_LAYOUT` 操作码、`dataset_layout` 审计字段，以及前端对它的展示，同步更新相关测试。

动手前用绝对路径重读工单 /home/shawn/桌面/robot-data-platform/.scratch/m1-datasets/issues/03-dataset-api.md（含 Comments）和 docs/agents/codex-workflow.md 第 7.1 节。

用 $tdd 和 $enterprise-coding，逐个去掉 36 项的跳过：先单独运行，看到红，再实现；第一次就绿的逐项说明原因。

**分两段交**
- **第一段**：先做树、列表与筛选、详情、子任务这几组只读接口，加上不碰存储根的测试（验收第 2、3、4 条），然后停下交检查点，`make check` 全绿。执行线会在沙箱外，对真实导航层建好的索引做一次只读演练（验收第 1 条），包括量 14 MB `子任务.json` 的响应时间。
- 第二段（下一次派工）：面板、重新检查和统计提交、布局偏好、OpenAPI 收尾。

交检查点时：激活迁移 0008 留到第二段做；OpenAPI 有变化就用 `make api-types` 生成。

边界同骨架阶段：
- 只改 `src/`、`tests/`；`pyproject.toml` 只改那条 import-linter 契约；
- 不 `git add`、不提交；
- 不读不写 `/mnt`；
- 不联网、不安装；
- 不碰真实部署，不占用 8600 端口。

60 分钟内交第一段的检查点。最终回复五块：
1. 改动清单；
2. `make check` 的 pytest 汇总行和末尾输出；
3. 契约变更申请、依赖申请；
4. 拿不准的地方，以及第二段还剩什么；
5. 先红后绿，每个测试一行。
