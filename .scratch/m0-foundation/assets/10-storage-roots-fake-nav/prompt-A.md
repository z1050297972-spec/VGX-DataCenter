你在工单「存储根与假导航层」的工作目录 /home/shawn/桌面/robot-data-platform.wt/m0-10-storage-roots-fake-nav（git worktree，分支 t/m0-10-storage-roots-fake-nav）里写契约骨架。

先读下面这些。规划文件一律读主仓库目录 /home/shawn/桌面/robot-data-platform 里的版本：工作目录里的副本停在开分支的那一刻，可能已经过期，也可能缺少还没提交的文件。
- /home/shawn/桌面/robot-data-platform/AGENTS.md
- /home/shawn/桌面/robot-data-platform/docs/standards/CODING_STANDARDS.md
- /home/shawn/桌面/robot-data-platform/docs/agents/codex-workflow.md 第 7.1 节「历次评审打回过的写法」：这些写法以前被打回过，一开始就避免
- 工单 /home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/issues/10-storage-roots-fake-nav.md（含 Comments 里负责人决定 L1–L3 和样本采集记录），以及它引用的：`.scratch/platform-v1/issues/11-dataset-contract.md` 的"存储根""假导航层（Q15，M0 的形态要求）"两节、`docs/adr/0006-导航层是数据集的唯一事实来源.md`、`.scratch/m0-foundation/spec.md` 第 10 张、`GLOSSARY.md` 的存储根、平台区、离线、断链、非数据集目录
- 样本：/home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/assets/10-storage-roots-fake-nav/ 下的 `samples/`（执行线从真实导航层只读复制的原件）、`sources.tsv`（每份原件的相对路径、来源路径、sha256、字节数）、`layout.txt`（导航层顶层、`按格式` 目录、18 条样本链接及目标、目标下第一层、非数据集目录第一层、挂载事实）。你只读这些副本，不读 `/mnt`。

用 $enterprise-coding。这一步只交契约骨架：
1. 签名、类型和六项 docstring 写全（AGENTS.md 规则 4，CODING_STANDARDS 第 3 条）。函数体只写 `raise NotImplementedError`。
2. 测试清单写成跳过的测试（`pytest.skip`），每个测试的 docstring 写明它验证哪条契约行为。
3. `make check` 跑到全绿。

**执行线给的设计方向**（你可以改，改了在第 4 块写理由；不确定的列进第 4 块）

配置（`rdp.infra.config`，第 3 张的模型加两组，不可变、未知字段拒绝，沿用现有风格）
- `nav_root: Path`，默认 `/mnt/datasets`。这个默认值是代码里唯一允许出现的 `/mnt/...`（写成具名常量）；绝对路径或 `~/` 开头，规则同 `state_dir`。
- `[[storage_roots]]`：列表，默认空（本机两块盘由运维写进配置文件，不做代码默认）。每条：`name`（标识符，例如 `dataset1`，规则复用 `rdp.infra.ids` 现有的类型键正则或单独定一个具名正则）、`path`（绝对路径）、挂载源（ext4 写文件系统 UUID，NAS 写"服务器:导出路径"；二选一，建议两个可选字段 `uuid`、`nfs_export` 恰好填一个，或你提出更好的表示）、`writable: bool` 默认 False。
- 校验（验收 4）：名字重复、路径不是绝对路径、两个存储根路径互相包含（含相等），各报一条错，拒绝启动，报错格式沿用第 3 张。
- 访问超时（L2）：默认 10 秒，可在配置里改（例如 `[storage] access_timeout_s`），有上下限。

在线判断（新模块 `rdp.infra.storage`）
- 在线 = 登记路径此刻正是一个挂载点，并且挂载源和登记的一致。读 `/proc/self/mountinfo`：挂载点字段要按内核规则解八进制转义（`\040` 等）；同一挂载点叠了多层时以最后一条为准。
- ext4：用 `/dev/disk/by-uuid/<UUID>` 对上设备。建议比较设备号（by-uuid 链接 `stat().st_rdev` 的 major:minor 对 mountinfo 第 3 列），不比较设备名字符串，避免 `/dev/mapper/...` 一类别名误判；你有更稳的做法也可以。NFS：fstype 是 nfs/nfs4，挂载源字符串等于登记的"服务器:导出路径"。
- 离线原因三种：没挂载、挂错了盘、超时（GLOSSARY"离线"）。读挂载表本身失败怎么处理，由你提出并写清。
- "读挂载表"和"找 by-uuid 设备"两步可替换（注入的协议或可调用对象），测试用它模拟离线、挂错盘、超时（验收 1）；生产实现读真实 `/proc/self/mountinfo` 和 `/dev/disk/by-uuid`，路径不硬编码在业务逻辑里。
- 访问带超时：检查放在线程里做，超时按离线（超时）处理并记一条 WARNING（key=value，带存储根名字和超时秒数）。线程卡住时无法强行结束：模块 docstring 写明这个限制（工单"风险"第 1 条），线程设为 daemon，不 join 无限等待。
- 两种用法：Web 页面只读挂载表、不碰存储根里的文件（ADR 0006）；作业开跑前检查在挂载表核对之外，再对存储根本身做一次有超时的只读访问（例如 stat），"访问超时"只会在这里出现。不往数据盘写任何标记文件。
- 结果类型：每个存储根一条（名字、路径、是否可写、在线/离线及原因、检查时刻 UTC），检查时刻从注入时钟取。

