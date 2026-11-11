# 就绪检查加"本机发现服务器上能看到 HDAS 节点"

Status: ready-for-agent

分级：直做。负责人 2026-11-11："可以加上'HDAS'的检查。开两个同时执行，测试成功后合并即可"（与第 10 张并行；评审和测试通过后执行线直接合并）。

**本票不连接任何机器人。** 测试只用本机的假 ssh 和假 `ros2`。

## 为什么

2026-11-10 真机演练（`docs/brief/0014-环境事实更新-R1Lite预览环境.md` 末两节）遇到这样一种状态：

- 厂商栈在 `eth1`（主臂网线）断开时启动，厂商节点没能在本机发现服务器报到，彼此发现不了，原厂采集会录出空数据。
- 现有的三条 error 级就绪条件（11811 在监听、HDAS 进程在、头部相机进程在）**全都通过**，只报一条 eth1 警告；而且警告文字"已在跑的厂商程序照常工作"在这种状态下是错的。
- `eth1` 接通以后，厂商节点几十秒内会自行报到，不一定要重启厂商栈。

能区分这两种状态的，是"用本机发现服务器能不能看到 `/HDAS` 节点"。执行线 2026-11-11 在机器人上只读实测：

- 用厂商 XML 的副本（地址换成 127.0.0.1），执行 `ros2 node list --no-daemon --spin-time 1`：用时 2.2 秒，看到 11 个节点，含 `/HDAS`。
- 不带 `--spin-time`（默认值）时，1.7 秒返回，**一个节点也看不到**。所以必须带 `--spin-time`。

## 要做的

1. **新的检查类型** `ros_node_visible`（`profile_models.py` 的 `ReadinessCondition`）：
   - `value` 是完整节点名，必须匹配 `^/[A-Za-z0-9_/]+$`。
   - 只有写了 `ros.join`（第 09 张）的 RobotProfile 才能用这种检查，校验写在模型里。
2. **检查怎么做**（`_readiness.py`，仍是同一个经标准输入交给 `bash -s` 的脚本）：
   - 只要有 `ros_node_visible` 条件，脚本里就只跑一次 `ros2 node list`，各条件再分别在结果里按整行精确匹配（`grep -Fx`）。
   - 在 `mktemp -d` 建的临时目录里放三样东西：厂商 XML 的副本（把每个 `<address>…</address>` 换成 `ros.join.discovery_address`，和第 09 张同一种做法，能共用就共用）、`ROS_HOME`、`ROS_LOG_DIR`。`trap` 在退出时删掉整个临时目录，**不写 `~/.ros`，也不写临时目录以外的任何地方**。
   - 环境用 `env -i` 起一个干净的，只放：`HOME`、`USER`、`LANG=C.UTF-8`、`PATH=/usr/bin:/bin`；`source <ros.join.setup_script>`；`FASTRTPS_DEFAULT_PROFILES_FILE=<副本>`、`ROS_LOCALHOST_ONLY`、`ROS_DOMAIN_ID`（只在 profile 有值时设）。
   - 命令：`timeout 8 ros2 node list --no-daemon --spin-time 3`。命令失败、超时或 XML 格式不对时，这些条件一律判"不满足"，不当作脚本出错。
   - profile 来的值一律 `shlex.quote`。
3. **时限**：整个就绪检查的 ssh 时限从 10 秒放宽到 20 秒。连接检查和第 09 张的开启预览都在用这个时限。
4. **`profiles/r1lite.toml`**：`version` 改成 4。
   - 在两条 `process_running` 之后加一条：
     `{ check = "ros_node_visible", value = "/HDAS", level = "error", reason = "厂商节点没在本机发现服务器报到：多半是厂商栈在 eth1（主臂网线）断开时启动的，节点之间互相发现不了，这时采集会录出空数据。先接通主臂网线，确认 eth1 有 10.42.0.238；节点一般会在几十秒内自行报到，之后再检查一次；仍然看不到，再执行 robot_startup.sh kill 和 boot.sh（0014）" }`
   - eth1 那条 warning 的 reason 改成：
     `"eth1（主臂网线）断开：主臂没接或没上电。这时启动或重启的厂商节点报到不了，采集会录出空数据；接通后节点一般会自行报到（0008、0014）"`
   - 其他条件不变。

## 不做

- 不自动修复、不重启任何东西。
- 不检查话题有没有数据流（那是第 4 层，以后另开票）。
- AutoLife 不加这条（它没有 `ros.join`）。

## 允许改的受保护文件

无。`profiles/` 不是受保护文件。

## 验收

1. **能看到**：假 `ros2` 输出里有 `/HDAS` 这一整行 → 该条件通过；其余条件都满足时，作业成功。
2. **看不到**：输出里没有 `/HDAS`（例如只有 `/HDAS_bridge`），或者 `ros2` 超时、退出码非零 → 作业失败在第 3 层，下一步是这条的 reason。
3. **不留痕迹**：比较临时 HOME 前后没有变化，脚本建的临时目录在退出后已删除；假 `ros2` 收到的 `ROS_LOG_DIR`、`ROS_HOME` 都在那个临时目录里；`FASTRTPS_DEFAULT_PROFILES_FILE` 指向的副本里地址是 `127.0.0.1`。
4. **校验**：没有 `ros.join` 的 profile 写 `ros_node_visible` → 读取 profile 时报错。
5. 最后一次 `make check` 全绿、0 skipped。

执行线另做（不进 make check）：把生成的就绪脚本经 ssh 交给 R1 Lite 跑一次（只读，只用临时目录），确认真机上这条通过。

## Comments

- 2026-11-11 开票（执行线），与第 10 张并行。
