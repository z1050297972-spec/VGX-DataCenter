# 机器人现场补测

Type: task
Status: open

## Question

「[两台机器人的事实](05-robot-facts.md)」收尾时留了三个缺口，这张票补上。事实和原始输出见 `docs/brief/0007-环境事实更新-机器人.md`。

这张票需要负责人在机器人旁边（HITL）。探针脚本已经写好，在 `.scratch/platform-v1/assets/05-robot-facts/`，都是只读的。

要补的：

- **R1 Lite 在 104 上的实时话题**：
  - 背景：10-21 在 GBU 上，R1 Lite 的节点之间互相不通，ros2 CLI 用 5 种发现方式都看不到它的节点。它的 DDS 配置把发现服务器写死在 `10.42.0.238:11811`，而机器人在 104 和 GBU 上都没有这个地址。负责人确认在 104 上（例如 10-11）一切正常。
  - 做法：机器人在 104 上开机，执行 `boot.sh`，**中途不切换网络**。先看 rqt 里有没有画面，再跑 `bash collect.sh r1lite nvidia@192.168.0.229 r1lite_ros.sh`。
  - 要得到的结论：
    - 在 104 上节点之间通不通，`rds_ros_monitor` 是否报非 0 频率；
    - 哪一种发现方式能看到节点。这决定了平台以后在机器人上跑的节点（例如 `viz_relay`）要用什么 DDS 环境才能加入 ROS 图；
    - 实时话题的名字、编码、频率和录制是否一致；
    - `data_collection_node` 订阅了哪些话题（`ros2 node info`）。
  - 如果在 104 上也不通，就说明原厂录制在 104 上录出来的可能是空数据。这时先停下来找负责人，是否改机器人上的 XML，由负责人或厂商决定，本票不改机器人。
- **AutoLife 头部相机的分辨率和帧率**：
  - 共享内存缓冲区的大小定不了分辨率。
  - 做法二选一：读采集器仓库里 SHM 读取代码定义的缓冲区头部结构；或者在负责人同意后临时开一次 `shm_camera_topic_bridge.py`，测完就关。开桥会占用约 663 Mbit/s 的本机带宽（0004）。
  - 顺带测一次遥操作时目标话题 `/topic_arm_whole_body_target_joints_position_0_310` 的频率和大小。空闲时它没有消息。
- **AutoLife 的 LeRobot 样本**：用 CB 采集器第一次正式采集之后，读一份产物的 `meta/info.json`，确认 `codebase_version` 是 v3.0。lerobot 版本是 0.6.2，平台锁的是 0.6.1，顺带记下这两个版本写出来的格式有没有差别。

这张票不阻塞「[核心领域模型与术语](13-domain-model.md)」和「[RobotProfile 是否共用](14-robot-profile.md)」。那两张票先按 0007 里根据录制和配置得到的话题清单走。补测如果发现出入，再回去修订。

补充（来自「[核心领域模型与术语](13-domain-model.md)」）：登记机器人时要填序列号。AutoLife 的 DMI 序列号要 root 权限才能读（`/sys/class/dmi/id/product_serial`）。下次在 AutoLife 旁边时，经负责人同意后用 `sudo` 读一次，写进补测文档。

**完成标准**：三项都有实测值，写成新的 `docs/brief/000N-环境事实更新-机器人补测.md`，每条附来源；本票 Answer 写要点并链接过去。

## Comments

- 2026-10-21，R1 Lite 这项已补完。负责人在 104 上开机、执行 `boot.sh`，rqt 有腕部画面，然后跑了 `collect.sh`。事实写在 `docs/brief/0008-环境事实更新-机器人补测.md` 第一批，原始输出在 `.scratch/platform-v1/assets/18-robot-facts-followup/raw/`。
  - 通不通取决于机器人有没有 `10.42.0.238`，也就是 `eth1` 接没接通，跟 Wi-Fi 连哪个网无关。前三次采集 `eth1` 都断着。
  - `eth1` 另一头是主臂自带的电脑：负责人确认主臂有线连接机器人，进程核对也显示主臂读数、手柄、躯干监控 4 个节点不在机器人上。
  - 节点原样的环境就能加入 ROS 图。录制的 52 个话题全部在实时话题里，名字、类型、编码一致。
  - 当场发现左夹爪目标话题没有消息。
  - AutoLife 的两项还没做，本票保持 open。
- 2026-10-21，负责人确认：早上那几次主臂也一直开着、线一直插着，`eth1` 却没有链路，原因待查。写了只读排查脚本 `eth1_probe.sh`，等负责人方便时跑：`bash collect.sh r1lite nvidia@192.168.0.229 eth1_probe.sh`。结果追加到 0008。
- 2026-10-21，`eth1_probe.sh` 跑完（0008 的"eth1 排查"一节）。
  - `eth1` 是载板上的 PCIe 网卡（`igc`）。机器人在早上和晚上之间重启过，本次开机后链路一直没断。上一次开机的日志不落盘，已经丢了，早上断链的原因查不到。
  - 实用做法：开机后先确认 `eth1` 拿到了 `10.42.0.238` 再采集。
  - **R1 Lite 这一项到此完成**，本票只剩 AutoLife 的两项。
- 2026-10-21，顺带核实：PyPI 上 lerobot 的最新版本是 0.6.1，没有 0.6.2（`https://pypi.org/pypi/lerobot/json`）。所以 AutoLife 上的 0.6.2 多半是从源码装的，补 LeRobot 样本时一并确认来源。