作业开跑前检查（`rdp.jobs`）
- `JobDefinition` 加一项声明：要用哪些存储根、每个要不要写（例如 `storage: tuple[StorageUse, ...]`，默认空）。登记时校验：名字必须在配置的存储根里，否则拒绝启动。
- 执行器在调用作业类型的执行函数之前检查：声明要写一个只读存储根，或者要用的存储根离线，以"外部失败"结束，诊断写明存储根名字和原因，执行函数一次都不调用，存储根上什么都不写（验收 3）。没有声明存储根的作业不做检查、不读挂载表。
- 依赖注入沿用第 9 张的做法：新增依赖是必填关键字，不给 None 默认（第 9 张 `test_required_dependencies_have_no_defaults` 的规则）。现有五种作业类型都不声明存储根，测试用测试专用类型。
- 生产入口装配属于第 11 张，本票不改 `rdp.ops` 的入口命令；Web 用一个类似 `configure_jobs` 的 `configure_storage(app, ..., *, ...)` 接入，worker 一侧经现有依赖对象注入。

页面"存储根"（L3：所有登录账号可看，只读）
- 接口例如 `GET /api/storage-roots`：每个存储根的名字、路径、只读或可写、在线状态和检查时间、离线原因；每次请求现场检查一次（只读挂载表）。权限沿用现有登录校验。不暴露挂载表原文。
- 前端 antd 页面，挂进菜单和路由；类型用生成的 OpenAPI 类型（`make api-types`，不手改生成文件）；页面不轮询，有一个"重新检查"按钮即可（你可以改）。search 参数如有，经真实 router 测（7.1）。

假导航层（`tests/`）
- `tests/fixtures/nav/`：从 assets 的 `samples/` 生成的样本 JSON 和一份清单（例如 `manifest.json`）。清单写明：每个入口（两个视图）有哪些链接、各指向哪个假存储根上的哪个目录；假存储根上要造的目录和小文件，包括带真实 `robot_type`、`fps`、`codebase_version` 的 `meta/info.json`（assets 里有 libero_10 和 EgoProDemo 各一份）；每份样本的来源路径、原件 sha256（取 `sources.tsv`）、截短说明（截了什么、为什么，CODING_STANDARDS 7.4）。
- 截短：大文件只留几条，例如 EgoProStandard 的 734 条数据块只留几条；同一数据集三份 JSON 之间、两个视图的副本之间保持一致（留下同一批记录），让 M1 的配对和引用检查还能在上面做。保留中文标点、空格、括号、撇号这些难处理的字符。
- 占位符：JSON 里的绝对路径换成存储根或导航层占位符，例如 `{dataset1}/libero_v3/libero_10`、`{nav_root}/按任务/libero_10`。注意 `/mnt/datasets` 与 `/mnt/dataset1` 前缀重叠，按路径段整段替换。生成后的样本里不能有 `/mnt/`。
- 一个 pytest fixture（例如 `fake_nav(tmp_path)`）在临时目录里展开：建假存储根、两个视图、真实的软链接（含跨盘 `原始数据__dataset1/__dataset2` 和按子目录逐个链接的 agibot_world_alpha），替换占位符，带上空的 `按格式/lerobot/2.0`、`lerobot/2.1` 和非数据集目录的骨架（`layout.txt` 里的 索引/、文档/、工具/、解压样本/、VGX_video/，只造目录和极小的占位文件）。返回对象给出导航层根、各假存储根路径、可直接用的存储根配置。
- 测试不依赖 `.scratch/`（规划目录不是测试输入）；样本可追溯由评审对照 `sources.tsv` 核对（验收 6）。
- 生成 fixtures 的工作放到派工 B（实现）；骨架阶段先定清单格式、fixture 的签名和返回类型，并写好对应的跳过测试。

**测试清单至少覆盖**：验收 1（在线、没挂载、挂错盘、超时并有一条警告，各一条，用替换的挂载表）、验收 3（只读存储根要写、存储根离线，两种都以外部失败结束且执行函数未被调用、假存储根下无新文件）、验收 4（三种配置错各一条）、验收 5（两个视图各 5 个入口、链接解析到假存储根内、空目录和非数据集骨架存在、无残留占位符、无 `/mnt/`）、验收 7（测试代码和 fixtures 里不出现真实 `/mnt` 访问；用一个静态检查测试）、mountinfo 解析（八进制转义、叠层取最后一条）、设备号比较、配置默认值、API 权限（未登录 401、成员可看）、前端页面三种离线原因的展示、OpenAPI 类型一致。

边界：
- 只改 `src/`、`tests/`。本票允许改的受保护文件：`pyproject.toml`（只在 ruff、basedpyright 需要时调整，每条写理由）。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。样本只读主仓库 assets 里的副本。
- 不安装任何东西，不访问网络（沙箱为了跑测试开了网络权限，但这张票用不到网络；评审会查运行日志，出现安装或联网的命令整轮打回）。需要新依赖时停下，在最终回复里写依赖申请（AGENTS.md 规则 7）。
- 自己在 `/tmp` 或别处建的试验文件，交付前删掉。测试只用临时目录，不碰真实的 `~/.config/rdp`、`~/.local/share/rdp`，不读真实 `/proc/self/mountinfo` 以外的系统状态（读真实挂载表的生产实现可以有一个只读的冒烟测试，但不能依赖本机挂了哪些盘）。

只有三种情况停下：要加新依赖；要改允许范围以外的受保护文件；要改已获批契约的含义（第 9 张及以前的公开签名改动属于此类，确需改动时写进第 3 块申请，像第 9 张那样只加参数或字段的可以先做再申请）。

最终回复分四块：
1. 改动清单：每个文件一行，写做了什么。
2. `make check`：最后一次运行的命令和末尾输出，原样贴出。
3. 契约变更申请、依赖申请：没有就写"无"。
4. 拿不准、需要评审决定的地方（包括你对上面设计方向的改动和理由）。
