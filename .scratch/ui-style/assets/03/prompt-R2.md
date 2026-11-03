R1 的 9 条都看过，效果到位。截图复查又发现 3 个问题，截图在 /home/shawn/.cache/rdp-ui-preview/shots/t03r1/。硬约束同前。

1. **阻塞：原文件查看器被塞进了标题右侧的按钮行。**`FileViewerEntry` 渲染的是"按钮 + 展开后的查看器"，你把它放进了 `DatasetSizeSummary` 的 `actions`，点"查看原文件"后，整个查看器在标题右侧那一小块 Flex 里展开，标题被挤到左边竖着居中（见 viewer-open.png）。
   修法：`FileViewerEntry` 不放进 `actions`。在大小分节下方单独占一整行，和原来一样，展开后查看器占满详情宽度。`actions` 里只留"重新检查""统计大小"。不要为了这事拆 `FileViewerEntry` 的内部结构。
2. **分隔线重复。**`FieldSummary` 自己末尾加了 `Divider`，`Details.tsx` 在它后面又加了一条，结果出现两条线（detail-y1400.png 上方）。另外，`DiagnosticEntries`、`NavigationDocumentViewer`、`SubtasksViewer` 这类可能什么都不渲染的组件，前后无条件放 `Divider`，内容为空时也会出现连续两条线。
   修法：分节组件内部不要自己加 `Divider`。分隔改成由各分节容器统一负责：给分节加一个类，用 CSS 写"相邻分节之间画上边线并留 24px 间距"（例如 `.browser-detail-section + .browser-detail-section`），或者用其他不会因为空分节产生连续线的写法。
3. 数据来源分节里，下拉框和"预览改动"按钮贴在一起没有间距，用 `Flex gap` 或 `Space` 隔开。

做完跑 `make check`，要全绿。最终回复第一行写状态，然后逐条写处理结果，最后贴出 `make check` 的命令和末尾输出原文。
