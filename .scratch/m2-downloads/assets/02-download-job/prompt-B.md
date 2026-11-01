骨架已获批（负责人预授权，执行线按下面的决定批准），契约提交是 c52221b。动手前重读 /home/shawn/桌面/robot-data-platform/docs/agents/codex-workflow.md 第 7.1 节「历次评审打回过的写法」。

先按下面的评审决定改契约（签名、类型、docstring、测试清单），再逐个实现。这些改动已经批准，不用再申请：

1. **不做本机下载网关**（你第 3 块的契约变更申请不批准，太重）。改成"逐文件预解析 + 定期复探"：
   - 每个文件加入 aria2 之前，worker 用第 01 张的 HTTP 传输（不跟随跳转）请求镜像的 `resolve/<commit>/<path>`，逐跳用 `validate_download_redirect` 校验，最多 `MAX_REDIRECT_HOPS = 5` 跳（具名常量，注明理由）；跳往 `huggingface.co` 及其子域、非 HTTPS、带用户信息的一律拒绝，该文件记失败条目并带诊断"镜像不生效"。最终得到 200/206 的那个 URL 交给 aria2 `addUri`。
   - token 只在请求镜像主机（hf-mirror.com）时带；最终 URL 不是镜像主机时，aria2 不带 Authorization 头。
   - 下载期间每 `MIRROR_RECHECK_INTERVAL_S = 60` 秒复跑一次 `probe_mirror`；失败就停止全部传输（RPC 先停，再按 M0 进程组规则），作业以"网络不满足：镜像不生效"结束，暂存保留。
   - aria2 报某文件失败且像签名过期（403/410，或 aria2 错误码对应的"资源不可用"类），重新预解析这个文件一次，再以 `-c` 续传；仍失败才进 curl 兜底。
   - 把这个方案的残余风险写进 `run_download` 或模块 docstring：预解析和 aria2 真正请求之间存在时间窗，靠定期复探兜底。
2. **curl 兜底**：等 aria2 这一轮全部结束后，对失败的文件逐个串行执行（不和 aria2 同时跑，免得总限速被突破）。不用 `-L`，自己逐跳校验 `Location`（同第 1 条的规则和跳数），`-C -` 续传，`--limit-rate` 用当时生效的总限速，重试次数用 `max_tries`。token 不放命令行（用 `-K -` 从标准输入读配置，或等价做法）。
3. **429**：不做自适应降速。删掉 `concurrency_after_throttling` 及其测试，只靠 aria2 的 `--retry-wait`、`--max-tries`。
4. **校验缓存**：按你第 4 块第 3 条的方案（`.rdp-verified-v1.json`、设备号/inode/mtime_ns/ctime_ns 全匹配才复用、原子替换、不跟随软链接）。
5. **接口**：本票只做调参通道和持久化；HTTP 入口放第 03 张。
6. **表结构**：`download_adjustments` 按你的方案。限速上限 `MAX_DOWNLOAD_LIMIT_BYTES_PER_S = 10 * 1024**3`（10 GiB/s，具名常量，注明"远高于本机网卡，只为让值落在 SQLite INTEGER 内"），参数模型和迁移的 CHECK 一致。
7. **并发上限**：下载类型的并发覆盖大于 1 时，worker 启动时报配置错误（复用现有 resolve_scheduling 一类的校验位置，选最小改动），补一个测试。续跑计数检查点按你第 7 条做并测试。
8. **测试位置**：把 `tests/test_download_job_contract.py` 挪到 `tests/jobs/downloads/test_job.py`，和第 01 张的测试放一起。
9. **worker 装配**：worker 入口把真实的 aria2 进程、RPC、curl、校验器、调参通道装配进 `download_dependencies`，aria2c 路径来自 `jobs.aria2c_path`。

然后按测试清单逐个函数实现，用 $tdd 和 $enterprise-coding：
1. 每次去掉一个测试的跳过，先单独运行它（`.venv/bin/pytest <文件>::<测试名>`），看到它失败，再写实现让它通过。去掉跳过就直接通过的测试，在最终回复里逐个列出并说明原因。
2. 除上面批准的改动外，已获批的签名、类型和 docstring 不改。确实要改时停下，在最终回复里写契约变更申请。
3. 集成测试用本机 aria2c（`shutil.which` 找不到就跳过并写明原因）和只监听 127.0.0.1 的 `http.server`，验证：续传（服务器中途断开后 `-c` 接着下）、sha256 不符被判失败、取消后重新执行跳过已完成文件、跳往 `huggingface.co` 的重定向被拒绝。测试里的本地服务器要在 `finally` 里关掉，aria2 子进程要回收（7.1）。
4. 最后 `make check` 全绿，测试里不留骨架阶段的跳过（集成测试只有找不到 aria2c 时才允许跳过）。

边界：
- 只改 `src/`、`tests/`。本票允许改的受保护文件：`pyproject.toml` 里 import-linter 的合约段（只加不改）；迁移 0013。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。
- 不安装任何东西，不访问外网（集成测试只连 127.0.0.1；评审会查运行日志，出现安装或访问外网的命令整轮打回）。需要新依赖时停下申请。
- 自己在 `/tmp` 或别处建的试验文件，交付前删掉。
- 只在三种情况停下：要加新依赖；要改允许范围以外的受保护文件；要改已有的对外行为。其余拿不准的写进最终回复。
- 只有实际运行到 80 分钟左右还没做完，才停在 `make check` 全绿的位置交检查点；不要开工前预判做不完。
- 机器内存紧张，和另一条线共用：`make check` 只在需要时跑，不要并发跑多份。

最终回复分五块：
1. 改动清单：每个文件一行，写做了什么。
2. `make check`：最后一次运行的命令和末尾输出，原样贴出。
3. 契约变更申请、依赖申请：没有就写"无"。
4. 拿不准、需要评审决定的地方。
5. 先红后绿：每个测试一行，写它第一次运行的结果。
