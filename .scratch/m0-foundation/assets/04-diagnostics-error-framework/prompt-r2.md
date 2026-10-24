评审发现下面的问题，逐条修复，别处不动。这三条只改注释和测试 docstring，不改任何行为，也不用先红后绿。

1. 问题：测试 docstring 还停在派工阶段的说法（CODING_STANDARDS 4.2、4.4）。位置：`tests/test_api_errors.py` 约第 753 行（"验证契约：派工B每个已知API路由……"）。期望：去掉"派工B"，只写现在要验证的行为。改完在本票改过的所有文件（`git diff 37871e4 --name-only` 列出的文件）里再搜一遍"派工""在 B 中"，一处都不留。
2. 问题：`src/web/src/api/problems.ts` 里"对应 CODING_STANDARDS 6.2；修改规范表时须同步更新此运行时校验映射"这条注释贴在 `requestId` 正则上方，不在它说的 `statusTable` 上方。位置：约第 231–234 行。期望：注释挪到 `statusTable` 正上方；`requestId` 正则另写一句注释，说明它对应后端 `ProblemResponse.error_id` 的 uuid4 hex 格式。
3. 问题：本票新写的测试里有几个 docstring 不以"验证契约："开头，和同文件其他测试不统一（CODING_STANDARDS 第 7 节的写法）。位置：`tests/test_diagnostics.py` 约第 415、506、515 行，`tests/test_api_errors.py` 约第 785、873、891、915 行。期望：都改成以"验证契约："开头，后面的内容不变。

修完后 `make check` 全绿，pytest 和 Vitest 都没有 skipped。

边界：
- 只改 `src/`、`tests/`。本票允许改的受保护文件：`pyproject.toml`（只改 `[tool.importlinter]`；本轮不用动）。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。
- 不安装任何东西，不访问网络（沙箱为了跑测试开了网络权限，但这张票用不到网络；评审会查运行日志，出现安装或联网的命令整轮打回）。需要新依赖时停下，在最终回复里写依赖申请（AGENTS.md 规则 7）。
- 自己在 `/tmp` 或别处建的试验文件，交付前删掉。不写 `.git/info/exclude`。

最终回复：逐条写处理结果；`make check` 最后一次运行的命令和末尾输出，原样贴出，再原样贴出跑之前和跑之后的 `git status --porcelain --untracked-files=all`。
