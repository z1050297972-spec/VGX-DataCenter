# 机器人侧转发程序 viz_relay（R1 Lite）

Status: ready-for-agent

分级：直做。负责人 2026-11-10："4.5还在做，请你开始03"。执行线把地图里的第 03 张拆成两张并行：本票只做**在机器人上运行的转发程序本身**；平台怎么把它装到机器人上、怎么开启和停止，是第 09 张。两张之间的约定（配置格式、命令行、输出协议）写在本票"约定"一节，第 09 张照此生成和调用。合并前要负责人说"合并"。

**本票不连接任何真实机器人，也不在机器人上安装任何东西。** 测试只用本机的假对象。真机演练等第 09 张做完、负责人在场时再做。

## 依据

- M5 地图 `.scratch/m5-live-preview/map.md`：D6（relay 范围）、D6 补充（通道约定、负责人对第 03 张的要求）、D10。
- 调研 `docs/research/M5-预览组件选型.md`：B4–B7（Foxglove SDK、rclpy 原始字节订阅）、推荐做法 (ii)（一个 rclpy 进程直接用 SDK）、末节"头部 H.264 不显示的原因"和"对真机 relay 的要求"四条。
- 环境事实 `docs/brief/0014-环境事实更新-R1Lite预览环境.md`：Python 3.10.12、rollout 时满负载、头部 H.264 帧结构、相机话题、关节单位。
- 离线原型（只读参考，不合并）：`/home/shawn/桌面/robot-data-platform.wt/m5-offline-preview/prototype/m5-offline-preview/replay.py`。它的 SPS 修正、CompressedVideo 换外壳、`has_sinks()` 判断已经用 Lichtblick 1.30.0 实测过。
- 第 04 张的通道约定：`src/rdp/collection/preview_channels.json`。

## 约定（第 09 张照此调用，改动要两张一起改）

**放哪里**：`src/rdp/robot_side/viz_relay/`，是一个独立的 Python 包。第 09 张把这个目录里的 `*.py` 原样拷到机器人上，在机器人上用 `python -m viz_relay` 运行（包名就是 `viz_relay`）。所以：

- 只用相对导入（`from . import x`），**不导入 `rdp` 的任何模块**；
- 只依赖标准库、`rclpy`、ROS 标准消息包（`sensor_msgs`）和 `foxglove-sdk` 0.30.3；
- 必须能在 **Python 3.10** 上运行。不能用 3.11 以后才有的语法和标准库（例如 `tomllib`、`typing.override`、`typing.Self`、`datetime.UTC`、`ExceptionGroup`、`type X = ...`、PEP 695 泛型）。

**命令行**：

- `python -m viz_relay --config <配置文件>`：运行。
  - 启动成功（WebSocket 服务器已在监听、ROS 节点已建好）后，向标准输出打印一行 `RDP_VIZ_READY port=<端口>`。
  - 启动失败时打印一行 `RDP_VIZ_ERROR <代码> <一句中文说明>`，退出码 2。代码限于 `config_invalid`、`import_failed`、`port_in_use`、`ros_init_failed`。
  - 收到 SIGTERM 或 SIGINT 后在 3 秒内停掉服务器、销毁节点、退出码 0。
- `python -m viz_relay --self-test --config <配置文件>`：只校验配置，并导入 `foxglove`、`rclpy`、`sensor_msgs.msg`。**不建 ROS 节点，不开端口**。成功时打印 `RDP_VIZ_SELFTEST ok`、退出码 0；失败时同上打印 `RDP_VIZ_ERROR …`、退出码 2。
- 运行时只写标准输出和标准错误（第 09 张重定向到日志文件）。ROS 自己的日志目录由环境变量 `ROS_LOG_DIR` 决定，本程序不另写文件。

**配置文件**（JSON，第 09 张按 RobotProfile 生成；本程序只认这个格式，多余的键、缺键、类型不对一律 `config_invalid`）：

