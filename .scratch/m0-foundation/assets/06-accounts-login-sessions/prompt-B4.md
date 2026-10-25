检查点收到，接着做完整票，规则照 prompt-B.md 和 prompt-B3.md。

剩下的：
1. `tests/test_accounts.py` 里你列的 51 个函数（68 个用例）。同类测试可以合跑看红。
2. 旧的 Python HTTP 测试（`test_web_app.py`、`test_api_errors.py`、`test_api_database.py`、诊断演示相关）补登录前置条件。断言不改；只有因为全局鉴权顺序（Origin、401、403）导致原断言不再成立时才改，并在第 4 块逐条列出改了哪条、为什么。
3. 全部无 skipped 后，最后跑一次 `make check`。

80 分钟左右还做不完，照旧停在全绿的位置交检查点。第 5 块沿用 P / R / R0 记法，只写本轮新做的测试。
