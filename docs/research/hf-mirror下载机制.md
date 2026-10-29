# hf-mirror 下载机制：M2「开源下载」用什么手段、怎么作为作业来跑

- **调研日期**：2026-10-28（本机时区 −06:00；实测请求的服务器时间是 2026-10-29 03:00 UTC 前后）
- **需求来源**：
  - `docs/brief/0001` 需求 (1)：经 hf-mirror 下载开源数据集和权重，用 aria2，curl 兜底，两者都要能断点续传；需求 (2)：检查 VPN 是否关闭、显示网速。
  - `docs/brief/0003` 第 (1) 条推荐答案：先列出文件、大小和 sha256，做容量预检，aria2 `-c` 续传，失败回退到 `curl -C - --retry`，校验 sha256 后入库；代理显式控制；aria2 跑 RPC 模式。
  - ADR 0005：下载是 worker 作业，恢复方式是"续跑"；取消不清理产物，重新提交接着下。ADR 0008：产物先进暂存区，检查通过才入库。
  - 决策票 07：平台的规范格式是 LeRobot v3.0。
- **对应决策票**：0003 开图草案的 R-01（本图 `map.md` 把它列在 Out of scope，留给 M2 开图时用）。下游是 G-07「下载流程与入库到导航层」。
- **方法**：
  - 一手资料：hf-mirror 首页、hfd.sh 的 gist、huggingface_hub 官方文档和发布说明、Hub 的 Xet 文档、aria2 手册、lerobot v0.6.1 源码。
  - 本机源码：`/home/shawn/miniconda3` 里装的 huggingface_hub 1.30.0、hf-xet 1.6.0（只读，没有安装或升级任何东西）。
  - 实测：对 hf-mirror.com 发了 4 次、对 huggingface.co 发了 10 次只读请求（`/api/...`、HEAD、一次 100 字节的 Range 请求）；PyPI JSON 接口查版本。没有下载大文件，没有改代理设置。
- **标注**：**已核对** = 亲自打开来源或实测，内容一致；**未核对** = 只来自二手说法、用户评论，或者是推论。

## 结论摘要

1. **本机现在用 hf-mirror 等于没用。** 今天经 Clash（出口在日本，`loc=JP`）请求 hf-mirror.com，API 和 `resolve` 都被 **308 重定向回 huggingface.co**；加 `--noproxy '*'` 也一样，因为 TUN 模式照样接管流量。（已核对，实测见 §1.3）
   - 想让镜像真正起作用，得让 hf-mirror.com 走国内直连。这要改 Clash 规则，属于负责人的决定（§6 第 1 条）。
   - 这也说明了 0001 为什么要"检查 VPN 是否关闭"。
2. **推荐方案：自己写一层很薄的编排，下载交给已经装好的 aria2c（RPC 模式），curl 只作单文件兜底。不引入 huggingface_hub。**
   - 文件清单走 Hub 的 HTTP API：先把分支解析成 commit，再按 commit 列文件树，得到每个文件的路径、大小和 sha256。
   - 逐个文件下载 `resolve/<commit>/<path>`，大文件用 aria2 的 `checksum=sha-256=…` 校验，小文件按 git blob 的 sha1 校验。
   - 断点续传、限速（运行中也能改）、进度（`tellStatus`）、取消（`forceRemove` 或 SIGTERM）这几项 aria2 都现成提供，正好对上 ADR 0005"下载续跑"和作业页面显示进度的要求。
   - 只用标准库（urllib、json、hashlib）加现有的 aria2c、curl，**不需要新增 Python 依赖**。
3. **huggingface_hub（`snapshot_download` / `hf download`）不适合当主力。**
   - 从 1.18 起，**进程重启以后不再续传**半截文件：每次下载写一个带随机后缀的临时文件，失败就删掉；只在同一个进程里重试时续传。
   - 没有限速参数。
   - 进度只能通过 tqdm 钩子拿到。
   - 在线程里跑的话取消不了，只能当子进程杀掉。
   - 2.x 换了 HTTP 栈（httpx2），x86_64 上还会强制带上 hf-xet。lerobot 0.6.1 要求 `huggingface-hub<2.0`。
4. **Xet 对镜像下载的影响。**
   - Hub 上 LeRobot 数据集的大文件（parquet、mp4）都已经存在 Xet 里。
   - 普通 HTTP 照样能下：`resolve` 会 302 到 `cdn.hf.co` 的 xet-bridge，支持 Range，实测返回 206。所以 aria2 和 curl 不受影响。
   - 走 hf_xet 时，token 从 `HF_ENDPOINT`（也就是镜像）领取，分块数据却从 token 里给出的 CAS 地址去拉，镜像能不能代理这部分**没有查实**。所以如果用 huggingface_hub 走镜像，应当设 `HF_HUB_DISABLE_XET=1`。
5. **LeRobot v3.0 数据集在 Hub 上的样子。**
   - 文件不多：`meta/` 下 4 类文件、`data/chunk-*/file-*.parquet`，再加每路相机一串 `videos/<key>/chunk-*/file-*.mp4` 分片。
   - 体积几乎全在视频上：aloha_mobile_cabinet 共 1.74 GB，视频占 99%。
   - 只下一部分时，先下 `meta/`（几 MB），再按 episode 元数据反查分片，但最小单位是整个分片。
