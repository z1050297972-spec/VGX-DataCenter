骨架已获批，契约提交是 `b1fec00`（`契约：仓库骨架和检查链`），经过了钩子。现在按测试清单逐个函数实现，用 $tdd 和 $enterprise-coding：
1. 每次去掉一个测试的跳过，先运行、看到它失败，再写实现让它通过。
2. 已获批的签名、类型和 docstring 不改。确实要改时停下，在最终回复里写契约变更申请：哪个函数、改什么、为什么。
3. 最后 `make check` 全绿，测试里不留骨架阶段的跳过。

本次的具体要求（工单「派工分段」的派工 B，以及骨架关卡上负责人的决定，见主仓库目录工单 /home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/issues/01-repo-skeleton-check-chain.md 的 Comments 末尾）：
- 实现 `src/rdp/infra/timeutil.py` 的 `ensure_utc` 和 `scripts/check_contracts.py`。脚本只用标准库（`ast` 等）；需要的私有辅助函数可以加，每个至少一句职责。测试里的期望值手算，或者来自契约，不调用被测逻辑生成（CODING_STANDARDS 7.2）。契约检查脚本的测试在临时目录（`tmp_path`）里生成样例源文件，再用 `sys.executable` 以子进程运行脚本，断言退出码和输出。
- **把契约检查接进 `make check`**：放在 import-linter 和 pytest 之间，步骤行改成 `[1/6]`…`[6/6]`，删掉 Makefile 里"派工 B 再接上"的那条注释。契约检查在 `src/rdp` 和 `scripts` 上必须是 0 个问题，包括脚本自己。
- **负责人决定 G3**：在 `[tool.basedpyright]` 里加 `failOnWarnings = true`，让 warning 也让 basedpyright 那一步失败，旁边用中文注释写理由。`make check` 保持全绿。
- G1、G2 已采纳，照现在的契约做：入口层两个包互不 import；问题总数按有问题的定义计；显式传入的软链接路径退出 2，目录里的软链接不跟随。
- 实现以后，验收第 7 条要能成立：公开函数缺 `Time Semantics:`、私有函数没有 docstring、`@dataclass` 没有 `Attributes:`、小节顺序颠倒、某一项为空，这五种都要输出 `文件:行号  函数全名  缺了哪几项（或哪项为空、顺序不对）`；没有问题退出 0，有问题 1，传入不存在的路径 2。Claude 会在探针工作目录里逐个试。
- 环境照旧：一律调用 `.venv/bin/<工具>`；沙箱写不了 `.git`；ruff 0.17.1 的默认输出写规则名（例如 `print:`），不写规则码。
- 上一轮你在 `/tmp` 下留了 `rdp-a2-*` 这几个试验文件，删掉；这一轮的临时试验用 `tempfile` 或 `tmp_path`，用完不留，工作目录里也不留试验文件。

边界：
- 只改 `src/`、`tests/`。本票允许改的受保护文件：`pyproject.toml`（只写 `[tool.*]` 表，依赖表由 Claude 用 `uv add` 写）、`Makefile`、`scripts/check_contracts.py`（`scripts/` 下只有这一个文件）、`.githooks/pre-commit`（保持可执行位）、`.gitignore`（只追加检查链产生的缓存目录）。`uv.lock` 不改。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。
- 沙箱不能联网，不要尝试安装任何东西。需要新依赖时停下，在最终回复里写依赖申请（AGENTS.md 规则 7）。

最终回复分四块：
1. 改动清单：每个文件一行，写做了什么。
2. `make check`：最后一次运行的命令和末尾输出，原样贴出（含每一步的步骤行、basedpyright 和契约检查的输出、pytest 的汇总行）。再原样贴出跑之前和跑之后的 `git status --porcelain --untracked-files=all`。
3. 契约变更申请、依赖申请：没有就写"无"。
4. 拿不准、需要评审决定的地方。
