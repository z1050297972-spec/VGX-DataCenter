# 两台机器人的事实

Type: task
Status: open

## Question

现场采集 Galaxea R1 Lite 和 AutoLife（云蝶）两台机器人的事实。0002 的 F8 只来自配置文件和 README，没有在真机上核实过。

这张票需要负责人在机器人旁边（HITL）：agent 给出一份逐条的命令清单，由负责人执行，或授权 agent 只读执行。

要采集的事实：

- **身份**：型号、MAC、序列号（如果有）；局域网 IP、SSH 端口、用户名；是否已经配好 SSH 密钥。
- **话题**：`ros2 topic list -t` 的完整输出；相机话题的编码（raw 还是 compressed）和帧率；关节话题的实际频率。关节话题包括 R1 Lite 的 `/hdas/feedback_*`、`/motion_target/*`，以及 AutoLife 的 JSON 状态话题。
- **AutoLife 相机**：采集器仓库里有一个可选的 `shm_camera_topic_bridge.py`，它发的是未压缩的 `bgr8`。要确认：机器人上有没有在跑它；头部彩色相机的分辨率和帧率。
- **AutoLife 状态话题**：两个 JSON 状态话题的实际频率和单条消息大小。
- **算力与系统**：两台机器人的 CPU、架构、ROS 发行版。这决定 `viz_relay` 能不能在机器人上做图像重编码（见「[实时可视化路线](06-live-viz-route.md)」）。
- **实时话题和录制的关系**：实时发布的话题，和录制下来的话题是否一致，包括话题名、编码和帧率。
- **原厂录制（R1 Lite）**：录制靠什么命令或按钮触发、输出到哪里、是什么格式。
- **自写采集器（AutoLife）**：CB_Autolife_Data_Collector 在机器人上部署在哪里；拿一份实际产出的样本，确认它的 LeRobot 版本（F8 里只是推断）。
- **网络**：工作站和机器人之间的连通方式，以及实测的延迟和吞吐。工作站目前只有 Wi-Fi，网口没插线（F10）。重点判断一件事：实测吞吐够不够把 R1 Lite 头部的 H.264（约 15 Mbit/s）原样转发过来。

**完成标准**：两台机器人的以上各项都有实测值，写成 `docs/brief/000N-环境事实更新-机器人.md`，每条附来源命令；本票 Answer 写要点并链接过去。
