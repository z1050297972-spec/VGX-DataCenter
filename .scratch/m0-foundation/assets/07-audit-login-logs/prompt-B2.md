检查点收到，接着把整票做完，规则照 prompt-B.md（先读 7.1，先写测试再写实现，同类测试可以合跑看红）。

剩下的顺序：`tests/test_audit_accounts.py`（92 个用例）→ `tests/test_audit_api.py`（26 个）→ 前端 `src/web/src/api/audit.test.ts`、`src/web/src/audit/Pages.test.tsx`（39 个）→ 收尾（搜过程说法、删临时文件）→ 最后一次 `make check`。

80 分钟左右还做不完，照旧停在相关测试全绿的位置交检查点。第 5 块只写本轮新做的测试，沿用 R / P 记法。
