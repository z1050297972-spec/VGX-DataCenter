# M5 地图：机器人连接与实时预览

Status: 开图（2026-11-09）。D1–D4 负责人已选（见下），其余按推荐，负责人可以随时改

## 负责人原话

- 2026-11-09："现在我想开始M5"。
- 原始需求 (5)（0001）："通过机器人的ip和用户名连接到机器人，例如ssh ubuntu@192.168.10.2，连接成功后用户可以选择摄像头的topic，把机器人相机画面调出来……类似rqt……如果能看到observation和action曲线最好……实时采集的情况下有没有哪种方法能看到目标、观测的机器人关节信息呢？"

## 目标

在平台网页上，对一台已登记的机器人：

1. **检查连接**：点一下就知道它通不通、软件栈和数据流是否就绪；不就绪时按诊断五段说明原因和下一步。
2. **实时预览**：选相机话题看画面；每个关节组看"目标 vs 观测"两条曲线。
3. **只读**：预览不能往机器人发任何消息、调服务或改参数。

先做 R1 Lite（事实基本齐），AutoLife 等现场补测后再接。录制是 M6，不在本图。

## 已有依据（不重新调研）

- **路线**（`docs/research/实时可视化路线.md`，规划票 06）：机器人侧跑一个自写的 `viz_relay`，把话题规整成 `/viz/*`，经 Foxglove WebSocket 协议发出来。工作站自托管 Lichtblick，嵌进平台页面。Wi-Fi 上只走 TCP，不走 DDS。备选 Rerun。
- **RobotProfile**（ADR 0007）：按型号一份 TOML，关节名/顺序/单位、目标和观测来源、相机编码、时间戳是否可信、怎么加入 ROS 图、就绪条件。草样在 `.scratch/platform-v1/assets/14-robot-profile/`。
- **机器人事实**（0007、0008）：
  - Wi-Fi：工作站到 R1 Lite 实测 47–125 Mbit/s，有 100–400 ms 的延迟尖峰。R1 Lite 头部 H.264 一路 15 Mbit/s，原样转发放得下；三路相机全帧率约 110 Mbit/s，放不下，腕部 JPEG 必须在机器人上降采样。
  - R1 Lite：ROS 2 Humble、Fast DDS 发现服务器；`eth1` 拿到 `10.42.0.238` 才能加入 ROS 图（就绪条件）；订阅一律 BEST_EFFORT；SSH 用户 `nvidia`，**只能密码登录**；厂商 `ehi_gateway`（8000 端口）自带三路相机的网页预览。
  - AutoLife：ROS 2 Jazzy、CycloneDDS **只绑回环**，所以 relay 只能跑在机器人上；关节是 JSON 字符串话题；相机在共享内存里；SSH 用户 `ubuntu`，已有一把别人的公钥。
  - 两台都是 DHCP 地址，会变。
- **M3 机器人登记**：已有地址、SSH 端口、SSH 用户、MAC（最多 8 张网卡）、序列号。
- **ADR 0001**：非 localhost 的浏览器解不了 H.264（WebCodecs 只在 HTTPS 或 localhost 可用）；前端地址一律相对路径，就是为 M5 上 HTTPS 留的。

## 要定的事

### 负责人已选（2026-11-09）

- **D1 只在工作站本机看预览**。浏览器在 `http://localhost` 下能解 H.264，所以 M5 不上 HTTPS（ADR 0001 的待定项就此关闭）。从别的电脑用 `http://<工作站IP>` 打开时，预览页按 `window.isSecureContext` 判断，明确提示"实时预览只能在工作站本机打开 http://localhost:8600"；检查连接等其他功能照常可用。其他选项（Tailscale 的 `tailscale serve`、自签证书）没选，以后要远程看再开票。
- **D2 (a) 加公钥，在用户目录装 relay**。往机器人加一把工作站公钥，relay 装在普通用户目录；不改厂商配置和 DDS XML，不用 sudo，随时能删干净。平台用公钥一键检查连接、启停预览。没选的：只装 relay 不加公钥；机器人上什么都不装（只用厂商 8000 端口的网页）。
- **D3 嵌入 Lichtblick**。自托管，嵌进平台页面。没选 React + antd 自写。
- **D4 先接 R1 Lite**。AutoLife 等现场补测完再接。

### 按推荐走（负责人不提就照此做）

- **D5 连接检查分四层**，逐层停：
  1. 网络：地址能解析，SSH 端口能连上，限时几秒；
  2. 登录：用平台的公钥 SSH 登录成功；
  3. 就绪：逐条跑 RobotProfile 的就绪条件，例如 R1 Lite 持有 `10.42.0.238`；
  4. 数据流：relay 启动后，报告每个预览话题的实测频率，与 RobotProfile 的标称值对照。
  每层失败都按诊断五段报告。结果只显示，不写导航层，不写机器人。
