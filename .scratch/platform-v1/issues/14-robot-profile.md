# RobotProfile 是否共用

Type: grilling
Status: resolved
Blocked by: 05, 06, 07

## Question

要不要引入一份按机器人型号描述的 RobotProfile，让实时预览、录制、格式转换三处共用（0003 第六节 (5)）？RobotProfile 里写话题、关节名及顺序、相机、同步参考和单位。

依据三张前置票：「[两台机器人的事实](05-robot-facts.md)」「[实时可视化路线](06-live-viz-route.md)」「[平台统一的 LeRobot 版本](07-lerobot-version.md)」。

要定的：

- **预览要不要关节映射**：推荐路线在机器人上跑一个 `viz_relay`，把各型号的话题规整成 `/viz/*` 下的标准 `JointState`，目标和观测分开。这个 relay 本身就是一份按型号的映射。它应该读 RobotProfile，还是自己再维护一份映射？
- **和 mcap2lerobot 配置的关系**：mcap2lerobot 已有 `configs/r1lite.toml`。是直接复用它的格式，还是平台自有一套、再由它生成工具配置。
- **目标和观测怎么成对表示**：R1 Lite 的目标和观测分属两组话题；AutoLife 的两者在同一份 JSON 里。
- **存放方式**：放在文件里（和工具清单一样，以清单为事实来源），还是放在数据库里。
- **怎么加入机器人的 ROS 图要不要也写进去**：两台机器人的做法完全不同。R1 Lite 是 Fast DDS 的发现服务器加 SUPER_CLIENT 配置；AutoLife 是 CycloneDDS，只绑回环。平台在机器人上跑的节点（例如 `viz_relay`）必须用对应的配置才能看到话题（0007）。
  - R1 Lite 已在 104 上实测（0008）：用节点原样的环境就能加入，前提是机器人持有 `10.42.0.238`，这个地址由有线连接的主臂电脑分配；主臂读数和手柄节点跑在那台电脑上，时间戳不可信；订阅要用 BEST_EFFORT；HDAS 反馈的 `JointState` 里 `name` 只有一项（如 `left_arm`），和 6 个位置对不上，关节顺序只能由 RobotProfile 给出。

补充（来自「[核心领域模型与术语](13-domain-model.md)」）：
- **RobotProfile 挂在机器人型号上**：每台机器人属于一个型号，RobotProfile 按型号来写。同一型号的两台机器人配置不一样时怎么办（例如换了夹爪），由本票定。
- **型号标签**：型号上会写明它对应哪些型号标签，例如 R1 Lite 对应 `galaxea_r1lite` 和 `r1lite`。RobotProfile 要不要用到这个对应关系，例如转换时写进 LeRobot 的 `robot_type`，由本票定。
- **端口的分工**：机器人登记里只记 SSH 端口。预览、录制要用的其他端口，例如 foxglove_bridge 的端口、厂商 `ehi_gateway` 的 8000，放在哪里由本票和 M5 定。

**完成标准**：以上各项都有结论，并且用两台机器人各写一份 RobotProfile 草样来验证。结论写成 ADR；术语写进 `GLOSSARY.md`。本票加调 `algorithm-engineering`。

## Answer

2026-10-22 与负责人走了一轮。Q1–Q6 全部采纳推荐（"都同意，按推荐来"），并用两台机器人各写了一份 RobotProfile 草样来验证。按地图的 Notes，本票加载了 algorithm-engineering。

- **决策和取舍**：见 [ADR 0007 RobotProfile 按型号写，预览、录制、转换共用，只写事实](../../../docs/adr/0007-RobotProfile按型号共用且只写事实.md)。
- **术语**：RobotProfile 机器人说明档、关节组、就绪条件，已写进 `GLOSSARY.md`。
- **草样**：[r1lite.toml](../assets/14-robot-profile/r1lite.toml)、[autolife.toml](../assets/14-robot-profile/autolife.toml)。

### 结论

1. **引入 RobotProfile**：按机器人型号写，只写机器人本身的事实。`viz_relay`、录制、转换都从它读，不各自维护映射。
2. **事实和做法分开**：同步基准、容差、切 episode 的规则、帧率、编码，这些归工具配置。v1 不从 RobotProfile 自动生成工具配置，改为核对：工具配置里的话题和关节顺序必须和 RobotProfile 一致，核对在 M4 实现。
3. **目标和观测成对写**：每个关节组写两个来源，共用同一份关节名、顺序和单位。来源 = 话题 + 取法（`JointState.position`，或者 JSON 路径）。没有目标的组明确写"无目标"；空闲时会不发消息的目标话题，标成 `may_be_silent`，不算故障。
4. **存成文件**：每个型号一份 TOML，放在平台仓库，带版本号，修改走评审。数据库里的型号只记用哪一份。录制和转换时，记下用的是哪个版本。
5. **ROS 图和就绪条件**：写明 DDS 实现、发现方式和 QoS。就绪条件在平台节点启动前逐条检查，不满足就当场报错，说明原因。
6. **v1 一个型号一份**：不支持单台机器人覆盖型号的配置，单台机器人特有的值放在机器人登记里。

### 草样验证出来的事

- **格式够用**：两台机器人差别很大的地方，这套格式都写得下：
  - 分开的话题，以及 JSON 路径；
  - 不可信的时间戳；
  - 会长时间不发消息的目标话题；
  - 从共享内存取图的相机。
- **时间语义**：
  - R1 Lite 的目标话题来自主臂电脑，时间戳不可信。
  - AutoLife 的状态消息是 `std_msgs/String`，没有 header，只能用接收时刻。

  转换和预览在对齐时都要考虑这两点。
- **还不知道的事实，草样里标成"待补测"**：
  - R1 Lite：关节名、夹爪单位。
  - AutoLife：关节名、单位、目标话题的字段和频率、头部相机的分辨率和帧率、LeRobot 的 `robot_type`。

  已转给「机器人现场补测」。M5 开工之前要补齐。

### 对其他票的影响（已同步到各票正文）

- 「[工具清单与转换血缘](15-tool-manifest-lineage.md)」：工具配置管做法，RobotProfile 管事实；工具配置要和 RobotProfile 核对；血缘里要记下 RobotProfile 的版本。
- 「[机器人现场补测](18-robot-facts-followup.md)」：补齐草样里标成"待补测"的事实。

## Comments

- 2026-10-22，认领、走票、关票。和 M0 第 1 张工单的执行线并行进行。
