# 两台机器人的事实

Type: task
Status: resolved

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

## Answer

2026-10-21 现场只读采集，负责人在自己的终端运行脚本、手输密码。明细和每条的来源命令见 [docs/brief/0007-环境事实更新-机器人.md](../../../docs/brief/0007-环境事实更新-机器人.md)；脚本和原始输出见 [assets/05-robot-facts/](../assets/05-robot-facts/)，其中的明文密码已打码。

- **网络**：
  - 日常工作网络是 104，R1 Lite 是 192.168.0.229，AutoLife 是 192.168.0.134，地址由 DHCP 分配，以后可能变。
  - 经 SSH 测的吞吐只能算下限：R1 Lite 在 104 上约 99–125 Mbit/s，在 GBU 上、软件栈运行时约 47–56 Mbit/s；AutoLife 约 138–189 Mbit/s。
  - **头部 H.264（两路共 30 Mbit/s）原样转发够用**；把整份录制流（约 119 Mbit/s）实时拉过来不现实。
  - Wi-Fi 上有 100–400 ms 的延迟尖峰。
  - 工作站的钟比机器人慢 13–22 ms，时区是 `America/Cambridge_Bay`，机器人是 `Asia/Shanghai`。
- **R1 Lite**：
  - 身份和算力：Jetson AGX Orin，L4T R36.3，8 核，29 GiB；有 NVENC，头部相机节点本身就在用 NVENC 编码；ROS 2 Humble + Fast DDS。机器人序列号 RBB60624A002；SSH 用户 `nvidia`，只能用密码登录。
  - 启动和录制：`~/boot.sh` 起 7 个 tmux 会话；手柄触发 `data_collection_node`，产物在 `~/GalaxeaDataset/<日期>_<任务>/<SN>_<时间>_RAW/*.mcap`，每份约 0.9 GB/分钟，录 52 个话题。
  - 相机：头部两路 H.264，每路 15 Mbit/s；腕部是 RealSense D405，原图 BGR8 1280×720 30 fps，只录 `/compressed` 的 JPEG。
  - 频率：录制频率和厂商监控的期望范围一致，关节反馈 200 Hz，相机 30 Hz，夹爪目标 20 Hz。
  - **实时话题没测到**：DDS 配置把发现服务器写死在机器人不持有的 `10.42.0.238`。在 GBU 上节点之间互相不通，厂商监控显示所有话题都是 0 Hz。负责人确认在 104 上一直正常，原因未定，在「[机器人现场补测](18-robot-facts-followup.md)」里复测。
  - **原厂录制默认开着往厂商云（TOS）上传**，目前因为编码错误没传成功。
  - 厂商的 `ehi_gateway`（8000 端口）自带三路相机的 WebRTC 预览和录制控制入口，可供 M5、M6 参考。
- **AutoLife**：
  - 身份和算力：Core Ultra 9 185H，15 GiB 内存，RTX 4090 Laptop；Ubuntu 24.04 + ROS 2 Jazzy；**CycloneDDS 只绑回环**，网络上看不到它的 ROS 图。
  - 关节状态 JSON：99.98 Hz，每条 2.56 KB，约 2.1 Mbit/s；共 23 个自由度（腰腿 4、双臂 7+7、夹爪 1+1、颈 3），每组带 position、speed、torque、temperature、communication_lost。目标话题空闲时没有消息。
  - 相机：**没有图像话题，SHM 图像桥没在运行**；从共享内存缓冲区的大小定不了分辨率。
  - 采集器部署在 `/home/ubuntu/CB_Autolife_Data_Collector`，HEAD `7be8d0cf`（10-18），**还没有正式用过**。
  - lerobot 是 0.6.2，平台锁的是 0.6.1；机器人上没有 LeRobot 样本，v3.0 仍然只是推断。
- **留到「[机器人现场补测](18-robot-facts-followup.md)」**：
  - R1 Lite 在 104 上的实时话题，以及平台节点加入 ROS 图的方式；
  - AutoLife 头部相机的分辨率和帧率；
  - AutoLife 第一次正式采集后的 LeRobot 样本。
- **给后续票的输入**：
  - 「[核心领域模型与术语](13-domain-model.md)」：两台机器人的地址都会变；R1 Lite 有机器人序列号，AutoLife 只有主机名里的编号 310，DMI 序列号没读到。
  - 「[RobotProfile 是否共用](14-robot-profile.md)」：两台机器人的话题和关节清单；两台机器人加入 ROS 图的方式完全不同，R1 Lite 是 Fast DDS 发现服务器，AutoLife 是 CycloneDDS 只绑回环。
