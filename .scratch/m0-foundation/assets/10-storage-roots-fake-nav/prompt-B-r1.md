评审打回第 1 轮。上一轮在你最终 `make check` 期间被执行线一侧的会话中断，没有最终回复；执行线已复跑 `make check` 全绿（pytest 1781、Vitest 243，0 skipped），日志审计干净，快照 `refs/rdp/m0-10/B-cut`。清单 32 份样本的 sha256、字节数、来源路径与 `sources.tsv` 全部对上；变异 10 个全部被抓住；真机核对和浏览器演示都通过（两块盘在线；UUID 改错一位显示"挂错了盘"）。下面这些要在本轮改掉，其余没提到的不要动。

动手前先用绝对路径重读 /home/shawn/桌面/robot-data-platform/docs/agents/codex-workflow.md 第 7.1 节。缺陷类每条先写会失败的测试、单独运行看到红，再改实现（$tdd）。

**缺陷（先红后绿）**

1. `parse_mountinfo` 用 `str.splitlines()` 分行（`src/rdp/infra/storage.py` 约 126 行）。内核在 mountinfo 里只转义空格、制表、换行和反斜杠，`\r`、`\x0c`、`\x85`、U+2028 等会原样出现在挂载点或来源里；`splitlines` 把它们当换行，整张表解析失败（已实测：`ValueError: '-' is not in list`）。后果：任何本地用户挂一个名字里带这类字符的 FUSE/sshfs 或 U 盘，存储根页面 502、所有声明存储根的作业外部失败。只按 `\n` 分行；测试用这几种字符各一条无关挂载，断言登记的根照常在线。
2. 作业开跑前检查等待期间不响应停止和取消（`execution.py` 约 427 行、`jobs/storage.py` 约 65 行）。每个根最多等 `access_timeout_s`（上限 60 秒），声明三个根在默认 10 秒下也能到 30 秒，超过 `WORKER_STOP_TIMEOUT_S` = 30 秒，worker 停止超预算。要求：检查的等待在停止或取消时及时返回（例如让检查接受一个注入的"应该放弃"信号/Event，按短片段等待并检查），停止按 WorkerStoppingError、取消按已取消结束，仍不调用执行函数、不写存储根；迟到线程照旧不覆盖结果。签名只加参数，按契约补充处理，在第 3 块写清。测试：阻塞的访问回调 + 在等待中设置停止/取消，断言在一个远小于超时的上限内返回、结局正确。
3. 挂载根字段未核对（`_check_mount`，mountinfo 第 4 列）。正确的盘挂在别处，再把它的一个子目录 bind 到登记路径时，设备号和类型都对，被报成在线，实际指向错误目录。要求：登记的是整个文件系统，第 4 列必须是 `/`，否则"挂错了盘"；NFS 同理（第 4 列不是 `/` 视为挂错）。测试各一条。
4. 假导航层引用的目录缺失（spec 评审已核实）：`tests/fixtures/nav/samples/nav/按任务/libero_10/子任务.json` 等（两个视图）指向 `{dataset1}/libero_v3/libero_10/meta/episodes`，清单 `directories` 里没有，也不在 libero 的 `retained_missing_paths` 里；真实盘上这个目录存在（执行线已只读核实）。M1 的断链检查会在这里误报。要求：补齐目录；`retained_missing_paths` 现在没有任何代码或测试读取，加一条测试：展开后每个样本 JSON 结构化字段里的占位符路径，要么在假存储根上存在，要么明确列在该数据集的 `retained_missing_paths` 里（且确实不存在）。
5. 截短说明是套话（CODING_STANDARDS 7.4 要每份样本写清截了什么、为什么）：每个数据集的 `truncation`/`explanation` 都写"保留跨盘……alpha已删除转换目录"，libero_10、R1 并没有这些。按数据集如实写：原有多少、留了哪些、为什么、保留了哪些难处理字符和失效引用。
6. 作业开跑前检查的诊断 `actual` 写的是枚举英文值（`not_mounted` 等，`jobs/storage.py` `_refusal(..., result.reason.value)`）。诊断给人看，改成与页面一致的中文（"没挂载""挂错了盘""超时"），只定义一处映射；测试断言诊断文字。

**规范（7.1、编码规范）**

7. `src/web/src/storage/queries.ts` 的 `staleTime: 0`、`gcTime: 0` 写成带单位的具名常量（CODING_STANDARDS 10.3），放在 `api/storage.ts` 的 `STORAGE_REQUEST_TIMEOUT_MS` 旁边，沿用 `jobs/queries.ts` 的写法。
8. `src/rdp/jobs/storage.py`：`isinstance` 之后的 `if checker is None` 永远到不了，删掉；`failure = _refusal(...); raise failure` 直接 `raise`；`check_storage_before_job` 的 Side Effects 写"无"，但它调用的检查会起一个 daemon 线程，补上。
9. `src/rdp/api/storage.py` `configure_storage` 里的依赖校验和 `infra/storage.py` `_validate_inspector` 几乎逐行重复，只保留一处（infra 提供，api 调用）。
10. 验收 7 的静态检查（`tests/test_fake_nav.py` 约 338 行）只认以 `"/mnt/"` 开头的字面量，漏掉单独的 `"/mnt"` 和 `"/" + "mnt"` 这类拼接。加强：测试代码和 fixtures 里出现 `mnt` 作为路径段的写法都报出来（允许的例外只有你写进测试里的白名单，并说明原因）。

边界和交付同前几轮：
- 只改 `src/`、`tests/`。本票允许改的受保护文件：`pyproject.toml`（只在 ruff、basedpyright 需要时调整，每条写理由）。改动留在工作区，不 `git add`、不提交。
- 不安装、不联网；不读 `~/桌面/data_check`、`~/桌面/Data_Collection_System-main`，不碰 `/mnt`；不碰真实 `~/.config/rdp`、`~/.local/share/rdp`；自己建的临时文件交付前删掉。
- 每个文件改完只跑相关测试，最后跑一次 `make check`，pytest 和 Vitest 都不留 skipped。60 分钟内交付；到 50 分钟还没做完，停在 `make check` 全绿处先写最终回复。
- 只有三种情况停下：要加新依赖；要改允许范围外的受保护文件；要改已获批契约的含义（第 2 条只加参数，已预先批准）。

最终回复分五块，覆盖上一轮（prompt-B，回复丢失）和本轮：1 改动清单（每文件一行）；2 `make check` 命令和末尾原样输出，及跑前跑后的 `git status --porcelain --untracked-files=all`；3 契约变更/依赖申请和改了哪些 docstring/TSDoc 的哪几句；4 拿不准的地方（含上一轮生成 fixtures 的脚本去留）；5 先红后绿（本轮每条缺陷的测试第一次运行结果；上一轮按文件汇总，直接通过的说明原因）。
