# 平台一键开启、停止预览：上传安装转发程序、启停作业、按钮

Status: ready-for-agent

分级：直做。负责人 2026-11-10："4.5还在做，请你开始03"。执行线把地图里的第 03 张拆成两张并行：第 03 张是机器人上运行的转发程序本身（`src/rdp/robot_side/viz_relay/`）；本票做平台这一侧，负责把它装到机器人上，并由人工开启和停止。合并前要负责人说"合并"。

**本票不连接任何真实机器人。** 测试只用本机的假 ssh 程序：在临时 HOME 里执行脚本，PATH 里放假命令。真机演练等负责人在 R1 Lite 旁边时再做。

## 依据

- M5 地图 `.scratch/m5-live-preview/map.md`：D2（用户目录装 relay、不用 sudo、不改厂商配置、随时能删干净），D6 补充里负责人对第 03 张的要求：
  - 预览必须人工开启、人工停止，要有按钮，不自动启动；
  - 在机器人上只装必要的东西，"切记不要做多余的事情，否则坏了没办法维修的"；
  - 正式采集时会关预览。
- 第 03 张的"约定"一节：包的位置、命令行、`RDP_VIZ_READY` / `RDP_VIZ_ERROR` / `RDP_VIZ_SELFTEST` 输出协议、配置文件格式。本票照此生成和调用，不改第 03 张的文件。
- 第 02、08 张：`src/rdp/jobs/robot_connection/`（平台密钥、ssh 参数、`_process.run` 有界子进程、第 3 层就绪脚本经标准输入交给 `bash -s`）。
- 第 04 张：`src/rdp/infra/lichtblick.py`、`src/rdp/ops/lichtblick.py`（固定版本和 sha256 的本地安装命令的写法），`src/rdp/collection/preview_channels.json`，`src/web/src/collection/PreviewPage.tsx`。
- 环境事实 0014：
  - 厂商进程都用 `/opt/galaxea/find_server/super_client_profile.xml`，环境里 `ROS_LOCALHOST_ONLY=0`，没有设 `ROS_DOMAIN_ID`；
  - 新起的参与者要用这份 XML 的副本，把 `<address>` 换成 `127.0.0.1`，`eth1` 断开时也能报到；
  - 机器人上 `python3 -m venv` 可用，Python 3.10.12。

## 要做的

### 1. RobotProfile：新起的参与者怎么加入 ROS 图

`profile_models.py` 的 `RosGraph` 加可选的 `join` 小节；`profiles/r1lite.toml` 填上，`version` 改成 3。AutoLife 不填（不填的型号不能开启预览，诊断说明原因）。

```toml
[ros.join]
# 预览转发程序这类新参与者怎么加入 ROS 图（0014）。
setup_script = "/opt/ros/humble/setup.bash"
fastdds_profiles_file = "/opt/galaxea/find_server/super_client_profile.xml"
# 副本里把 <address>…</address> 全部换成它：本机发现服务器监听 0.0.0.0:11811，eth1 断开时也能报到。
discovery_address = "127.0.0.1"
localhost_only = false  # 厂商进程环境 ROS_LOCALHOST_ONLY=0
```

两个路径必须是绝对路径；`discovery_address` 必须是 IP 字面量。转发程序的环境只在 `ros.domain_id` 有值时才设 `ROS_DOMAIN_ID`，与厂商进程一致。

### 2. 按 RobotProfile 生成转发配置

纯函数，输入 RobotProfile 和机器人登记的地址，输出第 03 张格式的配置：

- `host`：登记地址是 IP 字面量就用它，否则用 `"0.0.0.0"`。
- `port` 和通道名取 `preview_channels.json`。
- `qos_reliability` 取 `ros.qos_subscribe`。
- 路由：
  - **每个相机都发**，包括 `head_right`。默认布局不显示它，但用户可以在 Lichtblick 里手动加面板；没人订阅时它不占资源。`encoding = "h264"` 的用 `h264_to_compressed_video`，`"jpeg"` 的用 `passthrough`，都不限频（负责人：先原样转发实测）。
  - **每个 `message_type = "sensor_msgs/msg/JointState"` 的观测和目标来源都发**，通道 `/viz/joint/<组>/obs|target`，`passthrough`，`max_rate_hz = 50`（D6）。其他类型的来源（底盘目标 TwistStamped）跳过。

### 3. 工作站上存放 foxglove-sdk 的机器人用安装包

照第 04 张 `install-lichtblick` 的写法，新增运维命令 `rdp install-viz-relay-wheel <本地 whl 路径>`：

