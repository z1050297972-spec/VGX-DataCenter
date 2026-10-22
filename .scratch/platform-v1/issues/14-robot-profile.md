# RobotProfile 是否共用

Type: grilling
Status: open
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

**完成标准**：以上各项都有结论，并且用两台机器人各写一份 RobotProfile 草样来验证。结论写成 ADR；术语写进 `GLOSSARY.md`。本票加调 `algorithm-engineering`。
