# M2 遗留事项

- m2-02：429 自适应降速没做，只靠 aria2 的 `--retry-wait`。镜像真的限流时再看要不要补（需要先找到可靠的 429 信号）。
- m2-02：重定向拦截靠"预解析 + 每 60 秒复探"，预解析和 aria2 真正请求之间有时间窗。负责人关 VPN 实测时，确认镜像对 LFS 文件的跳转目标域名。
- m2-01：`meta/info.json` 经镜像 `resolve` 时如果被 302，会按"不可用"失败。实测时确认。
- m2-02：续跑靠大小 + 重新算哈希判断跳过，没写校验清单。TB 级数据重新提交时，会重新算一遍哈希（只耗时间，结果不受影响）。
- m2-02：多文件并发时，页面上的速度和进行中字节只取当前轮询到的文件，不是所有活动文件的合计；第 03 张显示时改用 aria2 的 `getGlobalStat`。
- m2-02：如果镜像直接对 `resolve` 返回 200（不跳 CDN），aria2 拿到的就是带 token 的 `resolve` 地址。下载中途有人开了 VPN，aria2 可能跟随 308 去官方站并带上 token；每 60 秒复探能缩小这个时间窗，但关不掉。

## 合并前必做：迁移改号（2026-11-01，M1/M0 线 datasets-e9 通知）

M0 第 13 张带着 `0013_login_wait_attempts`（down_revision 接 `0012_scene_task_index`）先进 main，真实部署会升到 0013。M2 分支上的两条迁移都还没上过 main、也没部署过，合并前整体顺延一号：
- `v0013_download_adjustments` → `v0014_download_adjustments`：revision 改为 `"0014_download_adjustments"`，down_revision 改为 `"0013_login_wait_attempts"`。
- `v0014_download_staging` → `v0015_download_staging`：revision 改为 `"0015_download_staging"`，down_revision 改为 `"0014_download_adjustments"`。
- `tests/test_jobs_migration.py` 等测试里引用的字符串一起改；以后 M2 的新迁移从 0016 起。
- 现在 m2-03 的 Codex 循环（`rdp-m2-03-loop`）还在这个工作目录里跑，不在中途改；等它停下后，rebase 到 main 时一起做，然后重跑 `make check`。

## 合并后必做：通知部署（2026-11-01，负责人决定，datasets-e9 转达）

M2 和前端样式第 02 张都合进 main 后，真实部署统一升级一次，由 datasets-e9 执行。M2 合并后，给 datasets-e9 发消息，写上合并提交号。
- m2-05：入库前检查"有 `meta/info.json` 但缺 `codebase_version`"没有专门测试；"导航层入口已存在"靠 M1 新增数据集在下游兜底。
- m2-05：没做浏览器演练，入库靠全链路集成测试，等负责人关掉 VPN 实测下载 + 入库时一并验证。
- m2-04：GPU 采集用独立的只读 `nvidia-smi` 查询，没有复用 `gpu.py`。