```json
{
  "schema_version": 1,
  "profile": "r1lite",
  "profile_version": 3,
  "host": "192.168.0.229",
  "port": 8765,
  "qos_reliability": "best_effort",
  "routes": [
    {"channel": "/viz/camera/head_left",
     "source_topic": "/hdas/camera_head/left_raw/image_raw_color/compressed",
     "source_type": "sensor_msgs/msg/CompressedImage",
     "transform": "h264_to_compressed_video", "max_rate_hz": null},
    {"channel": "/viz/camera/wrist_left",
     "source_topic": "/hdas/camera_wrist_left/color/image_raw/compressed",
     "source_type": "sensor_msgs/msg/CompressedImage",
     "transform": "passthrough", "max_rate_hz": null},
    {"channel": "/viz/joint/left_arm/obs",
     "source_topic": "/hdas/feedback_arm_left",
     "source_type": "sensor_msgs/msg/JointState",
     "transform": "passthrough", "max_rate_hz": 50}
  ]
}
```

- `schema_version` 只能是 1。
- `host` 是 IP 字面量（IPv4 或 IPv6），或者 `"0.0.0.0"`；`port` 取 1024–65535。
- `qos_reliability` 取 `"best_effort"` 或 `"reliable"`。
- `routes` 有 1–64 条，`channel` 不能重复，必须以 `/viz/camera/` 或 `/viz/joint/` 开头。
- `source_type` 只能是 `sensor_msgs/msg/CompressedImage` 或 `sensor_msgs/msg/JointState`。
- `transform`：
  - `"passthrough"`：原始 CDR 字节原样转发；
  - `"h264_to_compressed_video"`：只能用于 CompressedImage。
- `max_rate_hz`：`null` 表示不限；否则取大于 0、不超过 1000 的数。

## 要做的

1. **只读服务器**。用 Foxglove SDK 开 WebSocket 服务器，地址和端口取配置。`capabilities` 给空列表：不开放客户端发布、服务、参数、资源读取。每条路由在启动时登记一个通道：
   - passthrough：`message_encoding="cdr"`，schema 是对应 ROS 消息的 `ros2msg` 定义全文（含 `std_msgs/Header`、`builtin_interfaces/Time` 等依赖），写成常量；
   - h264：用 SDK 自带的 `foxglove.CompressedVideo`。
   - 每个客户端的发送队列有上限（`message_backlog_size`）。Wi-Fi 跟不上时丢旧消息，不能阻塞 ROS 回调，也不能让内存无限涨。
2. **有人看才订阅**。只有通道有订阅者（`has_sinks()`）时才建对应的 ROS 订阅，没人看了就销毁。订阅的创建和销毁只在 rclpy 执行器的线程里做（例如一个每 0.2 秒对账一次的定时器），不在 SDK 的回调线程里直接调 rclpy。订阅用原始字节（`raw=True`），QoS 取配置的可靠性，KEEP_LAST，深度小（相机 2，关节 10）。
3. **头部 H.264 换外壳**（沿用原型）：
   - 自己解析 CompressedImage 的 CDR（只认小端 CDR 封装 `00 01`），取出 header 时间戳、`frame_id`、`format` 和 `data`，不经 rclpy 反序列化。模块注释写明为什么不用现成的：rclpy 反序列化在工作站测不了，而且大数组转成 Python 对象很费时；`mcap-ros2-support` 会给机器人多装一个包。
   - `format` 不是 `h264` 的消息丢弃并计数。
   - 关键帧 SPS 的 `constraint_set5_flag` 清零（`0x0C → 0x08`），其余字节原样。写成纯函数，注释引用调研末节。
   - 发 `CompressedVideo`：`timestamp` 取 header 时间戳，`format="h264"`。同一通道的时间戳必须严格递增，重复或回退的帧丢弃并计数。重新订阅时重置这个比较基准。
