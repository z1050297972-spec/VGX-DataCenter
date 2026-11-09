# 连接检查第 3 层：就绪条件

Status: in-progress

分级：直做（在第 02 张的连接检查作业上加一层，改 RobotProfile 的就绪条件写法）。负责人 2026-11-09："第3层小票可以开"。合并前要负责人说"合并"。

**本票不连接任何真实机器人。** 测试只用本机假对象（假 ssh 程序）；真机演练等负责人点名后再做。

## 依据

- M5 地图 `.scratch/m5-live-preview/map.md` 的 D5（四层检查，第 3 层"就绪"逐条跑 RobotProfile 的就绪条件）。
- 第 02 张：`src/rdp/jobs/robot_connection/`（第 1 层网络、第 2 层登录）；第 01 张：`src/rdp/collection/profile_models.py`、`profiles/*.toml`。
- **新事实** `docs/brief/0014-环境事实更新-R1Lite预览环境.md`：
  - 厂商节点是在 `eth1` 接通时启动、已在本机发现服务器（UDP 11811）报到的；`eth1` 后来断开，它们照常通信。所以 R1 Lite 的就绪条件不能再是"必须持有 `10.42.0.238`"。
  - `eth1` 断开时**重启**厂商栈会录出空数据，这一条要作为**警告**提示，不算失败。
  - 栈在跑的时候再执行 `boot.sh` 什么都不做。

## 要做的

1. **RobotProfile 就绪条件**（`profile_models.py`）：
   - `check` 改为封闭集合，每种都由平台对应一条固定的只读命令，profile 里不能写命令：
     - `address_present`（value：IP）：`ip -br addr` 里有这个地址；
     - `udp_port_listening`（value：端口号）：`ss -Huln` 里有这个端口在监听；
     - `process_running`（value：进程命令行里的一段固定文本）：`pgrep -f` 找得到；
     - `run_on_robot`（无 value）：说明性条件，不检查，结果里显示为"说明"。
   - 新增 `level`：`"error"`（默认）或 `"warning"`。
2. **`profiles/r1lite.toml`**：`version` 改成 2，就绪条件换成下面四条（reason 照写）：
   - `udp_port_listening` `11811`，error："本机发现服务器没在跑：厂商软件栈没启动。先确认主臂网线接通（eth1 有 10.42.0.238），再在机器人上执行 boot.sh（0014）"
   - `process_running` `HDAS/HDAS`，error："手臂驱动 HDAS 没在跑：厂商软件栈没启动或已退出。先确认主臂网线接通，再执行 boot.sh（0014）"
   - `process_running` `signal_camera_node`，error："头部相机节点没在跑：厂商软件栈没启动或已退出。先确认主臂网线接通，再执行 boot.sh（0014）"
   - `address_present` `10.42.0.238`，warning："eth1（主臂网线）断开：已在跑的厂商程序照常工作，但这时重启厂商栈会互相发现不了、录出空数据。重启前先接通主臂（0008、0014）"
   - AutoLife 的 `run_on_robot` 不变。
3. **第 3 层**（连接检查作业）：
   - 第 2 层通过后，按机器人登记的型号找 RobotProfile；没有 Profile 就跳过第 3 层，作业带一条警告"该型号没有 RobotProfile，未检查就绪条件"。
   - 把全部条件拼成**一个**只读脚本，**通过标准输入**交给一次 ssh 执行（远程命令行只有 `bash -s`），每条输出一行机器可读的结果。用标准输入是为了让 `pgrep -f` 的匹配文本不出现在任何进程的命令行里，否则会匹配到执行脚本的那个 shell 自己。
   - profile 里的 value 一律 `shlex.quote`，不能拼成可执行的 shell 片段。ssh 参数沿用第 2 层（平台密钥、平台 known_hosts、BatchMode 等），整体限时 10 秒。
   - 结果：任一 error 级条件不满足 → 作业失败，诊断的下一步就是该条的 reason；只有 warning 级不满足 → 带警告成功，每条一个警告诊断；全部满足 → 成功。说明性条件不影响结果。
   - 进度摘要从两层改成三层（"网络：…；登录：…；就绪：…"），前端照现有方式显示。
4. 不做：第 4 层数据流（第 03 张）；按就绪结果自动修复或重启任何东西。

## 允许改的受保护文件

无。`profiles/` 不是受保护文件。

## 验收

1. 全部 error 级满足、`10.42.0.238` 不在 → 作业"带警告成功"，警告诊断里有 eth1 那条 reason。
2. `HDAS/HDAS` 不在 → 作业失败在第 3 层，下一步是 HDAS 那条 reason。
3. 型号没有 RobotProfile → 第 3 层跳过，作业带警告成功。
4. 安全：profile 的 value 含 `'; touch /tmp/x #` 这类文本时，假 ssh 收到的脚本里它是被引号包住的字面量；远程命令行只有 `bash -s`。
5. 最后一次 `make check` 全绿、0 skipped。

## Comments

- 2026-11-09 开票（执行线）。
- 2026-11-09 04:26 派工（执行线）：工作目录 `robot-data-platform.wt/m5-08-readiness`，Codex gpt-6-astra high，systemd 单元 `rdp-m5-08`，日志 `~/.cache/rdp-dispatch/m5-08/`。
