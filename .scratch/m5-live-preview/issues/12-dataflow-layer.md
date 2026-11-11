# 开启预览时检查数据流（连接检查第 4 层）

Status: done

分级：直做。负责人 2026-11-11："开"（问"多个gpt同时执行，30mins，能完成吗"之后），同意执行线推荐的放置位置和判定标准，测试通过后执行线直接合并、升级。**机器人正在跑 rollout：本票不连接任何机器人**，真机实测以后另约。

## 为什么

M5 地图 D5 的第 4 层"数据流"一直没做。前三层只说明"该在的程序在"，不说明"数据真的在流"：例如头部相机进程在但一帧不出、某组关节没有数据。第 11 张的 `/HDAS` 检查挡住了最常见的一种（厂商栈在 eth1 断开时启动），其余要靠人看画面。

转发程序只在有人看某一路时才订阅它，所以不能从正在运行的转发程序读统计。改为给转发程序加一个**探测模式**：只订阅 ROS、不开端口，计数一段时间后输出一行结果就退出。

## 约定（A、B 两路共用，不得改动）

命令行（在机器人上，环境与 `--self-test` 完全相同，由第 09 张的 `_launch` 设置）：

```
python3 -m viz_relay --probe --config <config.json>
```

- `--probe` 与 `--self-test` 互斥（同时给出按 `config_invalid` 处理）。
- 不建 Foxglove 服务器、不开端口、不建输出通道；ROS 节点名 `rdp_viz_probe`（与正在运行的 `rdp_viz_relay` 区分）。
- 对配置里**每条路由**的 `source_topic` 按路由的 `source_type` 和配置的 `qos_reliability` 订阅，回调里只计数，不解码、不转换、不限频（`max_rate_hz` 在探测里忽略：要测的是源话题的原始频率）。
- 时序（单调时钟）：订阅后先 spin **2.0 秒**预热（等发现和匹配，计数丢弃），再计数 **5.0 秒**。常量写在一处并注释引用本票。
- 成功时 stdout 恰好一行，然后退出码 0：

  ```
  RDP_VIZ_PROBE {"window_s": 5.0, "counts": {"/viz/camera/head_left": 149, "/viz/joint/left_arm/obs": 1000, ...}}
  ```

  JSON 用 `json.dumps(..., ensure_ascii=False, sort_keys=True)`，单行；`counts` 的键是路由的 `channel`（不是源话题），每条路由都有键，值是非负整数；`window_s` 是实际计数时长（单调时钟测得，保留 3 位小数）。
- 失败沿用现有协议 `RDP_VIZ_ERROR <code> <说明>`、退出码 2：配置不对 `config_invalid`，导入失败 `import_failed`，ROS 初始化失败 `ros_init_failed`。
- 收到 SIGINT/SIGTERM 时尽快退出（不输出 PROBE 行），回收订阅和节点。
- 不写任何文件（ROS 日志位置由外部 `ROS_LOG_DIR` 决定）。

## A 路：转发程序（`src/rdp/robot_side/viz_relay/`）

1. `__main__.py` 加 `--probe`，按上面的约定实现；计数逻辑放可单测的纯 Python（给它一个假 Source 和假时钟就能测），ROS 部分复用 `_ros.RosSource`（需要时给它加节点名参数，默认值不变）。
2. Python 3.10 兼容（机器人是 3.10.12），只用标准库和已有依赖；遵守本目录 `ruff.toml`。
3. 测试（新文件 `tests/test_viz_relay_probe.py`，不 import rclpy/foxglove，用假对象）：
   - 两条路由、假 Source 在计数窗口内各推若干条、预热期推的不计：输出一行 `RDP_VIZ_PROBE`，JSON 的 `counts` 正确、每条路由都有键（没收到的是 0）；
   - `--probe --self-test` 同时给出：输出 `RDP_VIZ_ERROR config_invalid`，退出码 2。
4. 只改 `src/rdp/robot_side/viz_relay/` 和这个新测试文件。

## B 路：平台（`src/rdp/jobs/robot_connection/`）

1. `_preview_scripts.py`：加 `probe(package_id, profile) -> str`，生成脚本：用和启动同一个包目录的 `config.json`，经 `_launch` 同样的环境 `exec python3 -m viz_relay --probe --config "$config"`（`_launch` 的 `self_test: bool` 可以改成模式参数，三种：服务、自检、探测）；探测进程的标准输出要回到 ssh（只取 `RDP_VIZ_PROBE`/`RDP_VIZ_ERROR` 那一行），标准错误写 `~/rdp_viz/log/probe.log`（覆盖写）。不拿启停锁（探测不碰 pidfile 和端口）。
2. `preview.py` 的 `_start`：在"启动：已开启 / 已在运行"之后加第 6 步"数据流"，ssh 时限 **20 秒**（`PROBE_TIMEOUT_S`）。进度 total 从 5 改成 6，最后的摘要形如
   `网络：通过；登录：通过；就绪：通过；安装：已是最新；启动：已开启；数据流：9 路通过，2 路提示；ws://…:8765`。
