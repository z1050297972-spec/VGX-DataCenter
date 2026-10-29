你停得对。阻塞原因是 `JobService` 本身就会间接引入存储根访问，和 reading、fingerprint 无关。执行线决定：

- 把 `rdp.jobs.dataset_browser` 拆成两部分：
  - **只读查询模块**（例如 `queries.py`）：树、列表与筛选、详情、子任务、面板、布局偏好的读写，都放在这里。它只能 import 索引模型、`rdp.jobs.datasets.reading`、`fingerprint`、`catalog`、`types` 和基础层。
  - **提交作业模块**（例如 `commands.py`）：重新检查、统计大小，经 M0 的 `JobService` 只插作业行，做法和现有的 `rdp.api.jobs` 一样。
- import-linter 禁入契约的 `source_modules` 改成：只读查询模块，加上 `rdp.jobs.dataset_browser.schemas`。禁入列表照旧，`allow_indirect_imports = false` 保持不变。提交作业模块和 `rdp.api.datasets` 包不在这条契约里。
- 运行时的边界仍由验收 2 的测试保证：把假存储根设成不可读，所有接口照常返回。
- 已获批的服务签名如果因为拆分要挪位置，只挪位置、不改含义，在第 3 块列出挪到了哪里。

然后按上一条指令继续做第一段：只读接口，加验收第 2、3、4 条，交检查点；同时去掉布局审计相关的东西。要求和边界都不变。60 分钟内交付，最终回复五块，格式同上。