6. **关键风险**：
   - 镜像是第三方服务，会限流（有用户报 429）。
   - gated 数据集的 HF token 要交给镜像。
   - 本机经代理访问 Hub 时偶发 TLS 握手失败（10 次里有 2 次）。
   - 超过 50 GB 的单个文件（智元的 tar 分卷有 53.5 GB 的）走 xet-bridge 能不能下，没有查实。
   - 暂存目录按作业编号命名的话，重新提交就续不上。

---

## 1. hf-mirror.com 是什么，`HF_ENDPOINT` 怎么起作用

### 1.1 它是什么

- hf-mirror.com 是面向国内用户的 huggingface.co 镜像站，首页给了五种用法：设 `HF_ENDPOINT`、官方 CLI、自家的 `hfd.sh`、只给某个脚本设环境变量、网页下载。（已核对：[hf-mirror 首页](https://hf-mirror.com/)）
- **它不是 Hugging Face 官方的服务**：Hugging Face 的文档里没有提到它，首页上也没写运营方。hfd.sh 的作者是 gist 用户 padeoe。（未核对：运营方是谁、有没有 SLA，都没找到一手说明）
- **镜像不支持登录**。gated 仓库要先在 huggingface.co 上申请权限、创建 token，再把 token 交给下载工具（CLI 的 `--token`，或 hfd 的 `--hf_username --hf_token`）。（已核对：[hf-mirror 首页](https://hf-mirror.com/) 的 gated 说明）
- 首页上的命令**已经过时**：
  - 它还在用 `huggingface-cli download --resume-download …`。
  - `huggingface-cli` 在 huggingface_hub 2.0.0 里已经删除，改名为 `hf`。（已核对：[v2.0.0 发布说明](https://github.com/huggingface/huggingface_hub/releases/tag/v2.0.0)）
  - 本机 1.30.0 的 `hf download --help` 里也没有 `--resume-download` 这个选项。（已核对：本机运行）

### 1.2 `HF_ENDPOINT` 怎么起作用

- huggingface_hub 在 **import 时**读一次 `HF_ENDPOINT`，默认值是 `https://huggingface.co`。所有 API 和 `resolve` 的 URL 都拼在这个地址上：`{ENDPOINT}/{repo_id}/resolve/{revision}/{filename}`。（已核对：本机 `huggingface_hub/constants.py` L67–L70；[环境变量文档](https://huggingface.co/docs/huggingface_hub/package_reference/environment_variables) 写明"All environment variables are read at import time"）
- `HF_ENDPOINT` 所指的主机会被算进 `HF_URL_HOSTS`。huggingface_hub 会跟着重定向去这些主机，并且**把 Authorization 头带过去**；跳到 CDN 时才把认证头去掉。（已核对：本机 `constants.py` L76–L90 的注释"The auth header is forwarded to these hosts: only add trusted ones"；[v2.3.0 `file_download.py`](https://github.com/huggingface/huggingface_hub/blob/v2.3.0/src/huggingface_hub/file_download.py) 里的 `_is_same_or_hub_host`）
  - 所以设了 `HF_ENDPOINT=https://hf-mirror.com` 以后，gated 数据集的 token 会发给镜像站。
- Xet 的 token 刷新地址是 `…/xet-read-token/<rev>`。如果响应里给的是 huggingface.co 的地址，huggingface_hub 会把它**改写成 `HF_ENDPOINT`**。（已核对：本机 `utils/_xet.py` L73–L75）
  - 但分块数据从哪儿拉，由 token 响应里的 CAS 地址决定，见 §3.2。
- 不经过 huggingface_hub 的工具（hfd.sh、aria2、curl）只是把 URL 的主机换成 hf-mirror.com，路径格式和 Hub 一样：`/api/datasets/<id>`、`/api/datasets/<id>/tree/<rev>`、`/datasets/<id>/resolve/<rev>/<path>`。（已核对：[hfd.sh](https://gist.github.com/padeoe/697678ab8e528b85a2a7bddafea1fa4f) 用 `$HF_ENDPOINT/api/...` 和 `$HF_ENDPOINT/.../resolve/$REVISION/$path` 拼 URL）

### 1.3 哪些 API 能用，本机实测结果

| 请求 | hf-mirror.com | huggingface.co |
|---|---|---|
| `GET /api/datasets/lerobot/pusht` | **308** → `https://huggingface.co/api/datasets/lerobot/pusht`，`server: Caddy` | 200，JSON 里有 `sha`、`gated`、`siblings` |
| 同上，加 `--noproxy '*'` | **308**，同上（`remote_ip` 是 TUN 的假地址 `2001:2::9`） | — |
| `HEAD /datasets/lerobot/pusht/resolve/main/meta/info.json` | **308** → huggingface.co 的同一路径 | — |
| `HEAD /`（首页） | 200 | — |

- 出口：`https://www.cloudflare.com/cdn-cgi/trace` 显示 `loc=JP`，有没有 `--noproxy` 都一样。Wi‑Fi 的 IPv6 前缀是 `240c:`，本机在国内，流量被 Clash 送到了日本出口。（已核对：实测）
- **推论**（未核对）：镜像对境外来源的请求一律 308 回官方站。官方文档里没写这条规则，网上也没找到说明。
  - 不管怎样，结论不变：**在现在的 Clash 规则下，设 `HF_ENDPOINT=hf-mirror` 不会经过镜像，实际是经代理直连 huggingface.co**。
  - 能下，因为 huggingface_hub、aria2、curl 都会跟随 308；但享受不到镜像的好处，还多一跳。
- 本机对 huggingface.co 的 10 次请求里，有 2 次报 `TLS connect error: unexpected eof`，重试就好了。下载器必须有重试。（已核对：实测）
- **镜像在国内直连时，xet 下载和 `git clone` 能不能用，本次无法实测**，原因就是上面的 308。留到负责人调整网络后，作为 M2 的第一项实测（§6 第 1 条）。

### 1.4 已知限制（来自 hfd.sh gist 下的评论，属于用户报告，都未核对）

- **429 限流**（2025-10）：作者说是上游收紧了限制，建议带上用户名和 token。
- **大仓库的文件列表被截断**（2025-10）：作者确认是 bug。后来的版本改成按 `Link: rel="next"` 分页遍历 `tree`。
- **xet 文件**：
  - 2025-12，有人报 `cas-bridge.xethub.hf-mirror.com` 的 URL 出现 `Invalid range header`。
  - 2026-01，有人报部分 xet URL 跳到了 `xethub.hf.co`，不经过镜像。
  - 来源都是 [hfd.sh gist 的评论区](https://gist.github.com/padeoe/697678ab8e528b85a2a7bddafea1fa4f)。

---

## 2. 三种下载手段对比

参与对比的是：A = huggingface_hub 的 `snapshot_download` / `hf_hub_download` / `hf download`（本机 1.30.0，最新 2.3.0）；B = `hfd.sh`（aria2c 或 wget）；C = `git clone` 加 git-lfs。另外把推荐方案 D（自写编排 + aria2c RPC，curl 兜底）也放进来对照。

| 项 | A huggingface_hub | B hfd.sh | C git + git-lfs | D 自写编排 + aria2c RPC |
|---|---|---|---|---|
| **断点续传** | 只在同一进程内：`http_get` 遇到连接错误或超时，最多带 Range 续 5 次。**换进程就不续**：临时文件名是 `<etag>.<uuid8>.incomplete`，失败时在 `finally` 里删掉，1.18 起都是这样（PR #4306）。已经完整下完的文件不会重下。xet 路径不再有本地分块缓存（`HF_XET_CHUNK_CACHE_SIZE_BYTES` 已经不起作用）。 | 能。aria2c `-c` 加 `.aria2` 控制文件，wget 用 `-c`。每次运行按清单比对本地文件大小，缺的或大小不对的才重下。 | 未核对。git-lfs 大文件的续传行为没有查一手资料。clone 本身中断后要从头来。 | 能。aria2 `-c` 加 `.aria2` 控制文件；curl 用 `-C -`。 |
| **并发** | `max_workers=8`，按文件并发；xet 是自适应并发（默认 1–64 路）。 | `-j` 同时下几个文件（1–10，默认 5），`-x` 每个文件几条连接（1–10，默认 4）。 | git-lfs 有并发传输设置（未核对细节）。 | `max-concurrent-downloads`、`-x/-s` 自己定。 |
| **限速** | **没有限速参数**。xet 只能固定并发（`HF_XET_FIXED_DOWNLOAD_CONCURRENCY`），不是带宽上限。 | 脚本没有暴露限速选项。 | 没有直接的限速选项（未核对）。 | `--max-overall-download-limit`；运行中可以用 `aria2.changeGlobalOption` 改。curl 用 `--limit-rate`。 |
| **进度** | 只能传 `tqdm_class`，`snapshot_download` 把各文件的进度汇总进一个父进度条；xet 有两条字节计数（网络字节和写盘字节）。不在同一个进程里，就只能解析 stderr。 | 调 aria2c 时用了 `--quiet=true`，输出重定向到 `/dev/null`，平台拿不到逐字节的进度。 | git 和 git-lfs 的进度打在 stderr 上，给人看的，不适合程序解析。 | `aria2.tellStatus` 给出 `completedLength`、`totalLength`、`downloadSpeed`、`status`；`getGlobalStat` 给出总速度。 |
| **校验** | 只校验**大小**（`Consistency check failed`），下载后**不算 sha256**。<br>`local_dir` 模式下，本地已有文件但缺元数据时，会算一次 sha256 来判断要不要重下。<br>要完整校验，另跑 `hf cache verify --local-dir`。 | **只比大小**，不校验 sha256。 | git 对象有 sha1，LFS 对象按 sha256 命名，git-lfs 会校验（未核对细节）。 | aria2 支持 `checksum=sha-256=<lfs.oid>`（本机 `aria2c -v` 的 Hash Algorithms 里有 sha-256）；非 LFS 小文件用 hashlib 算 git blob sha1，对 `tree` 里的 `oid`。 |
| **xet** | 默认走 hf_xet（2.x 在 x86_64 上是必装依赖）；可以用 `HF_HUB_DISABLE_XET=1` 退回普通 HTTP。走普通 HTTP 时，超过 50 GB 的文件直接拒绝。 | 脚本里没有专门处理 xet，走 `resolve` 的普通 HTTP；有人报 xet 的 URL 出问题（§1.4）。 | 下载走 LFS bridge，向后兼容（官方说法）。上传要 git-xet，和下载无关。 | 走 `resolve` → xet-bridge 的普通 HTTP，支持 Range（实测 206）。 |
| **认证（gated）** | `token=` 或 `HF_TOKEN`；会把 token 带给 `HF_ENDPOINT` 所指的主机。 | `--hf_username --hf_token`。 | 凭据写进 git 的 credential 或 URL。 | aria2 用 `--header="Authorization: Bearer …"`。跳到 CDN 时会不会也带上这个头，未核对。 |
| **取消后** | 在线程里调用就停不下来；作为子进程（`hf download`）被 SIGTERM 时，异常路径会删掉临时文件；被 SIGKILL 时留下 `*.incomplete` 孤儿文件，下次也不会再用。 | 杀掉以后 `.aria2` 和半截文件都留着，下次接着下。 | 留下半个仓库和 `.git/lfs/tmp`（未核对）。 | `aria2.forceRemove` 或 SIGTERM：控制文件留着，下次 `-c` 接着下。被 SIGKILL 时，控制文件按 `--auto-save-interval`（默认 60 秒）定期落盘，最多损失这一段（未核对：默认值以手册为准）。 |
| **本机现状** | 1.30.0 和 hf-xet 1.6.0 在 conda base 里，**不是平台依赖**。 | 要下载脚本，没有装。 | **git-lfs 没装**（0002 F10）。 | aria2c 1.37、curl 8.18 都已经装好（0002 F10）。 |

出处：
- A：
  - 本机 `file_download.py` 的 `http_get`（L326–L477）和 `_download_to_tmp_and_move`（L1930–L2003）；[v2.3.0 `file_download.py`](https://github.com/huggingface/huggingface_hub/blob/v2.3.0/src/huggingface_hub/file_download.py)，同样的逻辑仍在；
  - [PR #4306](https://github.com/huggingface/huggingface_hub/pull/4306)（"resuming a failed download is no longer possible"，随 v1.18.0 发布）；
  - [下载指南](https://huggingface.co/docs/huggingface_hub/guides/download)（`local_dir` 的 `.cache/huggingface/`、`dry_run`、`allow_patterns`）；
  - [环境变量文档](https://huggingface.co/docs/huggingface_hub/package_reference/environment_variables)（`HF_HUB_DISABLE_XET`、chunk cache 已经不起作用）；
  - 本机 `hf download --help`、`hf cache verify --help`。均已核对。
- B：[hfd.sh gist](https://gist.github.com/padeoe/697678ab8e528b85a2a7bddafea1fa4f)，包括调 aria2c 的那一行 `aria2c --quiet=true … -x "$THREADS" -j "$CONCURRENT" -s "$THREADS" -k 1M -c -i "$fileslist_file" >/dev/null`。已核对。
- C：[Using Xet Storage](https://huggingface.co/docs/hub/en/xet/using-xet-storage)（git-xet、LFS bridge 向后兼容）。git-lfs 自身的行为没有查一手资料。
- D：[aria2 手册](https://aria2.github.io/manual/en/html/aria2c.html)（`--checksum`、`--continue`、`--max-overall-download-limit`、`--enable-rpc`、`tellStatus`、`remove/forceRemove`、`changeGlobalOption`、`--save-session`）；本机 `aria2c -v`。已核对。

**另外两点**：
- **C 要占两倍空间**：git-lfs 先把对象存进 `.git/lfs/objects`，再检出到工作区；另外不能按文件筛选（[snapshot_download 的 docstring](https://github.com/huggingface/huggingface_hub/blob/v2.3.0/src/huggingface_hub/_snapshot_download.py) 也这么写："It is also not possible to filter which files to download when cloning a repository using git"）。对 TB 级的数据集，这两点就足以排除 C。
- **B 的思路可以借鉴，但不能直接嵌进平台**：先列清单，再生成 aria2 的输入文件，再按大小比对续跑，这套思路很好。但脚本把进度藏起来了，也不校验 sha256，参数还靠命令行指纹（`.hfd/last_download_command`）。D 就是把 B 的思路搬进 worker，补上 RPC 进度和 sha256 校验。

---

## 3. huggingface_hub 的版本和 Xet 后端

### 3.1 版本现状（已核对：PyPI JSON 接口，2026-10-28）

| 包 | 最新版 | 发布日期 | 本机 | 备注 |
|---|---|---|---|---|
| huggingface_hub | **2.3.0** | 2026-10-23 | conda base 1.30.0；`lerobot` 环境 1.27.0 | 2.0.0 发布于 2026-09-24 |
| hf-xet | **1.7.1** | 2026-10-28 | 1.6.0 | huggingface_hub 2.3.0 在 x86_64 上**强制依赖** `hf-xet>=1.6.0,<2.0.0` |
| lerobot 0.6.1 | — | — | — | 依赖 `huggingface-hub>=1.6.0,<2.0.0` |

- **2.0 的破坏性变更**（已核对：[v2.0.0 发布说明](https://github.com/huggingface/huggingface_hub/releases/tag/v2.0.0)）：
  - HTTP 栈从 httpx 换成 httpx2，异常类型跟着变了；
  - 默认用操作系统的证书库；
  - 删除了 1.x 里所有已弃用的 API，包括 `huggingface-cli` 命令。
- **推论**（未核对）：平台如果引入 huggingface_hub，版本区间要和 lerobot 0.6.1 分开考虑。平台运行时不依赖 lerobot（ADR 0003），所以技术上不冲突；但开发机上 `lerobot` 环境和平台环境用的大版本会不一样。

### 3.2 Xet 对经镜像下载的影响

- **Hub 上的大文件现在都在 Xet 里**：
  - `lerobot/pusht` 和 `lerobot/aloha_mobile_cabinet` 的 `tree` 接口里，所有 parquet、mp4 都带 `xetHash`，还保留着 `lfs.oid`（sha256）。（已核对：实测）
  - 官方文档写的是"the Hub is fully powered by the Xet storage backend"。（已核对：[环境变量文档](https://huggingface.co/docs/huggingface_hub/package_reference/environment_variables) 里 `HF_HUB_ENABLE_HF_TRANSFER` 那一条）
- **普通 HTTP 照样能下**：
  - `HEAD resolve/main/data/chunk-000/file-000.parquet` 返回 302，`location` 指向 `us.aws.cdn.hf.co/xet-bridge-us/...`，同时给出 `x-linked-etag`（就是 sha256）、`x-linked-size`、`x-xet-hash`，`Link` 头里有 `xet-read-token` 和 CAS 的地址。
  - 跟着 302 带 `Range: bytes=0-99` 请求，返回 **206** 和 `content-range: bytes 0-99/2265`。
  - 所以 aria2 和 curl 的续传、多连接，对 Xet 文件同样有效。（已核对：实测）
  - 302 指向的是带签名的 CDN URL，有有效期，所以续传时应当始终从 `resolve` 的 URL 重新开始，不要保存 CDN 的 URL（推论）。
- **hf_xet 经过镜像时的路径**：
  - token 从 `{HF_ENDPOINT}/api/.../xet-read-token/<rev>` 领取（§1.2）。
  - 拿到 token 以后，hf_xet 向 token 里给出的 CAS 地址请求重建信息，再从预签名的 URL 拉 xorb 分块。（已核对：[下载指南的 Faster downloads 一节](https://huggingface.co/docs/huggingface_hub/guides/download)）
  - 镜像有没有把 CAS 地址和预签名 URL 换成自己的域名，决定了分块数据走不走镜像。从 gist 评论看，两种情况都有，还有报错（§1.4）。**没有查实**。
  - 所以：经镜像用 huggingface_hub 时，建议设 `HF_HUB_DISABLE_XET=1`，统一走 `resolve` 的普通 HTTP。代价是触发 50 GB 的单文件上限（下一条）。
- **50 GB 上限**：
  - huggingface_hub 走普通 HTTP 时，遇到超过 50 GB 的文件直接 `ValueError`，提示改装 hf_xet。（已核对：本机 `constants.py` 的 `MAX_HTTP_DOWNLOAD_SIZE = 50 * 1000 * 1000 * 1000`，`http_get` L370–L375）
  - xet-bridge 自己对超过 50 GB 的文件是什么行为，**未核对**。智元的 tar 分卷有 53.5 GB 的（0005），这类仓库要实测。
- **xet 下载不能跨进程续传**：
  - hf_xet 已经不再用本地分块缓存（`HF_XET_CHUNK_CACHE_SIZE_BYTES` 不起作用，见 [xet-core#715](https://github.com/huggingface/xet-core/issues/715)）。
  - 加上 huggingface_hub 的唯一临时文件机制，一个大文件下到一半被取消，下次要从头下。
  - PR #4306 说"Xet-backed downloads recover most of the resume value through chunk dedup"，但它依赖的本地分块缓存已经关了，这句话现在大概率不成立（推论，未核对）。

---

## 4. LeRobot v3.0 数据集在 Hub 上的文件布局

### 4.1 目录结构（格式细节见 `docs/research/LeRobot版本.md` §1）

```
<repo>/
├── .gitattributes, README.md                      # git 小文件
├── meta/info.json, meta/stats.json                # git 小文件（几 KB 到几十 KB）
├── meta/tasks.parquet                             # Xet
├── meta/episodes/chunk-000/file-000.parquet       # Xet，每个 episode 一行，带分片索引和起止时间
├── data/chunk-000/file-000.parquet ...            # Xet，默认每片不超过 100 MB
└── videos/<video_key>/chunk-000/file-000.mp4 ...  # Xet，每片不超过 200 MB（0.4.0–0.4.1 是 500 MB）
```

### 4.2 实测的三个样例（已核对：Hub `tree` 和 `treesize` 接口）

| 数据集 | 文件数 | 总大小 | 构成 |
|---|---|---|---|
| `lerobot/pusht` | 8 | 7.7 MB | 1 个 data 分片 0.67 MB，1 个视频分片 6.9 MB，meta 约 0.1 MB |
| `lerobot/aloha_mobile_cabinet` | 13 | 1.74 GB | data 9 MB；三路相机各 2 个分片，共 1.73 GB（**视频占 99%**）；meta 0.18 MB |
| `lerobot/droid_1.0.1` | — | 412 GB（`treesize`） | `meta/tasks.parquet` 1.5 MB，`info.json` 10.8 KB |

- 本机导航层里最大的 LeRobot 数据集是 galaxea_open_world，2.86 TB（0002 F9）。M2 要按"单个作业几百 GB 到几 TB、跑好几天"来设计（ADR 0005 举的例子就是"下载要跑三天"）。
- v3.0 的特点是**文件少、单个文件大**（一百到几百 MB），所以续传的粒度落在单个文件上就够了。不像 v2.1，一个 episode 一个文件，动辄几万个文件。

### 4.3 只下一部分

- **筛选语义**：`allow_patterns` / `ignore_patterns` 是 `fnmatch.fnmatchcase`，区分大小写，`*` 能匹配 `/`；以 `/` 结尾的模式会自动补一个 `*`。（已核对：本机 `utils/_paths.py` L17、L135–L155）
  - 自写编排时，对 `tree` 的结果用同一套 fnmatch 规则筛选即可，用户填的模式和 `hf download --include` 行为一致。
- **lerobot 自己的做法**（已核对：[lerobot v0.6.1 `lerobot_dataset.py`](https://github.com/huggingface/lerobot/blob/v0.6.1/src/lerobot/datasets/lerobot_dataset.py) 的 `_download`）：
  - 不要视频时，`ignore_patterns="videos/"`；
  - 只要部分 episode 时，`allow_patterns` = 读 `meta/episodes` 算出来的那些分片路径。
- **对平台的含义**：
  1. 先只下 `meta/`（几 MB），立刻就能显示 episode 数、帧数、FPS、`robot_type`、相机列表，供用户确认和做容量预检。
  2. 再按用户的选择下其余部分。可以是全部；也可以是"不要某路相机"（`ignore videos/<key>/`）；或者"只要前 N 个 episode"，这时用 `meta/episodes/*.parquet` 里的 `data/file_index`、`videos/<key>/file_index` 反查分片。
  3. 最小单位是**整个分片**，一个分片里可能有很多 episode。只下一部分 episode 得到的是"整份元数据 + 部分分片"，这**不是一份完整的 v3.0 数据集**，入库时要么拒绝，要么按"部分下载"另外标记（§6 第 4 条）。

---

## 5. 推荐方案

### 5.1 总体

**下载作业 = 自写编排（只用标准库）+ aria2c（RPC 模式，作为 worker 的子进程）+ curl 单文件兜底。**

理由：
- 0001 原话要求 aria2 加 curl，两个都已经装好。
- ADR 0005 规定下载的恢复方式是"续跑"，而 huggingface_hub 换进程就不续传。
- 进度、限速、取消三项 aria2 都有现成的接口。
- 要自己写的只有"列清单、生成输入、读进度、校验"这层薄编排。按 `AGENTS.md` 规则 7 的顺序，标准库加现有工具就够，不用新依赖。模块注释里要写明为什么不用 huggingface_hub（见 §2 和 §3）。

### 5.2 流程

1. **解析版本**：`GET {endpoint}/api/datasets/<id>/revision/<rev>`，取 `sha`，后面的步骤一律用这个 commit，避免下载途中仓库更新导致新旧文件混在一起。顺便读 `gated`、`private`、`disabled`。gated 但没配 token 的，直接以"需要用户处理"失败，不开始下载。（`sha`、`gated` 字段已核对：实测 `/api/datasets/lerobot/pusht`。`/revision/<rev>` 这个路径是 huggingface_hub `dataset_info(revision=…)` 用的，未逐字核对）
2. **列清单**：`GET {endpoint}/api/datasets/<id>/tree/<sha>?recursive=true&expand=false`，跟着 `Link: rel="next"` 翻页（hfd.sh 就是这么做的）。每条记下 `path`、`size`、`oid`（git blob sha1）、`lfs.oid`（sha256）。清单存进作业记录或暂存区里的清单文件，作为续跑和校验的依据。
3. **筛选与预检**：用 fnmatch 应用包含和排除规则；算出待下总量，减去暂存区里已经完整的部分；对照目标存储根的剩余空间，留一定余量；检查存储根在线（ADR 0005）。这一步的结果就是网页上的"预览"。
4. **下载**：
   - worker 启动一个 `aria2c --enable-rpc --rpc-listen-all=false --rpc-secret=<随机> --continue=true --file-allocation=none --auto-file-renaming=false --max-tries=… --retry-wait=…` 子进程，用进程组管理，跟 M0 第 8 张的外部进程规则一致。
   - 通过 `aria2.addUri` 逐个文件加入，URI 用 `{endpoint}/datasets/<id>/resolve/<sha>/<path>`，带上 `dir`、`out`、`checksum=sha-256=<lfs.oid>`（只有 LFS/Xet 文件有）。
   - 某个文件 aria2 连续失败时，对这一个文件改用 `curl -L -C - --retry N --retry-all-errors -o <file>` 兜底。
5. **校验**：aria2 下完会自己校验 sha256；curl 兜底的文件和非 LFS 小文件，由 worker 用 hashlib 校验，sha256 或 git blob sha1，外加大小。校验失败就删掉这个文件重下一次，还不对就记为失败条目。
6. **入库**：全部校验通过后，进入 ADR 0008 的入库检查（对 LeRobot v3.0 做四层检查），再在同一文件系统上改名进平台区，然后在导航层写锁下建入口、写 `来源.json`（数据来源 = 开源下载，记下 repo_id、commit sha、endpoint、筛选规则）。具体由 G-07 定。

### 5.3 进度、取消、限速、失败重试、暂存

- **进度**：
  - worker 每秒调一次 `aria2.tellActive` / `tellStatus` 和 `getGlobalStat`，按 M0 进度节流规则写数据库。
  - 进度 = 已完成文件的字节数 + 进行中文件的 `completedLength`，除以清单总量；速度取 `downloadSpeed`。
  - 阶段依次是：解析、列清单、预检、下载、校验、入库检查、入库。
  - 计数：文件总数、已完成、失败、跳过（已存在且校验通过）。
  - 作业结果按 ADR 0004 由计数算出，有失败条目就是"部分成功"。
- **取消**：
  - 先 `aria2.forceRemove` 所有任务、`aria2.shutdown`，再按 M0 规则对进程组 SIGTERM，10 秒后 SIGKILL。
  - 暂存区里的半截文件和 `.aria2` 控制文件**保留**，因为 ADR 0005 说取消不清理，重新提交接着下。
- **限速**：
  - 作业参数里带一个全局限速，默认不限。启动时用 `--max-overall-download-limit` 设上。
  - 运行中如果要调，用 `aria2.changeGlobalOption` 生效，不用重启。要不要在网页上提供这个功能，在 G-07 定。
  - curl 兜底时用同一个值传 `--limit-rate`。
- **失败重试**：
  - 三层：aria2 自己的 `--max-tries` / `--retry-wait`（应对 TLS 偶发失败、429、5xx）；单个文件换 curl 兜底；整个作业中断（断电、升级）后按"续跑"重新执行。
  - 续跑时重新执行流程就行，第 4 步碰到已经完整、校验通过的文件会跳过，碰到半截文件靠 `-c` 接着下。
  - 遇到 429 要放慢，不能狂刷，因为镜像会按 IP 限流（§1.4）。
- **暂存区**：
  - 落在目标存储根（NAS 平台区）上的暂存目录，保证入库只是同一文件系统内的改名。
  - **目录名应当按"数据集 + commit"取，不按作业编号**，否则"取消后重新提交接着下"做不到（§6 第 3 条）。
  - 不要用 huggingface_hub 的缓存布局（blobs 加软链接），直接按仓库路径平铺。
- **代理与端点**：
  - endpoint 和代理都写进作业参数和作业日志，显式传给 aria2（`--all-proxy` 或 `--no-proxy`），不依赖 systemd 服务继承来的环境变量。
  - 作业开始前做一次探测：`HEAD {endpoint}/` 和一个 API 请求。如果镜像返回 308 指向 huggingface.co，就在作业日志和网页上明确提示"当前网络下镜像不生效，实际直连官方站"。这个探测也可以复用为需求 (2) 里网络检查的一项。

### 5.4 依赖

- **不需要新增 Python 依赖**：HTTP 请求和 aria2 的 JSON-RPC 都用 `urllib.request`，另外用 `json`、`hashlib`、`fnmatch`、`subprocess`。
  - 注意：urllib 会读代理环境变量，本机的 `no_proxy` 里已经有 `127.0.0.1`，RPC 不会被送进代理；保险起见，RPC 连接显式用不带代理的 opener。
- **系统工具**：aria2c 1.37（现在在 conda 的 `bin` 里，不是系统包）、curl 8.18。M2 要在运维手册里写清楚这两个路径怎么配置，以及最低版本。
- **备选**（不推荐，列出来是为了满足"先用现成的"的比较）：用 huggingface_hub 只做"列清单 + 鉴权"。好处是自动处理分页和 token；代价是引入 httpx2 和 hf-xet 两个重依赖，换来的只是几十行代码。如果负责人更看重少写代码，可以走依赖申请。

### 5.5 风险

| 风险 | 后果 | 应对 |
|---|---|---|
| 当前网络下镜像不生效（308 回官方站） | 速度和稳定性全靠代理；需求 (2) 的"VPN 关了才下"跟现实对不上 | 作业前探测并提示；由负责人决定 Clash 规则（§6 第 1 条） |
| 镜像限流（429）、不稳定，或者镜像停止服务 | 长时间下载中途失败 | 端点可配置，失败后可以改用官方站重新提交；aria2 重试时加等待 |
| gated 数据集的 token 交给第三方镜像 | token 可能泄露 | 对 gated 数据集默认走官方站，或者用专门的只读 token（§6 第 2 条） |
| 本机经代理访问 Hub 时 TLS 偶发失败（实测 10 次中 2 次） | 列清单这一步也会失败 | 列清单的请求也要重试，不能只给下载加重试 |
| 超过 50 GB 的单个文件 | huggingface_hub 的普通 HTTP 路径会拒绝；xet-bridge 的行为不明 | M2 用一个大文件仓库实测（例如智元的 tar 分卷） |
| CDN 签名 URL 过期 | 长时间续传时出现 403 | 始终从 `resolve` 的 URL 开始，让 aria2 重新跟随 302 |
| 只下部分分片 | 得到的不是完整的 v3.0 数据集 | 入库规则另定（§6 第 4 条） |
| aria2 被 SIGKILL 时控制文件不是最新的 | 最多重下一个自动保存周期的数据 | 取消一律先走 RPC，再发信号 |
| 下载途中仓库被更新 | 新旧文件混在一起 | 固定 commit sha 下载（§5.2 第 1 步） |
| aria2 的 `--header` 带 token 时，跳到 CDN 是否还会带上（未核对） | token 发到 CDN 主机 | M2 实测；必要时在 worker 里先解析 302，再把 CDN 的 URL 交给 aria2（但要处理签名过期） |

---

## 6. 留给 M2 开图时负责人决定的问题

1. **hf-mirror 走国内直连，还是干脆用官方站？**
   - 现状：Clash 把镜像的流量送到日本出口，镜像 308 回官方站（§1.3）。
   - 建议：在 Clash 里给 `hf-mirror.com` 加一条 DIRECT 规则，并且实测镜像在直连下对 Xet 文件的 `resolve` 是否正常。如果不正常，平台默认端点就用 huggingface.co 走代理，镜像作为可选端点。
   - 网络检查里的"VPN 是否关闭"相应改成"当前端点实际走的是哪条路"。
2. **gated 数据集的 token 交给谁？**
   - 建议：平台只存一个只读的 fine-grained token，存在状态目录里，不进数据库、不写日志；gated 仓库默认强制走官方站，不经第三方镜像。
3. **暂存目录按什么命名、保留多久？**
   - ADR 0008 写的是 `暂存/<作业编号>/`，失败和中断的保留 7 天。这和 ADR 0005"取消后重新提交接着下"冲突，下载已经下了几百 GB 的情况尤其突出。
   - 建议：下载的暂存目录改为 `暂存/下载/<repo_id>@<commit 前 12 位>/`，重新提交时复用；保留期按"多久没动过"算，而且只能人工清理，不自动删除。
4. **允许只下一部分吗？下一部分的东西能入库吗？**
   - 建议：
     - 允许"不要视频"或"不要某路相机"，按完整数据集的一个变体入库，在 `来源.json` 里记下筛选规则；
     - 只要部分 episode 的，v1 不做；
     - `meta/` 预览这一步一律先做。
5. **默认并发和限速是多少，能不能在运行中调？**
   - 建议：
     - 每类作业并发上限沿用 ADR 0005 的默认值 1。
     - 单个作业内 aria2 同时下 4 个文件、每个文件 4 条连接（接近 hfd 的默认值，比它保守一点，免得被镜像限流）。
     - 全局限速默认不限，作业参数里可以设。
     - "运行中调整限速"放进 M2，因为 aria2 本来就支持，成本低，而且一次下载要跑好几天，期间可能需要让出带宽。

---

## 附录：本次实测的请求

| 主机 | 次数 | 内容 |
|---|---|---|
| hf-mirror.com | 4 | `GET /api/datasets/lerobot/pusht`（走代理、加 `--noproxy` 各一次）、`HEAD …/resolve/main/meta/info.json`、`HEAD /` |
| huggingface.co | 10 | `api/datasets/lerobot/pusht`、它的 `tree`、`resolve meta/info.json`（TLS 失败）、`HEAD resolve data/…parquet`、`aloha_mobile_cabinet` 的 `tree`、`droid_1.0.1` 的 `treesize`（TLS 失败一次后重试）和 `tree/main/meta`、`resolve meta/tasks.parquet` 带 `Range: 0-99`（跟随到 xet-bridge，返回 206） |
| pypi.org | 4 | huggingface_hub、hf-xet 的最新版本，huggingface_hub 2.3.0 和 lerobot 0.6.1 的依赖 |
| cloudflare.com | 2 | `cdn-cgi/trace` 看出口（走代理、加 `--noproxy` 各一次） |

本机只读查看：`/home/shawn/miniconda3/lib/python3.14/site-packages/huggingface_hub/`（1.30.0）、`aria2c -v`、`hf download --help`、`hf cache verify --help`、`env` 里的代理变量、`ip -br addr`、`ip route`。

## 负责人决定（2026-10-28）

- **§6 第 1 条**：负责人原话"不走代理，只走镜像站"。M2 的下载只用 hf-mirror.com，不经代理去 huggingface.co。
  - 落到 M2 的要求：作业开始前先探测（§5）。如果镜像返回 308 指向 huggingface.co（说明流量从境外出口出去），作业就以"网络不满足：镜像不生效"失败，并提示怎么处理：关掉 VPN，或者让 hf-mirror.com 走直连。不允许跟随 308 改成从官方站下载。
  - 下载子进程不设代理环境变量（显式清掉 `HTTPS_PROXY` 等）。但 Clash TUN 模式开着时，清掉变量也没用，还是要靠上面那条探测来兜底。
  - Clash 规则由负责人自己决定，平台和执行线都不去改。
- 负责人补充（2026-10-28）："到时我会把梯子关掉，确保走镜像的"。下载时由负责人关掉梯子；平台照样保留作业前的探测，作为兜底。