4. **限频**：`max_rate_hz` 不为空时，按接收时刻（单调时钟）丢掉间隔小于 `1/max_rate_hz` 的消息。
5. **编解码器字符串自检**：写两个纯函数。一个按 H.264 标准从 SPS 算 `avc1.PPCCLL`；另一个照 Lichtblick 1.30.0 的写法（`constraint_set5_flag << 1`）算。每次订阅后的第一个关键帧，记一行日志写出修正后的编解码器字符串；两种算法结果不一致时记警告。
6. **统计日志**：每 60 秒按通道写一行：收到、转发、因限频丢弃、因时间戳丢弃、因格式丢弃的条数，以及订阅者数。只写标准输出，不写文件。
7. **ROS 这一层要能替换**：rclpy 和 foxglove 的调用集中在少数几个模块里。转发逻辑（解析、换外壳、限频、时间戳判断、按订阅者对账）放在只用标准库的模块里，通过参数传入"订阅源"和"通道"两个接口，测试用假对象驱动。执行线评审后会用录制回放替换 ROS 这一层做端到端验证，所以这个接口要能在不装 rclpy 的机器上使用。
8. **静态检查**：
   - 导入 `rclpy`、`foxglove` 的模块在工作站上解析不到这两个包，basedpyright 会报错。豁免只写在这几个模块的文件开头，逐条列规则名并写理由，不能整文件改成 basic 模式。其余模块照常过严格检查。
   - 新建 `src/rdp/robot_side/viz_relay/ruff.toml`（`extend` 根目录的 `pyproject.toml`，只把 `target-version` 改成 `py310`），让 ruff 不建议 3.11 以后的写法。**本票允许新建这一个配置文件。**
   - 加一个测试：用 `ast.parse(..., feature_version=(3, 10))` 解析包里每个 `.py`；导入只允许标准库（按 `sys.stdlib_module_names`，再排除上面列的 3.11 以后才有的名字）、`rclpy`、`sensor_msgs`、`foxglove` 和包内相对导入。

## 不做

- 在机器人上安装、启动、停止（第 09 张）；按 RobotProfile 生成配置（第 09 张）。
- 腕部 JPEG 降采样或降帧率（负责人：先原样转发实测，超带宽再想办法）。
- 连接检查第 4 层"数据流"（以后另开小票）。
- 往 ROS 发布任何消息、调服务、改参数。

## 允许改的受保护文件

无。新建 `src/rdp/robot_side/viz_relay/ruff.toml` 见要做的第 8 条（不是受保护文件，但它改检查行为，所以写明）。

## 验收

1. **配置**：示例配置能通过；缺键、多键、重复通道、h264 用在 JointState 上、`schema_version` 不是 1 时，都报 `config_invalid`。
2. **头部换外壳**：用测试里构造的 CompressedImage CDR 字节（SPS 前三字节 `64 0C 33`，后跟 PPS 和 IDR）得到的 CompressedVideo：时间戳等于 header，`format == "h264"`，SPS 的约束字节变成 `0x08`，其余字节逐字节相同；两种编解码器字符串算法对修正后的 SPS 都得到 `avc1.640833`，对修正前的 SPS 得到 `avc1.640C33` 和 `avc1.640A33`。
3. **时间戳**：重复或回退的帧被丢弃，计数加一。
4. **限频**：200 Hz 的输入配 `max_rate_hz = 50`，输出不超过 50 Hz。
5. **按订阅者对账**：没有订阅者时一个 ROS 订阅都不建；某通道有了订阅者，下一次对账后建了它的订阅，而且只建它的；订阅者走了以后销毁。
6. **只读**：传给服务器的 `capabilities` 是空列表。
7. **Python 3.10**：上面第 8 条的语法和导入测试通过。
8. 最后一次 `make check` 全绿、0 skipped。

## Comments

- 2026-11-10 开票（执行线），与第 09 张并行。
