# 预览页面：自托管 Lichtblick 与按 RobotProfile 生成布局

Status: in-progress

分级：直做。负责人 2026-11-09："同时开第04张预览页面"（与第 08 张并行）；依赖已批准（Lichtblick 1.30.0 网页包）。合并前要负责人说"合并"。

**本票不连接任何真实机器人。** 机器人侧的转发程序是第 03 张；本票只做平台这一侧，测试用假对象。

## 依据

- M5 地图 `.scratch/m5-live-preview/map.md`：D1（只在工作站本机看，不上 HTTPS）、D3（自托管 Lichtblick，嵌进平台页面）、D6、D7。
- 调研 `docs/research/M5-预览组件选型.md`：URL 参数（A7）、子路径托管（A5）、离线与扩展市场（A6）、iframe（A8）、#1376 的规避（A12）、面板与路径写法（A13、A14），以及末尾"头部 H.264 不显示的原因"。
- 离线原型（只读参考，不合并）：`/home/shawn/桌面/robot-data-platform.wt/m5-offline-preview/prototype/m5-offline-preview/` 的 `layout.json`（Lichtblick 1.30.0 能直接读的布局格式，已在截图里验证过）、`README.md`。
- 第 01 张：`src/rdp/collection/profile.py`、`profile_models.py`、`/api/robot-profiles`；第 02 张：机器人登记页的"检查连接"。

## 通道约定（本票定，第 03 张的转发程序照此发）

- 相机：`/viz/camera/<RobotProfile 相机名>`。H.264 相机发 `foxglove.CompressedVideo`，JPEG 相机发 `sensor_msgs/msg/CompressedImage`。
- 关节：`/viz/joint/<关节组名>/obs`、`/viz/joint/<关节组名>/target`，都是 `sensor_msgs/msg/JointState`。只有 `JointState.position` 取法的组画曲线；其他取法（例如底盘的 TwistStamped）本票不画。
- 端口：机器人上转发程序的 WebSocket 端口固定 8765，作为平台常量写在一处，第 03 张共用。
- 代码里在一处集中写明这些通道名和端口（中文注释引用本票）；地图 D6 由执行线合并时补上。

## 要做的

1. **安装 Lichtblick 网页包**（不联网）：
   - 平台代码里固定版本 `1.30.0` 和发布包 `lichtblick-web.tar.gz` 的 sha256 `f73b6bd0b4d2857b7311eb780279494334690e203de43440b54bc75994fd16c6`。
   - 新增运维命令（沿用 `src/rdp/cli.py` 的写法），从**本地**的 tar 包安装：核对 sha256，拒绝绝对路径、`..`、软链接和设备文件等不安全的条目，解到状态目录下的 `lichtblick/1.30.0/`，删掉 `.map` 文件；已经装过同版本就直接返回成功。平台代码不下载任何东西，下载由执行线在部署时做。
2. **托管**：Web 进程把已安装的目录同源挂在 `/lichtblick/`。
   - `.wasm` 用 `application/wasm`；不加 `X-Frame-Options: DENY`。
   - 给 `/lichtblick/` 加 CSP，`connect-src` 只放行本站和 `ws:`，拦掉扩展市场、地图瓦片这些外网请求（调研 A6）。
   - 没装时 `/lichtblick/` 返回 404，诊断说明怎么安装（运维命令一行）。
   - 只有登录账号能访问，和平台其他页面一样。
3. **布局接口**：`GET /api/robots/{robot_id}/preview-layout`，按机器人型号找 RobotProfile，生成 Lichtblick 布局 JSON（格式以原型的 `layout.json` 为准）：
   - 每个相机一个 Image 面板，话题 `/viz/camera/<名>`；
   - 每个 `JointState.position` 取法的关节组一个 Plot 面板，画观测和目标两组线：组有目标时每个关节 `position[i]` 两条（观测、目标），默认只启用 `[0]`，其余可在面板里勾选；没有目标的组只画观测；
   - 关节数取 `joint_count` 或 `joints` 的长度；单位未知时轴标签写"单位未确认"，不冒充 rad。
   - 型号没有 RobotProfile 时返回 404，诊断说明"该型号没有 RobotProfile"。
