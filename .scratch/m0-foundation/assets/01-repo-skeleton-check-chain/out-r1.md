6 项均已修复，完成了对应的失败复现与验证：

1. **属性访问器**：`_decorators` 将 getter、setter、deleter 按 property 处理。新增 `test_property_accessors_require_only_summary`，验证一句职责通过、空文档失败。
2. **cached_property**：补充直接名和限定名识别，复用导入别名解析。新增 `test_cached_property_forms_require_only_summary`。
3. **小节标题**：允许尾随空白；同行内容明确报“标题后要换行再写内容”。新增 `test_section_heading_trailing_whitespace`、`test_inline_section_content_reports_layout_error`。
4. **重复路径**：`_collect_problems` 不再重复补充已有路径。加强 `test_invalid_file_kind`，精确断言完整错误输出。
5. **时区独立性**：`test_input_unchanged` 切换上海、纽约时区，并在 `finally` 恢复时区状态。临时错误实现验证了旧测试会放过回归、补强后能检出。
6. **失败现场保留**：配置改为 `"failed"`，注明规范 7.8。新增 [test_check_configuration.py](/home/shawn/桌面/robot-data-platform.wt/m0-01-repo-skeleton-check-chain/tests/test_check_configuration.py)，验证失败现场保留、成功样例清理。

三个公开函数的签名和 docstring 未改；无依赖变更，未暂存或提交。本轮临时文件已清理。

最后一次命令：`make check`，退出码 **0**。关键步骤及末尾输出原样摘录：

```text
[3/6] basedpyright
.venv/bin/basedpyright
0 errors, 0 warnings, 0 notes
```

```text
[5/6] 契约检查
.venv/bin/python scripts/check_contracts.py src/rdp scripts
问题总数: 0
[6/6] pytest
.venv/bin/pytest
```

```text
tests/test_timeutil.py ..........                                        [100%]

============================== 61 passed in 3.72s ==============================
```