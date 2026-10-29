评审第 3 轮（一键脚本这一段，本段第 3/3 轮，也是最后一轮），只有一项阻塞。

第 2 轮修复后，在 `d1fc95e` 上重跑验收 9：真实联网自动装好了 Node 22.23.2、uv 0.13.5、pnpm 11.22.0，校验、自检全部通过。执行线另外用一份事先写好的配置跑了后半段：install、建管理员、健康检查、浏览器全过程、Ctrl+C 退出码 0、重复运行只报告状态（退出码 0），全部通过。

唯一失败在问答生成配置这一步：
```
查询失败：ValueError；挂载点不得重复
挂载快照校验失败
部署停止：配置读取（退出码1）
```
原因：真实机器上有叠加挂载，同一个挂载点挂了两层。这台机器的 `/proc/sys/fs/binfmt_misc` 先挂 `autofs`（source `systemd-1`），上面再挂 `binfmt_misc`。这是 systemd 的标准行为，几乎所有机器都有。`mounted_storage_candidates` 遇到重复的挂载点，就把整份快照拒绝了，所以问答在任何真实机器上都走不下去。

真实快照存在 `/home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/assets/11-ops-entry-systemd/findmnt-real-2026-10-28.json`，共 60 行。执行线把重复的那两行去掉以后验证过：剩下的快照能正常解析，`/`、`/mnt/dataset1`、`/mnt/dataset2` 都可选，UUID 正确。

**修法（执行线按负责人预批定，改 `mounted_storage_candidates` 的契约含义）**
- 不再因为挂载点重复就拒绝整份快照。同一挂载点的所有行都照常展示，但一律标为不可选。
- `unavailable_reason` 增加一个值 `"stacked_mount"`，展示的文字写"叠加挂载，无法确认哪一层可见"。不去猜哪一层在上面。
- 同步更新 docstring 里"重复记录拒绝"那一句，在第 3 块列出原句和新句。
- 其他非法输入仍然整份拒绝：形状不对、超限、字段缺失、ro/rw 矛盾。

**测试**
- 用上面那份真实快照文件，把它复制进测试的 fixture 目录，测试里不要引用 assets 的路径。断言：快照解析成功；binfmt_misc 那两行都标为 `stacked_mount`；三个 ext4 根可选，UUID 和 read_only 与快照一致。
- 再加一个脚本级测试：setup.sh 的问答拿到含叠加挂载的假 findmnt 输出，能走完并生成通过校验的配置。

**要求**
- 先红后绿。
- 只改 `src/rdp/ops/setup_queries.py`、`scripts/setup.sh`（只在需要展示新原因时改）和 `tests/`。
- 最后跑一次 `make check`，0 skipped。
- 边界同前：不 `git add`、不提交、不联网、不安装，不调用真实 `findmnt`、`systemctl`、`loginctl`，不碰真实 `~/.config`、`~/.local`，不碰 `/mnt`。

30 分钟内交付。最终回复五块，第 1、5 块只写本轮。