4. **预览页面** `/robots/<编号>/preview`（只用 antd，沿用现有页面风格）：
   - 页面判断 `window.isSecureContext`。不是安全来源时（例如别的电脑用 `http://<工作站IP>` 打开）不嵌查看器，明确提示"实时预览只能在工作站本机打开：http://localhost:8600"（D1）。
   - 显示机器人名称、地址、RobotProfile 版本，以及预览地址 `ws://<机器人地址>:8765`。
   - "连接"按钮：先在浏览器里试连那个 WebSocket（子协议 `foxglove.sdk.v1`，限时 3 秒）。连上以后再设置 iframe 的 `src`，规避 #1376；连不上就提示"机器人上的预览程序没在运行（第 03 张做好后由平台一键启动）"，不嵌查看器。
   - iframe 地址：`/lichtblick/?openIn=web&ds=foxglove-websocket&ds.url=<ws 地址>&layoutUrl=<本站 origin>/api/robots/<编号>/preview-layout`，参数逐个 URL 编码。
   - 机器人登记页每台机器人加"实时预览"入口；型号没有 RobotProfile 时入口不可用并说明原因。
5. 不做：在机器人上启动或停止转发程序（第 03 张）；头部 H.264 的 SPS 修正（在转发程序里做，第 03 张）；HTTPS（D1）。

## 允许改的受保护文件

无。如果实现中发现必须改受保护文件（例如前端配置），停下来写申请。

## 验收

1. 安装命令：sha256 对不上就拒绝，什么都不写；包里有 `../` 条目就拒绝；正常包装好后 `/lichtblick/index.html` 能访问、`.wasm` 的类型对、响应头没有 `X-Frame-Options`、带 CSP。测试用自己造的小 tar 包，不用真包；sha256 常量通过注入替换。
2. 布局：R1 Lite 的布局有 4 个 Image 面板（四路相机），左右臂、左右夹爪、躯干各一个 Plot 面板，左臂面板里有 `/viz/joint/left_arm/obs.position[0]` 和 `/viz/joint/left_arm/target.position[0]`；底盘不出 Plot 面板。
3. 页面：不是安全来源时只显示提示、没有 iframe；安全来源且（模拟的）WebSocket 连得上时，iframe 的 `src` 等于上面的格式；连不上时没有 iframe、显示提示。
4. 最后一次 `make check` 全绿、0 skipped。

## Comments

- 2026-11-09 开票（执行线），与第 08 张并行。
- 2026-11-09 04:32 派工（执行线）：工作目录 `robot-data-platform.wt/m5-04-preview`，Codex gpt-6-astra high，systemd 单元 `rdp-m5-04`，日志 `~/.cache/rdp-dispatch/m5-04/`；与第 08 张并行。
- 2026-11-09 负责人："我记得只有左右手腕相机和头部rgb，为什么会多出一个呢？"→ 执行线核对录制样本：头部是双目，左目、右目两路都录（52 秒样本各约 1660 帧，各带标定）；厂商网关和 mcap2lerobot 用的是左目。负责人："同意，默认只显示3路"。**范围补充（评审修复轮做）**：
  - RobotProfile 相机加两项事实（可选）：`stereo_eye`（`"left"`/`"right"`）和 `stereo_partner`（另一目的相机名）；R1 Lite 的 head_left、head_right 填上，`version` 与第 08 张一致写 2。
  - 预览布局默认跳过 `stereo_eye = "right"` 的相机，R1 Lite 默认 3 个 Image 面板（head_left、wrist_left、wrist_right）。验收 2 相应改为 3 个 Image 面板，且没有 head_right。
- 2026-11-09 负责人确认看本机真实数据定单位（0014 补充）。**范围补充（评审修复轮一起做）**：`profiles/r1lite.toml` 的手臂和躯干关节组 `unit = "rad"`，夹爪组 `unit = "0-100"`（注释写明哪端张开未核对）；布局的轴标签按单位写，不再写"单位未确认"。
- 2026-11-09 05:18 第一轮交回（约 46 分钟，Codex 全量检查后端 2871、前端 418），运行日志 45 条命令无违规。评审：安装命令先整包预检（只允许普通文件和目录，拒绝绝对路径和 `..`），再用 `filter="data"` 解到临时目录后改名，可靠。**阻塞问题（打回）**：执行线用真包和离线原型实测，`/lichtblick/` 的 CSP 让 Lichtblick 整页空白——内嵌脚本被 `script-src` 拦、消息解码要 `unsafe-eval`、`connect-src 'self' ws:` 拦了内部 `blob:`/`data:` 请求使 Plot 不画（证据：原型 `shots/m5-csp.png`、`csp-a/b/c/none.png`）。放行内嵌脚本哈希、`unsafe-eval`、`connect-src` 加 `blob: data:` 后画面和曲线都正常，外网照样拦。
- 2026-11-09 05:2x 第一轮提交 `b9e79f0`；把 main（第 08 张）合进分支 `ac98468`（生成文件自动合并，重新生成无差异，后端 2874、前端 418）。05:31 修复轮派工（续接同一会话，单元 `rdp-m5-04-fix`）：CSP 阻塞问题 + D10 默认 3 路 + 关节单位。
