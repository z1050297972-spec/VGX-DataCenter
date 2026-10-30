**改动清单**

- 详情响应新增只读 `provenance`，从规范入口读取当前来源、标注人和时间；两种视图显示一致。
- 未标注显示“当前：未知（还没有 来源.json）”；已标注显示来源、姓名和 `formatDateTime` 时间。
- 选择框默认选中当前来源；相同值禁用预览并提示“和当前一样”。
- 四项新增回归均先红后绿，并补强写入完成后返回详情的断言；两项变异均被抓住。
- 已运行 `make api-types`。未暂存、未提交。

**检查汇总**

`make check` 全绿，**0 skipped**：

```text
2483 passed, 8 warnings in 91.74s (0:01:31)
Test Files  34 passed (34)
     Tests  329 passed (329)
```

`vite build` 成功，主入口 **50.45 kB < 500 kB**。`dist` 和本轮临时文件已删除。