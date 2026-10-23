评审发现下面的问题，逐条修复，别处不动。三个公开函数（`ensure_utc`、`check_file`、`main`）的签名和 docstring 不改；修复用私有函数和测试完成。每条先写一个能复现问题的测试，看到它失败，再改实现（$tdd）。

1. 问题：property 的 setter、deleter 被当成公开函数，要求六项。复现：公开类里 `@v.setter def v(self, x: int) -> None: """设置值。"""`，脚本报 `缺少 Args:；缺少 Returns:；…`。位置：`scripts/check_contracts.py` 识别装饰器的地方（`_DECORATOR_KINDS` 一带）。期望：`@<名>.setter`、`@<名>.deleter` 和 getter 一样，只要一句非空职责（工单：私有函数和 `@property` 至少一句职责）。
2. 问题：`functools.cached_property` 没被认作 property。期望：直接名（`from functools import cached_property`）、限定名（`functools.cached_property`）和导入别名都按 property 处理。
3. 问题：小节标题行有尾随空格（`Side Effects: `），或者标题和内容写在同一行（`Returns: 无`）时，都报成"缺少 Returns:"，提示不准。期望：尾随空格不影响识别标题；标题和内容在同一行时，报一条准确的问题，例如 `Returns: 标题后要换行再写内容`，不报"缺少"。这仍然算问题，退出 1。
4. 问题：非 .py 参数的报错里路径重复。复现：`.venv/bin/python scripts/check_contracts.py x.txt` 输出 `检查失败: x.txt: x.txt: 不是 .py 文件`。位置：`main` 的报错输出。期望：路径只出现一次，例如 `检查失败: x.txt: 不是 .py 文件`；相关测试断言改严，能抓到重复。
5. 问题：`tests/test_timeutil.py` 的 `test_input_unchanged` 在 docstring 里说"不依赖系统时钟或本地时区"，但测试没有验证这一点。期望：用 `monkeypatch.setenv("TZ", …)` 加 `time.tzset()` 换两个不同的本地时区（例如 `Asia/Shanghai`、`America/New_York`），结果相同；测试结束后恢复 `tzset()`，不影响别的测试。
6. 问题：`pyproject.toml` 里的 `tmp_path_retention_policy = "none"` 会删掉失败测试的现场，和 CODING_STANDARDS 7.8"测试没过时先保留证据"冲突。这是上一轮提示写成"用完不留"引起的，不怪你。期望：改成 `"failed"`，注释写明理由。

修完后 `make check` 全绿。临时试验用 `tmp_path` 或 `tempfile`，用完不留，`/tmp` 和工作目录里都不留试验文件。

边界：
- 只改 `src/`、`tests/`。本票允许改的受保护文件：`pyproject.toml`（只写 `[tool.*]` 表）、`Makefile`、`scripts/check_contracts.py`、`.githooks/pre-commit`（保持可执行位）、`.gitignore`（只追加检查链产生的缓存目录）。`uv.lock` 不改。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。
- 沙箱不能联网，不要尝试安装任何东西。需要新依赖时停下，在最终回复里写依赖申请（AGENTS.md 规则 7）。

最终回复：逐条写处理结果（改了哪里、加了哪个测试）；`make check` 最后一次运行的命令和末尾输出，原样贴出。