3. **判定**（纯函数，输入 RobotProfile、`build_relay_config` 的路由、探测结果，输出每路一条结果；放 `src/rdp/collection/` 或 `robot_connection/` 均可，选更合适的一处）：
   - 每条路由按 channel 对回 RobotProfile 的来源：相机 → `[[camera]]` 的 `rate_hz`；关节 → 该组 observation 或 target 的 `rate_hz`、`may_be_silent`。实测频率 = count / window_s。
   - **观测和相机**：标称未知（`rate_hz` 省略）时有数据算通过、0 条算失败；已知时 ≥ 标称的 50% 通过，> 0 但 < 50% 警告，0 条失败。
   - **目标**：从不判失败。≥ 50% 通过；> 0 但 < 50% 警告；0 条记"提示"（主臂没人操作时目标不发数据，0014 演练实测；Profile 里 `may_be_silent = false` 的目标也一样，这条事实冲突记在 Comments，Profile 不改）。
   - 50% 写成常量，注释引用本票。
4. **结果怎么报**：
   - 每路一行写进作业日志（`context.log`）：`数据流 /viz/camera/head_left 29.8 Hz（标称 30 Hz）通过`，标称未知写"标称未知"。
   - 警告：每路一条 WARNING 诊断（`actual` 写"<channel> 实测 x Hz，标称 y Hz"，`next_step` 写"画面或曲线可能卡顿；检查机器人负载和厂商节点"），作业"带警告成功"。
   - 失败：任一路失败 → 作业失败（`ExternalError`），每个失败路一条 ERROR 诊断（`actual` "<channel> 5 秒内 0 条"，`consequence` "预览程序已开启并保持运行，但这一路没有数据"，`next_step` "先点检查连接看就绪条件；接通主臂网线、确认厂商栈在跑；不需要预览时点停止预览"）。**不停转发程序**。
   - 提示不出诊断，只进日志和摘要的计数。
   - 探测本身出错（`RDP_VIZ_ERROR`、超时、输出不是一行合法 JSON 或键与路由不符）→ 作业带警告成功，一条 WARNING 诊断"数据流检查没做成"，`next_step` "看机器人上 ~/rdp_viz/log/probe.log"；预览照常可用。
5. 测试（新文件 `tests/test_preview_dataflow.py`，复用 `tests/test_preview_start_stop.py` 的假 ssh / 假机器人写法；假机器人上的 `python3 -m viz_relay --probe` 由假程序按测试给定的计数输出 PROBE 行）：
   - 判定纯函数：R1 Lite 真实 Profile + 路由，构造一组计数：一路相机 0 条→失败；一路观测 40%→警告；目标 0 条→提示；其余通过。
   - 开启作业端到端：全部通过 → 成功，摘要含"数据流：…路通过"；有一路观测 0 条 → 作业失败、转发程序没被停（pidfile 还在）；探测输出坏 JSON → 带警告成功。
   - 现有 `tests/test_preview_start_stop.py` 照样通过（需要时给假机器人补探测输出）。
6. 只改 `src/rdp/jobs/robot_connection/`、`src/rdp/collection/`（若判定放这里）和测试；**不改 `src/rdp/robot_side/`**（A 路在改），不改前端。

## 不做

- 前端改动（预览页已经显示进度摘要和诊断）。
- "检查连接"作业里的第 4 层（它不安装转发程序；以后要的话另开小票）。
- 自动重试、自动停止或修复任何东西。

## 验收

1. A 路、B 路各自的测试如上；交叉核对（执行线）：B 路生成的探测脚本调用的命令行与 A 路实现一致；A 路输出的 PROBE 行能被 B 路解析（执行线写一个交叉测试）。
2. 最后一次 `make check` 全绿、0 skipped。

## Comments

- 2026-11-11 开票（执行线）。两个 Codex 在同一工作目录并行（A 路 robot_side，B 路平台），文件不重叠。手册（使用手册 12.2/12.3、运维手册 11.10）由执行线同时补。
- 2026-11-11 07:44 两路派工（单元 rdp-m5-12a、rdp-m5-12b，gpt-6-astra medium，日志 `~/.cache/rdp-dispatch/m5-12{a,b}/`）。A 路 08:0x 交回，B 路 08:14 交回；B 路在沙箱里起不了本机 socket，作业端到端测试由执行线在沙箱外重跑通过。
- 评审：A 路探测不导入 foxglove、日志走标准错误、预热后清零；B 路判定纯函数放 `collection/preview_dataflow.py`，探测超时（TimeoutError 属 OSError）、坏输出都降为警告，失败时不停转发程序。执行线删掉了 B 路误加进机器人安装脚本内嵌 Python 的一行 `from typing import Literal`。执行线补交叉测试 `tests/test_preview_dataflow_cross.py`（真实 R1 Lite 配置 → A 路入口输出 → B 路判定，四种结论都出现）。变异抽查 3 处都被抓到：目标静默判失败、预热不清零、数据流失败不报错。
- **事实冲突**（不改 Profile）：r1lite 的手臂、右夹爪、躯干目标写着 `may_be_silent = false`，但 0014 演练实测无人操作主臂时目标 0 条；本票按"目标从不判失败"处理。
- **待真机核对的风险**：探测循环每次 `spin_once` 只处理一个回调，R1 Lite 十来路 200 Hz 关节加相机合计每秒两千多条，Python 可能数不全，表现为关节观测"警告"（不会误判失败）。真机实测时看作业日志里各路的实测 Hz；数不全就改成一次 spin 处理全部就绪回调，或把关节标称改用实测上限。
- 机器人在跑 rollout，本票没有真机实测。