- 平台代码里固定文件名 `foxglove_sdk-0.30.3-cp310-abi3-manylinux_2_28_aarch64.whl`，sha256 固定为 `a36b76e1f57f9e2889732922f7af473c8dd4d2da740efc1cbc5e2acaa6ae7d29`（执行线已核对 PyPI）。
- 核对文件名和 sha256 后，原子地拷到状态目录 `viz_relay/wheels/` 下。对不上就拒绝，什么都不写；已有同一文件就直接返回成功。
- 平台代码不下载任何东西。

### 4. 机器人上的目录（只写这里）

```
~/rdp_viz/
  venv/                   python3 -m venv --system-site-packages（复用系统 rclpy），只装上传的 wheel
  wheels/<固定文件名>      上传后在机器人上再核对一次 sha256
  relay/<包编号>/viz_relay/*.py、config.json   包编号 = 程序文件和配置内容的 sha256 前 16 位
  fastdds_local.xml       每次启动时由厂商 XML 生成的副本（厂商 XML 只读）
  ros_home/、log/ros/     ROS_HOME、ROS_LOG_DIR 指到这里，不写 ~/.ros
  log/relay.log           每次启动时把上一份改名为 relay.log.1
  run/relay.pid、run/lock
```

不写 `~/rdp_viz/` 以外的任何地方：

- 不用 sudo，不改 `~/.bashrc`、crontab、systemd，不碰厂商目录和厂商 XML；
- pip 只装进 venv，带 `--no-index --no-deps`，并设 `PIP_NO_CACHE_DIR=1`、`PIP_DISABLE_PIP_VERSION_CHECK=1`，不写 `~/.cache/pip`。

### 5. 两个作业：`robot_preview_start`、`robot_preview_stop`

参数只有 `robot_id`，和连接检查一样。

- 复用第 02、08 张的平台密钥、ssh 参数、`_process.run`。每次 ssh 的远程命令行都只有 `bash -s`，脚本经标准输入传进去。
- profile 和登记里来的值一律 `shlex.quote`。
- 共用的部分从 `robot_connection` 里提出来，不复制一份。

**开启**（进度摘要例如"网络：通过；登录：通过；就绪：通过；安装：已是最新；启动：已开启"）：

1. 网络、登录、就绪三层照连接检查执行。error 级就绪条件不满足就失败，不上传任何东西；warning 级（eth1）照常继续，作业带警告。
2. 型号没有 `ros.join`、工作站没有 wheel、平台缺转发程序文件，都按诊断五段失败，并给出下一步：
   - 没有 wheel：`rdp install-viz-relay-wheel /本地路径/<文件名>`；
   - 缺转发程序文件：属于程序缺陷。
3. 安装：只上传机器人上缺的东西。
   - wheel 已在、sha256 对上，就不再传；venv 已有、foxglove-sdk 0.30.3 已装，就不再建。
   - 本次的包编号目录不在，才传程序和配置。
   - 机器人上没有 Python 3.10 以上、或 `python3 -m venv` 不可用时，失败并说明原因。
   - 装好以后在机器人上跑一次 `--self-test`（带下面的 ROS 环境）。
4. 启动：
   - 用 `flock` 拿 `run/lock`，最多等 5 秒。
   - 已在运行（pidfile 里的进程活着，且命令行里有 `-m viz_relay` 和本目录下的 `--config`）：返回成功"已在运行"。如果它的包编号和本次不同，作业带警告"先停止再开启才会更新"。
   - pidfile 指向的进程不是我们的：只删 pidfile，不动那个进程。
   - 端口已被别的程序监听：失败，下一步"机器人上 8765 端口被别的程序占用；平台不会去停它，先查是谁在用"。
   - 生成 `fastdds_local.xml`：把每个 `<address>…</address>` 换成 `discovery_address`。换完必须至少有一处，而且不剩别的地址；不满足就失败，说明"厂商 XML 和预期的格式不同"。
   - 用 `setsid nohup` 后台启动。环境用 `env -i` 起一个干净的，只放：`HOME`、`USER`、`LANG=C.UTF-8`、`PATH=/usr/bin:/bin`；`source <setup_script>` 的结果；`FASTRTPS_DEFAULT_PROFILES_FILE=<副本>`、`ROS_LOCALHOST_ONLY`、`ROS_HOME`、`ROS_LOG_DIR`、`PYTHONDONTWRITEBYTECODE=1`、`PYTHONUNBUFFERED=1`。
   - 标准输入接 `/dev/null`，标准输出和标准错误接 `log/relay.log`，保证 ssh 退出时不挂住、进程不被带走。
   - 写 pidfile 后，最多等 20 秒看日志里出现 `RDP_VIZ_READY`：
     - 出现了：成功，结果写预览地址 `ws://<登记地址>:8765`；
     - 进程先退出或超时：失败，诊断写 `RDP_VIZ_ERROR` 的代码，下一步"看机器人上 ~/rdp_viz/log/relay.log"；超时还要把刚起的进程停掉。
   - 清掉 `relay/` 下不是本次、也不是正在运行的旧包目录。
