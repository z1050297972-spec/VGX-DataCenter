骨架已获批，契约提交是 `47aed75`（`契约：存储根与假导航层`），内容就是你交的骨架。第 4 块的四点照你的方案：超时 0.1–60 秒；挂载表/UUID 读取失败按 ExternalError、API 502；根名在全部登记后统一核对；样本来源用 `source_path_parts` 记录。工作目录现在是干净的。

动手前先用绝对路径重读：工单 /home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/issues/10-storage-roots-fake-nav.md、/home/shawn/桌面/robot-data-platform/docs/agents/codex-workflow.md 第 7.1 节「历次评审打回过的写法」。

现在按测试清单逐个函数实现，用 $tdd 和 $enterprise-coding：
1. 每次去掉一个测试的跳过，先单独运行它（Python 用 `.venv/bin/pytest tests/<文件>::<测试名>`，前端在 `src/web/` 里用 `node_modules/.bin/vitest run <文件> -t "<标题>"`），看到它失败，再写实现让它通过。去掉跳过就直接通过的测试，在最终回复里逐个列出并说明原因。评审会用变异抽查验证测试能区分对错。
2. 已获批的签名、类型和 docstring 不改。确实要改含义时停下来写进最终回复的契约变更申请；只是措辞、补充说明的，照改并在第 3 块列出。
3. 最后 `make check` 全绿，测试里不留骨架阶段的跳过（pytest 和 Vitest 都没有 skipped）。

要做的：
- 从 /home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/assets/10-storage-roots-fake-nav/samples/ 生成 `tests/fixtures/nav/` 的样本和清单：截短大的（同一数据集三份 JSON、两个视图的副本留同一批记录），绝对路径按路径段整段换成占位符（`/mnt/datasets` 与 `/mnt/dataset1` 前缀重叠，注意），保留难处理的字符；清单里每份样本的原件 sha256 取 `sources.tsv`，截了什么、为什么写清（CODING_STANDARDS 7.4）。生成后的 fixtures 里不能有 `/mnt/` 文本。生成样本用的一次性脚本不留在仓库里（或者留在 tests 下作为可复跑的生成器、写明用途，二选一，写进第 4 块）；测试运行时不读 `.scratch/`。
- 删掉所有骨架期的说法（"骨架""桩""实现阶段""尚未接线""留待""待实现""10 号票"等），只写现在的行为；`第 N 张`作为来源可以保留。交付前在本票改过的文件里搜"骨架""提案""派工""桩""实现阶段""留待""待实现""号票"，不留。前端那条 `no-unused-vars` 豁免实现后移除。
- 线程超时测试：所有等待有上限，测试里阻塞的回调必须能被释放（Event），结束时 join 有上限；不依赖本机挂了哪些盘、不读真实 `/dev/disk/by-uuid`（读真实挂载表的冒烟测试只断言能解析，不断言具体盘）。
- 前端页面用 antd，类型用生成的 OpenAPI 类型；OpenAPI 有变化用 `make api-types`，不手改生成文件。
- 真机核对和浏览器演示由执行线在沙箱外做（验收 2、9），你不用起服务器、不碰 `/mnt`。

为了不超时：每个测试单独先红后绿，每改完一个文件只跑相关测试文件；最后只跑一次 `make check`。预计 80 分钟内做不完时，停在 `make check` 全绿的位置交检查点（已完成的去掉跳过、没做的保留跳过），到 70 分钟还没做完就先写最终回复。第 4 块写清还剩哪些测试。

边界：
- 只改 `src/`、`tests/`。本票允许改的受保护文件：`pyproject.toml`（只在 ruff、basedpyright 需要时调整，每条写理由）。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。样本只读主仓库 assets 里的副本。
- 不安装任何东西，不访问网络（沙箱为了跑测试开了网络权限，但这张票用不到网络；评审会查运行日志，出现安装或联网的命令整轮打回）。需要新依赖时停下，在最终回复里写依赖申请（AGENTS.md 规则 7）。
- 自己在 `/tmp` 或别处建的试验文件，交付前删掉。测试只用临时目录，不碰真实的 `~/.config/rdp`、`~/.local/share/rdp`。

只有三种情况停下：要加新依赖；要改允许范围以外的受保护文件；要改已获批契约的含义。其余拿不准的照你的判断做，列进第 4 块。

最终回复分五块：
1. 改动清单：每个文件一行，写做了什么。
2. `make check`：最后一次运行的命令和末尾输出原样贴出（pytest、Vitest 的 passed、skipped 数目要看得出）；再贴跑之前和跑之后的 `git status --porcelain --untracked-files=all`。
3. 契约变更申请、依赖申请：没有就写"无"。列出改了哪些 docstring/TSDoc 的哪几句。
4. 拿不准、需要评审决定的地方；交检查点时写清还剩什么。
5. 先红后绿：每个测试一行（可以按文件分组），写它第一次运行的结果（失败的原因，或者为什么一开始就通过）。
