**1. 改动清单**

无。发现 429 尚未获准后，按你的明确要求停止，未编写骨架、暂存或提交。

**2. `make check`**

本轮未运行：在契约检查阶段触发停止条件，尚无代码改动或新增跳过测试。

开始与停止前均执行了：

```text
git status --porcelain --untracked-files=all
```

两次输出均为空，工作区干净。

**3. 契约变更申请、依赖申请、受保护文件申请**

契约变更申请：

- G2 等待中的登录使用 **429 Too Many Requests**，归入 `InputError`；返回 `ProblemResponse`，携带诊断。
- 增加 `Retry-After` 响应头，单位秒，剩余等待时间向上取整；等待期间不校验口令。
- 在 `ALLOWED_HTTP_STATUSES[DiagnosticCategory.INPUT]` 增加 429，同步接口状态码表及测试。401、403 按本票已授权范围一并补齐。
- 主仓库 `CODING_STANDARDS.md` 6.2 当前没有 429，需由 Claude 先补充获批定义。

依赖申请：无。额外受保护文件申请：无。

**4. 需要评审决定的地方**

请确认上述 **429 的类别、响应格式和 `Retry-After` 语义**，再继续骨架。

停止依据是你本次派工中的明确要求：“429 是否在 `ALLOWED_HTTP_STATUSES` 里；不在就停下，写进第 3 块”。其余设计选择尚未落定。