5. 各段限时（单调时钟）：查询 10 秒，上传安装 180 秒，启动 30 秒。取消要能打断。

**停止**（进度摘要例如"网络：通过；登录：通过；停止：已停止"）：

1. 网络、登录照连接检查执行；不跑就绪。
2. `flock` 同上。
   - pidfile 里的进程是我们的：向它的进程组发 SIGTERM，最多等 5 秒，还在就 SIGKILL。然后删 pidfile，结果"已停止"。
   - 不是我们的或已不在：只删 pidfile。
   - 没有 pidfile：结果"本来就没在运行"，作业成功。
3. 连不上机器人时失败，诊断写明"预览程序可能还在机器人上运行"。

### 6. 预览页面（`PreviewPage.tsx`，只用 antd）

- 加"开启预览""停止预览"两个按钮。只在安全来源（D1）下显示。
- **打开页面时不提交任何作业，也不主动连接。**
- 点"开启预览"：提交 `robot_preview_start`，照连接检查的写法显示进度和诊断。成功后自动走一遍现有的"连接"流程（试连 WebSocket，连上再设 iframe）。
- 点"停止预览"：先把 iframe 撤掉，再提交 `robot_preview_stop`，显示结果。
- 页面写明："预览要手动开启和停止，平台不会自动开启。正式采集前请先停止预览。"
- 现有"连接"失败的提示"机器人上的预览程序没在运行（第 03 张做好后由平台一键启动）"改成"机器人上的预览程序没在运行，先点开启预览"。

## 不做

- 第 03 张的文件（`src/rdp/robot_side/viz_relay/`），本票不建也不改。测试用自己造的假程序目录。
- 卸载按钮（D2 的"删干净"由演练文档写一行命令，第 06 张）。
- 连接检查第 4 层"数据流"（以后另开小票）。
- 预览没人看时自动停止（负责人要人工决定启停）。

## 允许改的受保护文件

无。

## 验收

1. **首次开启**（假机器人：临时 HOME，wheel、venv 都没有）：上传 wheel 和程序；机器人侧核对 sha256；venv 带 `--system-site-packages`；pip 带 `--no-index --no-deps`；跑了 `--self-test`；按上面的环境启动；作业成功。比较临时 HOME 前后，**只有 `~/rdp_viz/` 下有变化**。
2. **再次开启**（已在运行，同一个包）：成功"已在运行"，没有起第二个进程，没有再传 wheel。
3. **端口被占用**：失败，下一步是端口那条，没有启动。
4. **error 级就绪条件不满足**：失败在第 3 层，没有上传任何东西。
5. **停止**：
   - 正在运行时停掉，pidfile 删除；
   - pidfile 指向一个无关进程时，那个进程还活着，pidfile 删除；
   - 没在运行时成功"本来就没在运行"。
6. **wheel**：运维命令遇到 sha256 不符就拒绝、什么都不写；工作站没有 wheel 时开启失败，下一步是安装命令。
7. **配置生成**：R1 Lite 得到 15 条路由：
   - 4 路相机：头部左右目用 h264 转换，腕部 passthrough，都不限频；
   - 11 路关节：左右臂、左右夹爪、躯干各有 obs 和 target，加上底盘 obs，全是 passthrough、50 Hz；
   - 没有底盘 target。
   - 登记地址是主机名时，`host` 是 `"0.0.0.0"`。
8. **安全**：远程命令行只有 `bash -s`。profile 里的路径含 `'; touch /tmp/x #` 时，脚本里它是被引号包住的字面量。脚本里没有 `sudo`。
9. **页面**：
   - 打开页面不提交作业；
   - 点开启提交 `robot_preview_start`，成功后走连接流程出现 iframe；
   - 点停止先撤 iframe，再提交 `robot_preview_stop`；
   - 不是安全来源时没有这两个按钮。
10. 最后一次 `make check` 全绿、0 skipped。

## Comments

- 2026-11-10 开票（执行线），与第 03 张并行。两张都合并后，派 Codex 补一个交叉测试：本票生成的 R1 Lite 配置能通过第 03 张的配置校验。
- 2026-11-10 19:11 派工（执行线）：工作目录 `robot-data-platform.wt/m5-09-start-stop`（分支 `t/m5-09-start-stop`），Codex gpt-6-astra high，systemd 单元 `rdp-m5-09`，日志 `~/.cache/rdp-dispatch/m5-09/`；与第 03 张并行。机器人用的 wheel 已下载到 `~/.cache/rdp-m5-offline/wheels/`，sha256 与 PyPI 一致。
