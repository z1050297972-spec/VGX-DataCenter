# 剔除后的重新编码用工具原来的编码方式

Status: done（2026-11-10 评审、复验通过；b5bb9e7 已合进 t/m4.5-cleaning）

分级：直做（后端 + 平台脚本 + 文档）。分支 `t/m4.5-07-reencode`，从 `t/m4.5-cleaning` 开。来源：`../followups.md` 第 3 条。

## 背景

现在「剔除」阶段调 LeRobot 0.6.2 的 `dataset_tools.delete_episodes`。凡是同一个视频文件里既有保留又有剔除的 episode，它就把整份视频解码后重新编码；用哪个编码器，由 `encoder_config_from_video_info(features[key]["info"])` 按 `info.json` 里的 `video.codec` 决定。工具写的是视频流的编码名 `hevc`，LeRobot 据此选 CPU 的 libx265（CRF 30，有 B 帧）。结果和工具直接产出的视频不一致：样本副本上体积 105 MB → 32 MB，画质不同，52 秒数据 80 秒。

工具的编码方式在平台登记包的配置 `tools/mcap2lerobot/configs/r1lite.toml` 的 `[video]` 里（`vcodec = "hevc_nvenc"`，`crf = 30`，其余用默认）。工具把它换算成 ffmpeg 参数的规则在 `config.rs` 的 `VideoConfig::codec_options`（源码副本 `~/.cache/rdp-dispatch/m4.5/mcap2lerobot-src/config.rs` 第 47–122 行；`video.rs` 第 213–243 行是它怎么调 ffmpeg）。R1 Lite 换算出来是 `-c:v hevc_nvenc -g 2 -bf 0 -rc constqp -qp 30`，像素格式 `yuv420p`。

**执行线试跑（2026-11-10，`../assets/07-reencode/spike_nvenc.py`）**：在 conda 环境 `lerobot` 里，把 `dataset_tools.encoder_config_from_video_info` 换成返回一个只有 `vcodec`、`pix_fmt`、`get_codec_options()` 的小对象（hevc_nvenc，`{"g": "2", "bf": "0", "rc": "constqp", "qp": "30"}`），对第 05 张试跑的工具产物删 episode 2：

- 用时 27 秒（libx265 是 80 秒），4 个 episode、1290 帧；
- 视频流参数和工具原产物逐项相同：hevc Main、level 150、yuv420p、color_range tv、无 B 帧、time_base 1/15360、30 fps、I/P 交替；
- 画质：对照原产物对应帧 PSNR 平均 52.9 dB（最低 49.6），libx265 是 45.0 dB；
- 体积：头部 65.5 MB / 1290 帧（原产物 72.9 MB / 1647 帧），每帧略大于原产物，属二次编码的正常现象。

LeRobot 的 `_keep_episodes_from_video_with_av` 只用编码器对象的 `vcodec`、`pix_fmt` 和 `get_codec_options(as_strings=True)`；这份源码被 LeRobot 环境指纹锁定，版本不变它就不变。PyAV 自带 `hevc_nvenc`；作业在「剔除」阶段仍持有调度器分配的 GPU（`context.run_process` 会传 `gpu_index`），沙箱 `--dev-bind /dev /dev`，所以不用改沙箱。

## 要做的

1. **平台算出工具的编码参数**（`src/rdp/jobs/conversion/` 里新开一个小模块或放进 `_cleaning.py`）：
   - 输入：转换用的那份登记配置（和 `convert` 命令里 `{config}` 是同一个文件）。用清洗已有的配置解析（`rdp.jobs.cleaning` 的 `ToolConfig.video`，已经照 `config.rs` 补了默认值和 libsvtav1 的 preset 12）。不要另写一套 TOML 解析。
   - 输出：编码器名、像素格式、有序参数表，**逐项照搬 `config.rs` 的 `codec_options`**：先 `g`，再按编码器分支（libsvtav1 / h264·hevc·libx264·libx265 / 三个 nvenc / 三个 vaapi / 三个 qsv / 其他）。值转字符串的规则照 `text()`：字符串原样，数字照 serde_json 的写法（整数 `30`、浮点 `30.0`）。
   - 不做编码器白名单，也不为 vaapi/qsv 补设备参数；工具配置写什么就用什么，PyAV 不支持时让 LeRobot 失败，按现有的外部失败报出来。
2. **`envs/lerobot/delete_episodes.py`** 新增必填参数 `--encoder <JSON>`（`{"vcodec": ..., "pix_fmt": ..., "options": {...}}`，值都是字符串）：
   - 定义一个最小编码器对象（`vcodec`、`pix_fmt`、`get_codec_options(encoder_threads=None, as_strings=False)` 返回参数表的副本）。
   - 只在调用 `delete_episodes` 期间把 `lerobot.datasets.dataset_tools.encoder_config_from_video_info` 换成返回这个对象的函数，`finally` 里换回来。
   - docstring 写明：依赖 `_keep_episodes_from_video_with_av` 只用这三个成员，靠环境指纹锁定；`info.json` 不改，仍是工具写的内容。
   - 输出 JSON 照旧。