- **D6 relay 的范围**（R1 Lite）：
  - 头部 H.264：只换外壳（`CompressedImage` → `foxglove_msgs/CompressedVideo`），不重编码；
  - 腕部 JPEG：缩到 640×360、15 fps 再发；
  - 关节：目标和观测按 RobotProfile 的关节名和顺序重新发成标准 `JointState`，限到 50 Hz；
  - 只发 `/viz/*`，WebSocket 关掉发布、服务、参数能力，只订阅制；
  - 有人看才转，没人看不占 CPU；断线后自动重连。
  - 代码放平台仓库（例如 `robot/viz_relay/`），按 RobotProfile 版本锁定，走评审。
- **D6 补充：通道约定**（第 04 张定，第 03 张照发）：相机 `/viz/camera/<RobotProfile 相机名>`（H.264 发 `foxglove.CompressedVideo`，JPEG 发 `sensor_msgs/msg/CompressedImage`）；关节 `/viz/joint/<关节组名>/obs`、`/target`（`sensor_msgs/msg/JointState`）；端口 8765。代码里集中在 `src/rdp/collection/preview_channels.json`。头部 H.264 换外壳时要清 SPS 的 constraint_set5（Lichtblick 1.30.0 缺陷，调研文档末节）。
- **D6 补充：负责人对第 03 张的要求**（2026-11-09）：手腕先原样转发 `/compressed` 实测，超带宽再想办法；预览人工开启、人工停止，有按钮，不自动启动；在机器人上只装必要的东西（`~/rdp_viz/`），不用 sudo、不改厂商配置和启动脚本；正式采集时会关预览。
- **D7 RobotProfile 转正**：草样移到平台仓库 `profiles/`，平台读取并校验；机器人登记按型号找到对应的 Profile。补测前不知道的事实标"未知"，预览照样能用，比如单位未知的曲线标"单位未知"。
- **D8 按 MAC 找新地址**：v1 不做。检查失败时提示"地址可能变了，去机器人登记页改地址"。以后要做，再开一张小票（局域网 ARP 表对 MAC）。
- **D10 预览默认画面**（负责人 2026-11-09 同意）：R1 Lite 头部是双目，预览默认只显示头部左目和左右手腕 3 路；右目不进默认布局（需要时在 Lichtblick 里手动加面板）。实现在第 04 张。
- **D9 平台的私钥**：放在状态目录，权限 600，不进仓库、不进备份以外的地方；网页上不显示私钥，只显示公钥和"复制到机器人"的一行命令。

## 先做 spike（规划票 06 的"下一步"）

在 `prototype/m5-r1lite-preview` 分支上做，不合并。负责人在 R1 Lite 旁边：

1. 在 R1 Lite 上跑一个最小 relay：头部 H.264 换外壳，一路腕部降采样，一个关节组；
2. 在工作站本机用 localhost 打开 Lichtblick 连上去（D1）；
3. 实测：端到端延迟（拍屏幕上的时钟对比）、Wi-Fi 上的实际带宽、Jetson 的 CPU 占用、Lichtblick 能不能显示头部 H.264；
4. 顺带核对：机器人能不能联网装 Python 包，不能的话从工作站拷 wheel。

spike 的结果决定 D6 的参数，以及 relay 用 foxglove_bridge 加转发节点，还是直接用 Foxglove SDK 一个进程搞定。

## 拆票草案（HTTPS 按 D1 不做；05 号空着不用）

| 票 | 内容 | 需要负责人在场 |
|---|---|---|
| 01 | RobotProfile 转正、读取与校验（D7） | 否 |
| 02 | 平台密钥与连接检查四层（D5、D9），机器人登记页加"检查连接" | 第一次加公钥时要 |
| 03 | `viz_relay`（R1 Lite）和机器人侧安装、启停脚本（D6） | 演练时要 |
| 04 | 预览页面：自托管 Lichtblick、嵌入、按 RobotProfile 生成布局（D3） | 否 |
| 06 | 演练与文档 | 要 |
| 07 | AutoLife 接入（现场补测之后） | 要 |

## 需要负责人在机器人旁边的事

- 现场补测（规划票 18 的 AutoLife 项；R1 Lite 的两条臂关节名、夹爪单位）；
- spike 上机；
- 第一次往机器人加公钥（D2 选 (a) 时）。

## 不做

- 录制、启动/停止采集（M6）；
- 控制机器人、遥操作，往机器人发任何消息；
- 改厂商配置、DDS XML，用 sudo；
- 按 MAC 自动找地址（v1）；
- NAS、真实下载、真实转换（负责人 2026-11-08 说后面自己做）。
