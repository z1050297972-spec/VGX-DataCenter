你在 M1 第 02 张工单「扫描第二段与统计大小」的工作目录 /home/shawn/桌面/robot-data-platform.wt/m1-02-scan-stage2-sizing（git worktree，分支 t/m1-02-scan-stage2-sizing，从 main 开出，第 01 张已经合并）里工作。

这张票**分级是直做**（codex-workflow.md 3.0 第 1 条）：不交骨架，直接先写测试、再实现，用 $tdd 和 $enterprise-coding。每个测试先单独运行，看到红，再实现；第一次就绿的，在最终回复里逐项说明原因。

先用绝对路径读这些：
- 工单 /home/shawn/桌面/robot-data-platform/.scratch/m1-datasets/issues/02-scan-stage2-sizing.md 全文
- AGENTS.md、docs/standards/CODING_STANDARDS.md
- docs/agents/codex-workflow.md 第 3.0 节和第 7.1 节（7.1 是以前被打回过的写法，一开始就避开）
- 工单引用的决策：11 的 Q14、12 的 1A、ADR 0005、0006、`docs/manual/导航层手册.md` 第 8 节
- 第 01 张已经合并的代码：
  - `src/rdp/jobs/datasets/`，第二段的框架在 `_stage.py` 和 `rescan.py`，目前返回 `NOT_RUN`；
  - 存储根的超时访问，M0 第 10 张。
- 第 01 张执行线对真实导航层扫描的结果：/home/shawn/桌面/robot-data-platform/.scratch/m1-datasets/assets/01-nav-read-index-rescan/realscan-findings.txt，以及同目录的 `baseline-*.txt`

**分两段交**
- **第一段**：先做第二段扫描，加上面板第 ③④ 组、`meta/info.json`、离线处理（工单验收第 3、4、5 条），然后停下交检查点，`make check` 要全绿。统计大小的测试先保留跳过。执行线会在沙箱外对真实存储根跑一次只读扫描，结果作为下一段的输入。
- 第二段（下一次派工）：做统计大小（验收第 6 条）。

**交检查点时**，在第 4 块写出你按手册第 8 节和盘点票（`.scratch/platform-v1/issues/01-nav-json-inventory.md`）预计真实数据上 ③④ 组会报出的发现清单。执行线会逐条核对。

边界：
- 只改 `src/`、`tests/`；`pyproject.toml` 只在 ruff、basedpyright 确实需要时改，每条写理由。
- 不 `git add`、不提交。
- **不读不写 `/mnt`**。
- 不联网、不安装，不新增依赖。
- 不碰真实部署（`~/.config/rdp`、`~/.local/share/rdp`、`~/.local/opt/rdp`），不起占用 8600 端口的服务。
- 测试里的存储根一律用临时目录和替换的挂载表。
- 自己建的试验文件交付前删掉。

只有三种情况停下：要加新依赖；要改允许范围以外的受保护文件；要改已合并契约的含义（只加参数或字段的，可以先做，再在第 3 块申请）。

60 分钟内交第一段的检查点。最终回复五块：
1. 改动清单；
2. `make check` 最后一次的 pytest 汇总行和末尾输出；
3. 契约变更申请、依赖申请；
4. 真实数据上预计会报出的 ③④ 组发现，以及拿不准的地方；
5. 先红后绿，每个测试一行。