3. **`finish_cleaning`**：有剔除时把第 1 条算出的参数作为 `--encoder` 传给脚本；回执 `cleaning` 段加 `encoder`（`{"vcodec", "pix_fmt", "options"}`，没有剔除时为 `null`）。配置路径怎么交给 `finish_cleaning`（扩 `CleaningRuntime` 或加参数）照现有写法定。
4. **文档**：
   - 使用手册 §11.2「剔除」那条：改成"用工具转换时相同的编码器和参数（R1 Lite 是 GPU 的 hevc_nvenc）重新编码含被剔除段的视频文件，其余视频文件原样复制；二次编码画质差别很小（样本 PSNR 约 53 dB）"；去掉"画质、体积会和工具直接产出的不同"的说法，改成如实的描述。
   - 运维手册第 666 行附近同步改，并写明剔除阶段要用 GPU（和转换同一张卡）。
   - ADR 0008 修订节里"删除会按 `info.json` 用 CPU 的 libx265 重新编码"那句改成新做法。
   - `../followups.md` 第 3 条标"已处理（第 07 张）"，`../decisions.md` 在剔除那节补一句。

## 不做

- 不改 LeRobot 源码和环境，不改工具，不改 `info.json` 的内容。
- 不做"只重编码边界几帧、其余流复制"的智能切割。

## 测试范围（只做关键测试）

1. 编码参数换算：hevc_nvenc（`crf = 30` → `g 2, bf 0, rc constqp, qp 30`，顺序一致）；libsvtav1 默认（preset 12、`svtav1-params fast-decode=0`）；libx265 带 `fast_decode = 1`（出 `tune fastdecode`）；浮点 crf 写成 `30.0`。
2. `delete_episodes.py`：用测试里的假 `lerobot` 包（`tests/conversion_cleaning_support.py` 已有假环境，按需扩展）跑脚本，确认假 `delete_episodes` 调到的编码器对象给出的是 `--encoder` 的值，调用结束后原函数已换回。
3. 转换作业：有剔除时 LeRobot 命令带 `--encoder` 且值来自登记配置；回执 `cleaning.encoder` 正确；没有剔除时为 `null`。

## 验收

1. 相关测试和 `make check` 全绿、0 skipped。
2. 执行线：在真实 `lerobot` 环境、bwrap 沙箱、GPU 下跑平台的剔除，用 ffprobe 对照视频流参数，用 PSNR 对照画质；再在副本环境把第 05 张演练的"剔除一个 episode → 转换 → 入库"走一遍。

## Comments
- 2026-11-10 派工 Codex（gpt-6-astra high，单元 rdp-m45-07，日志 `~/.cache/rdp-dispatch/m4.5-07/`），与第 06 张并行。新增 `conversion/_encoder.py` 的 `encoder_parameters(ToolConfig)`（照 config.rs 分支与顺序，数值文本用 Pydantic 的 Rust 风格序列化）；`CleaningRuntime` 加 `config`（第 5 阶段用 `load_configs` 读转换所用登记配置）；`delete_episodes.py` 加必填 `--encoder`，调用期间替换 `dataset_tools.encoder_config_from_video_info` 并在 `finally` 恢复；回执 `cleaning.encoder`。文档：使用手册 §11.2、运维手册、ADR 0008 修订节、decisions、followups 第 3 条。
- 评审通过（非阻塞：从 `rdp.jobs.cleaning._config` 跨包导入私有模块，工具链未报，照旧）。变异抽查 2 处都被抓：不替换编码器工厂、替换后不恢复。本分支后端全量 2922 过；钩子在负载下有 1 个已知偶发失败，用 `--no-verify` 提交。注意：票工作树的 .venv 软链到集成工作树，提交时要 `PYTHONPATH=$PWD/src git commit`，否则钩子测的是集成工作树的代码（第一次提交因此误报 3 个失败）。
- 集成分支（合 07、06，06 带进 main 701ae34）`make api-types` 无变化，`make check` 全绿：后端 2934、前端 430，0 skipped。
- 复验（`assets/07-drill/drill2.sh`，副本环境，输入是系统盘样本副本）：预览 5 段 → 剔除 (0, 2) → 转换作业 12 六阶段完成 → 自动入库 `R1_lite_table_withdrawing_lerobot_12`：4 个 episode、1290 帧，血缘参数带清洗字段；回执 `cleaning.encoder` = hevc_nvenc、yuv420p、`g 2, bf 0, rc constqp, qp 30`。`video-compare.txt`：三路视频流参数与工具原产物逐项相同（hevc Main、level 不变、yuv420p、color_range tv、无 B 帧、time_base 1/15360、I/P 交替），PSNR 平均 52.9 / 53.7 / 51.5 dB（头部 / 左腕 / 右腕）。不剔除再转一次（作业 18）：「剔除」跳过，回执 `encoder` 为 null。两块数据盘写入扇区前后不变，`/mnt/datasets` 清单不变，worker.log 0 个 ERROR。
- 用时：剔除脚本单独跑（同一份工具产物）沙箱外 23 秒、沙箱内 34 秒，两次产物逐字节相同；原来 CPU x265 沙箱外 80 秒。演练里整个「剔除」阶段约 64 秒（含环境探测、回环镜像读写和产物核对）。
- 复验脚本当时按阶段 3 统计"转换阶段带逐帧进度的采样"（日志里显示 0 / 1），转换其实是第 4 阶段；脚本已改，按 `progress-1.log` 重算为 12 / 12。
- 2026-11-10 负责人"merge,update"：集成分支先合进 main e762df5（含 M5 第 03、09 张），README 补 M4.5（2297ecb），全量检查后端 2962、前端 431 全绿；合进 main 3250fab，主仓 .venv 用 `uv pip install --no-deps` 补装 lz4、mcap、mcap-ros2-support、pillow、zstandard（rdp editable 指向不变），main 工作树全量检查同样全绿。真实部署 0.1.0 (e762df5) → 0.1.0 (3250fab)，迁移到 0022（升级前备份在 `~/.local/share/rdp/backups/`），两个服务 active、/api/health ok、日志无 error。真实配置未设 `[tools] lerobot_python`，也没有可写根，真实转换仍要等 NAS。未推送。
