# 查看器：AV1 视频转码播放、parquet 表格预览

Status: done

分级：直做。

## 依据

- 负责人（2026-10-30，升级到真实部署后）："没办法浏览视频和parquet文件"。
- 执行线查实：
  - 真实数据的视频全是 AV1 编码（libero、aloha、droid、galaxea 抽查都是），很多浏览器（如 Mac 上的 Safari、没有硬件解码的机器）解不了，`<video>` 放不出来。M1.5 第 01 张的演练用的是 Chrome，它能解 AV1，所以当时没暴露。
  - parquet 被查看器归在"此格式不支持在线预览"，这是功能缺口。
- 本机条件：ffmpeg 8.0.1，带 libdav1d 解码、libx264 和 h264_nvenc 编码，支持 `fd:` 协议；两张 RTX 3090。
- 依赖：pyarrow，执行线按负责人授权批准，开工前由执行线 `uv add pyarrow`，单独提交。

## 范围

- **视频转码预览**（只读，仍走 M1.5 第 01 张的路径校验）：
  - 新接口：给定数据集、链接、路径、起点秒数、时长（默认 60 秒，上限 300 秒），返回 H.264 的分片 MP4 流（fragmented MP4，`-movflags frag_keyframe+empty_moov`），浏览器边收边播。
  - 输入**必须用 O_NOATIME 打开的文件描述符**，以 `fd:` 协议交给 ffmpeg（子进程继承这个描述符），不能让 ffmpeg 按路径自己去打开，否则会更新数据盘的 atime。EPERM 时退回普通打开。
  - 有 NVENC 就用 h264_nvenc，否则用 libx264（veryfast）；两者都不可用，或者转码失败时，返回五段诊断。
  - 资源上限：同时最多 2 路转码，再多返回 429 和诊断；客户端断开要杀掉 ffmpeg；单次转码有超时。
  - 用 ffprobe 读时长和编码（同样用 fd: 输入），给前端显示总时长。
  - 前端：
    - 视频预览默认先试原文件直接播放；`<video>` 报错或者探测到浏览器不支持 AV1（`MediaSource.isTypeSupported('video/mp4; codecs="av01..."')` 或 `canPlayType`）时，自动切到转码播放；
    - 提供"起点"滑块和"上一段 / 下一段"按钮，按分段转码；
    - 显示编码、时长，并提示当前是原文件还是转码。
- **parquet 预览**：
  - 新接口：读 parquet 的表结构（列名、类型）、总行数、行组数，以及按 offset/limit 分页的数据行（单页上限 200 行，单元格太长就截断，标明截断）。
  - 用 pyarrow 读，文件对象来自 O_NOATIME 打开的描述符；只读需要的行组。
  - 单个文件超过一个上限（例如 2 GiB）时，只给表结构和行数，不读数据行。
  - 嵌套和二进制列：列表、结构体转成截断的 JSON 文本；二进制列显示长度。
  - 前端：表结构表格，加可分页的数据表格（antd Table），宽表格放在自己的容器里横向滚动。
- 1280×900 下不能出现横向滚动条；控件统一用 antd。

## 验收

1. 测试：
   - fd: 输入确实被使用（断言 ffmpeg 的参数里没有原文件路径）；
   - 转码并发上限、客户端断开后进程被杀、超时；
   - parquet 的表结构、分页、截断、大文件只给表结构；
   - 都用测试里生成的小文件（用 ffmpeg 或 pyarrow 在临时目录里现做），不读 /mnt。
2. 真实演练（执行线）：
   - 对真实的 libero_10 视频，用不支持 AV1 的浏览器配置（让 Chrome 的 canPlayType 返回空，或者直接调转码接口）播放转码流，并跳到第 60% 处；
   - 预览一个真实 parquet，看到表结构和前 200 行；
   - 前后比对两块数据盘的写入扇区数，必须不变。
3. 检查链：make check 全绿、0 skipped，变异抽查。

## Comments

- 2026-10-30 开票（执行线，负责人授权）。派给 Codex gpt-6.1-sol。
- 2026-10-30 20:56 交回（Codex gpt-6.1-sol），日志审计 0 条，Codex 自报 make check 全绿（2627 passed，Vitest 373），变异抽查 2 处被发现（删 pass_fds、放宽大文件阈值）。新增 3 个 GET（video-info、video、parquet），批准。依赖提交两次被高负载下的偶发超时打挂（Vitest 页面用例、test_jobs_processes；当时 Codex 和 M2 线的检查都在跑），负载降下来后第三次通过，提交 `依赖：pyarrow`。**真实演练**（`vp-drill.sh`、`vp-browser-drill.mjs` → `vp-drill-run.log`、`drill/m154-*.png`，直接读真实数据盘，临时状态目录）：video-info 返回 `{codec: av1, duration_s: 2822.6}`；从 60% 处（2560 秒）转码 10 秒，HTTP 200 video/mp4，0.38 秒完成（NVENC），ffprobe 确认 h264 256×256，时长 10.0 秒；parquet 接口返回列名、类型和数据行。浏览器里把 canPlayType 和 MediaSource.isTypeSupported 对 AV1 改成不支持：页面显示"编码：av1 · 总时长：4271.45 秒 · 转码播放 · H.264 · 每段60秒"，播放时 readyState=4，没有错误；点"下一段"后从 start_s=60 接着播；parquet 页显示"总行数：16040 · 行组：1"、列结构和 200 行表格；1280×900 下没有溢出。平台读取期间两块盘写入扇区数不变，/mnt 清单逐字节相同。按负责人授权合并，然后升级真实部署。遗留：高负载下的偶发超时测试需要单独处理（M2 线也碰到了）。
