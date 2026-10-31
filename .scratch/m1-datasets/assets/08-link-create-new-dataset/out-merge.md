7 个冲突文件的内容已处理，无残留冲突标记。

- registry 保留两个创建预览和数据来源预览，生产类型共 **12 个**，四处测试断言同步。
- 两份生成文件由 `make api-types` 重新生成。
- 新增跨票集成测试：创建后的来源能被两视图详情、来源筛选及后续来源修改正常使用。
- 共用文件 `jobs/queries.ts`、`jobs/Pages.tsx` 合并缓存刷新逻辑，避免重复失效。
- 无契约变更、无新增依赖。

`make check` 退出码 0，**0 skipped**：

```text
2551 passed, 8 warnings in 85.51s
Test Files  35 passed (35)
     Tests  349 passed (349)
```

Vite 构建成功，主入口 **55,255 bytes < 500 kB**；`dist` 和本轮临时文件已删除。

暂存未完成：`git add` 因主仓库索引只读而失败（`index.lock: Read-only file system`），所以索引仍显示 7 个 `UU`。执行线需暂存原 7 个冲突文件，另加上述两个缓存文件和 `tests/test_creation_origin_compatibility.py`。未执行提交。