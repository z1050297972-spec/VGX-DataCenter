# Issue tracker：本地 Markdown

本仓库的工单和 spec 都是 `.scratch/` 下的 markdown 文件。目录怎么命名（里程碑、开图）以 `docs/README.md` 为准。

## 约定

- 一个功能或里程碑一个目录：`.scratch/<feature-slug>/`
- spec 放在 `.scratch/<feature-slug>/spec.md`
- 实现工单一张一个文件：`.scratch/<feature-slug>/issues/<NN>-<slug>.md`，从 `01` 开始编号
- triage 状态写在工单顶部附近的 `Status:` 行（取值见 `triage-labels.md`）
- 评论、派工和评审记录追加在文件末尾的 `## Comments` 标题下

## 当 skill 说 "publish to the issue tracker"

在 `.scratch/<feature-slug>/` 下新建文件（目录不存在就先建）。

## 当 skill 说 "fetch the relevant ticket"

读取对应路径的文件。用户通常会直接给出路径或工单编号。

## Wayfinding 操作

供 `/wayfinder` 使用。**map** 是一个文件，每张工单对应一个 **child** 文件。

- **Map**：`.scratch/<effort>/map.md`（正文分 Notes / Decisions-so-far / Fog 三部分）
- **Child ticket**：`.scratch/<effort>/issues/NN-<slug>.md`，从 `01` 编号，正文写问题。`Type:` 行记录类型（`research`/`prototype`/`grilling`/`task`）；`Status:` 行记录 `open`/`claimed`/`resolved`（新建时为 `open`）
- **Blocking**：顶部附近写 `Blocked by: NN, NN`。所列文件全部 `resolved` 后，该工单解除阻塞
- **Frontier**：扫描 `.scratch/<effort>/issues/`，找出未关闭、未阻塞、未认领的工单；编号最小的优先
- **Claim**：开工前先把 `Status:` 改为 `claimed` 并保存
- **Resolve**：在 `## Answer` 标题下追加答案，把 `Status:` 改为 `resolved`，再在 `map.md` 的 Decisions-so-far 里追加一条上下文指针（要点 + 链接）
