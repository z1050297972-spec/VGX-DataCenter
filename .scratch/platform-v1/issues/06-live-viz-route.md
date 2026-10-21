# 实时可视化路线

Type: research
Status: resolved

## Question

在平台里实时查看两台机器人的相机画面，以及目标关节和观测关节的曲线，有哪几条技术路线可选？各自的代价是什么？

候选路线：foxglove_bridge + Lichtblick、rerun、web_video_server，以及自写的 ROS 2 → WebSocket → React 前端链路。调研中发现其他可行路线，一并纳入比较。

约束（来源：0002 的 F8、F10；原始需求 (5)）：

- 工作站是 Ubuntu 26.04，装不了 ROS 2 Jazzy。ROS 2 只能跑在机器人上，或者跑在工作站的容器里。
- R1 Lite：标准 `sensor_msgs/JointState`；目标和观测分别在两组话题上。
- AutoLife：关节状态是 `std_msgs/String` 里的 JSON；相机画面在共享内存 `/dev/shm` 里，不一定有 ROS 图像话题。
- 平台前端是 React（负责人的初步意见，见「[交互形态与前端路线](02-interaction-frontend.md)」）。
- 工作站目前只有 Wi-Fi。

每条路线都要回答：

- 机器人上要装什么、要跑什么
- 带宽和延迟的量级
- 能不能在同一张图上显示目标和观测
- 能不能嵌进 React 页面
- 许可证是什么，项目还在不在活跃维护

**完成标准**：每条路线都回答了上面五个问题，每条结论都附出处。结果写到 `docs/research/实时可视化路线.md`；本票 Answer 写要点并链接过去。

## Answer

- **推荐 A'**：机器人侧跑 foxglove_bridge 和一个自写的 rclpy `viz_relay` 节点，把话题规整成 `/viz/*` 下的标准消息（`JointState`、降采样后的 JPEG、`foxglove_msgs/CompressedVideo`）。工作站自托管 Lichtblick（≥ v1.22.0），React 页面用 iframe 加 `?ds=foxglove-websocket&ds.url=…&layoutUrl=…` 嵌入。主要依据：协议是订阅制，只传正在看的话题；话题选择和"目标 vs 观测"多序列曲线都是现成的；全部依赖都是 MIT/MPL-2.0，且都在活跃维护。备选是 Rerun（有官方 React 组件，但 viewer 和 SDK 版本锁死，而且推送全部数据）。
- **桥必须放在机器人上，Wi-Fi 上只走 TCP**。ROS 2 官方文档明确说 DDS 在 Wi-Fi 上会因 IP 分片丢失而卡住，组播发现也不可靠。工作站现在可以原生装 ROS 2 Lyrical（Ubuntu 26.04 是 Tier 1），但跨发行版通信不受官方支持，所以 F10 关于"只能用容器"的表述需要更新，结论不变。
- **R1 Lite 实测（本机 MCAP）**：
  - 头部相机话题是 `CompressedImage`，但 `format="h264"`（1920×1536，GOP 10，没有 B 帧）。web_video_server 和 Lichtblick 都不能直接显示，只换个外壳成 `CompressedVideo` 就能显示。
  - 腕部是质量约 95 以上的 1280×720 JPEG。三路相机全帧率原样转发约 107–112 Mbit/s；缩到 640×360、15 fps 后，每路约 1 Mbit/s。
- **AutoLife**：采集器仓库里已经有一个可选的 SHM→ROS 桥，但它发的是未压缩的 `bgr8`，一路约 663 Mbit/s。状态 JSON 里同时有实测值和目标值。所以 AutoLife 同样需要 relay 来规整数据。
- **还没查实**：Wi-Fi 的实际吞吐和延迟、实时话题是否和录制一致、AutoLife JSON 的频率、机器人 CPU 能否撑住重编码，以及端到端延迟（目前都是推算）。前几项交给 05 票，延迟需要用原型实测。
- 详见 [docs/research/实时可视化路线.md](../../../docs/research/实时可视化路线.md)
