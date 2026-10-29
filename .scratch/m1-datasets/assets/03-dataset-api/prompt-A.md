你在 M1 第 03 张工单「数据集接口」的工作目录 /home/shawn/桌面/robot-data-platform.wt/m1-03-dataset-api（git worktree，分支 t/m1-03-dataset-api，从 main 开出，第 01 张已经合并）里写契约骨架。这张票分级是**骨架关卡**：它是跨模块的接口，前端第 04 张要照着生成的类型开发。

第 02 张（扫描第二段与统计大小）此刻在另一个工作目录里并行开发，两张票的分工如下：
- 本票只读索引表：表结构是第 01 张定的，第 02 张要填的列已经在表里。
- 本票只提交统计大小作业：作业类型的键名由第 02 张定义。骨架里按 `dataset_sizing` 写，写成一个具名常量，第 4 块里标出来，合并时再对齐。
- 本票不 import 第 02 张的模块。

先用绝对路径读这些：
- 工单 /home/shawn/桌面/robot-data-platform/.scratch/m1-datasets/issues/03-dataset-api.md 全文
- AGENTS.md、docs/standards/CODING_STANDARDS.md
- docs/agents/codex-workflow.md 第 3.0 节和第 7.1 节
- `.scratch/m1-datasets/spec.md`；11 的 Answer（Q8、Q9、Q14 等）；ADR 0006
- `.scratch/platform-v1/issues/16-dataset-browser.md`：三种布局要的数据
- 已经合并的代码：
  - `src/rdp/jobs/datasets/`（索引模型、指纹、扫描作业）；
  - `src/rdp/api/` 里现有的接口写法：全局 Origin 检查、认证、强制改密、五段诊断、OpenAPI 导出；
  - M0 的作业提交接口；
  - import-linter 契约（在 `pyproject.toml` 里）。

用 $enterprise-coding。这一步只交契约骨架：
1. 路由、请求模型和响应模型、服务函数的签名、类型和六项 docstring 写全，函数体只写 `raise NotImplementedError`。路由先挂上去，OpenAPI 要能导出，前端类型用 `make api-types` 生成，不手改生成的文件。
2. 布局偏好表照 M0 的做法建迁移，骨架阶段放进 `pending/`。
3. "接口不访问存储根"这条边界，写成一条 import-linter 契约（工单允许改 `pyproject.toml` 加这一条）。
4. 测试清单写成跳过的测试，docstring 写明验证哪条契约行为，覆盖验收第 2–7 条。
5. `make check` 全绿。

骨架关卡要看的东西，在第 4 块单独列出：
- 每个接口的路径、方法、请求和响应字段、错误码；
- 布局偏好表的结构；
- import-linter 契约的写法；
- 14 MB 的 `子任务.json` 怎么返回。

边界：
- 只改 `src/`、`tests/`；`pyproject.toml` 只加上面那条 import-linter 契约，ruff、basedpyright 确实需要时也可以改；OpenAPI 生成文件用 `make api-types` 生成。
- 不 `git add`、不提交。
- **不读不写 `/mnt`**。
- 不联网、不安装，不新增依赖。
- 不碰真实部署，不占用 8600 端口。
- 自己建的试验文件交付前删掉。

只有三种情况停下：要加新依赖；要改允许范围以外的受保护文件；要改已合并契约的含义。

60 分钟内交付。最终回复四块：
1. 改动清单；
2. `make check` 末尾输出原样；
3. 契约变更申请、依赖申请；
4. 骨架关卡要看的东西，以及拿不准的地方。
