你的 429 方案执行线同意按它写骨架：G2 等待中的登录返回 429，归 `InputError`，`ProblemResponse` 带诊断，加 `Retry-After`（秒，剩余等待时间向上取整），等待期间不校验口令；`ALLOWED_HTTP_STATUSES[DiagnosticCategory.INPUT]` 加 429，`rdp.api.errors` 模块 docstring 的状态码表同步，401、403 一并补齐。这是对第 4 张已获批契约的改动，负责人在骨架关卡统一拍板；`CODING_STANDARDS.md` 6.2 由 Claude 在关卡通过后改，你不用改。

上一条派工提示（prompt-A.md）的其余要求全部不变。现在继续把骨架写完：遇到别的"要停下"的情况，同样不要停，按你认为最好的方案写进骨架，在最终回复第 3、4 块写清楚，由骨架关卡决定。只有需要新依赖或改 `pyproject.toml` import-linter 段以外的受保护文件时才停。

最终回复照 prompt-A.md 的四块。
