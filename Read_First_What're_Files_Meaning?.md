> 本文是 2026-11-01 的目录说明快照，第一次更新于 2026-10-23。项目能力和各阶段进度，以 [README.md](README.md) 为准。

# 1.首次接触项目，请先阅读本文档，

# 2.本文档主要是介绍项目中各个目录的内容、每个目录都讲了什么，

# PS. 这非常重要！！！避免被淹没在文档的海洋里！

# 后续开发时，AI的节奏很快，but make it slow,make AI in control!

# docs看说明，.scratch看任务和进度，src看程序，tests看测试

robot-data-platform/
│
├── docs/                       项目的说明书
│   ├── README.md               文档导航：不知道去哪找，先看它
│   ├── brief/                  原始需求、环境事实及后续更新（0001–0013）
│   ├── adr/                    重要架构决定，以及为什么这样选（0001–0011）
│   ├── research/               技术调研结果和依据
│   ├── manual/                 操作手册：使用手册、运维手册、导航层手册
│   ├── standards/              代码和工程规范
│   │   └── engineering-control/  制定规范时使用的参考材料
│   └── agents/                 Claude、Codex 如何派工、评审和协作
│
├── .scratch/                   项目任务和过程记录（相当于工单系统）
│   ├── platform-v1/            整个平台的规划、方案讨论
│   │   ├── map.md              规划总览：已决定什么，还有什么没定
│   │   ├── issues/             决策票：逐个讨论需要确定的问题
│   │   └── assets/             支撑讨论的脚本、样例和采集记录
│   ├── m0-foundation/          M0 阶段：搭建平台基础（已完成；第 12 张备份还没开工）
│   ├── m1-datasets/            M1 阶段：数据集浏览、检查和受控写入（已完成）
│   ├── m1.5-edit-view-classify/  M1.5 阶段：字段编辑、原文件查看、场景与任务分类（已完成）
│   ├── m2-downloads/           M2 阶段：开源数据下载、入库、网络与资源监控（已完成）
│   └── ui-style/               前端样式线：统一页面样式（已完成 01、02 张）
│       每个阶段目录里都是同样的结构：
│       ├── spec.md             这个阶段要交付什么、如何验收
│       ├── issues/             实现工单：具体开发任务及其进度
│       ├── followups.md        记下来、暂时没处理的遗留事项
│       └── assets/             派工提示、执行回复、演练记录、截图等
│
├── src/                        平台的正式源代码
│   ├── rdp/                    平台的 Python 包（后端）
│   │   ├── api/                Web 接口
│   │   ├── accounts/           账号、登录、会话
│   │   ├── audit/              操作日志、登录日志、报错记录
│   │   ├── jobs/               后台作业：作业框架、调度、数据集扫描、导航层写入、下载、文件查看
│   │   ├── monitoring/         网络与资源监控（镜像站是否可用、磁盘和 GPU）
│   │   ├── infra/              基础能力：时间、配置、数据库与迁移、日志、存储根
│   │   └── ops/                运维命令入口（rdp migrate、rdp status 等）
│   └── web/                    网页前端（React + antd）
│       └── src/                按页面分目录：datasets、jobs、downloads、accounts、audit 等
│
├── tests/                      自动测试，验证程序是否符合约定
├── scripts/                    安装、升级、一键部署脚本，以及函数契约检查工具
│
├── README.md                   项目介绍：能做什么、怎么装、各阶段进度
├── AGENTS.md                   CODEX作为执行者的规范文档
├── CLAUDE.md                   CLAUDE作为项目管理和审核者的规范文档
└── GLOSSARY.md                 系统开发过程中所用术语的解释文档


| 你想了解什么 | 去哪里找 |
|---|---|
| 项目现在能做什么、做到哪了？ | README.md |
| 最开始提出了什么需求？ | docs/brief/ |
| 调研过哪些选择？ | docs/research/ |
| 当时讨论了什么、负责人怎么拍板？ | .scratch/platform-v1/issues/ |
| 最终的重要架构决定是什么？ | docs/adr/ |
| 某个阶段具体做了哪些开发、进度如何？ | .scratch/<阶段目录>/issues/，看每张工单开头的 Status: |
| 做好以后怎么使用、怎么安装和升级？ | docs/manual/ |

.scratch/ 在这个项目里需要保留。 虽然名字像临时目录，但它承担了工单系统的作用，里面保存着计划、状态和评审历史。

它下面那些 05-robot-facts/、13-followups-cleanup/ 等编号目录，只是对应事项的附件夹，不必逐个记住。常见名称可以这样理解：

- assets/：该事项的附件和证据，在这里也包括脚本、提示词和报告。
- raw/：未经整理的原始采集输出。
- prompt-*.md：给执行者的派工提示。
- out-*.md：执行者返回的结果。
- *-drill.sh、*-drill.mjs、drill/：用真实数据副本做的演练脚本、运行记录和截图。
- violation_probe*、mutation_probe*：检查违规能不能被拦住、测试能不能发现故意改坏的代码的验证材料。

还有一批隐藏目录，平时可以折叠起来：

| 目录 | 含义 |
|---|---|
| .git/ | Git 的版本历史和分支信息，由 Git 管理 |
| .githooks/ | 提交时自动执行的检查，目前有 pre-commit（提交代码时自动跑 make check） |
| .venv/ | 项目专用的 Python 环境和安装的依赖 |
| src/web/node_modules/ | 前端安装的依赖 |
| .pytest_cache/、.ruff_cache/ | 测试、代码检查工具生成的缓存 |
| 各处的 __pycache__/ | Python 自动生成的缓存 |

根目录的几个文件也可以按用途记：

| 文件 | 用途 |
|---|---|
| README.md | 项目介绍和各阶段进度，对外发布时的首页 |
| AGENTS.md | AI 在这个项目里必须遵守的规则 |
| CLAUDE.md | Claude 的规划、派工、评审职责 |
| GLOSSARY.md | 项目术语词典，例如“导航层”“存储根”“作业” |
| pyproject.toml、uv.lock | Python 项目配置、依赖清单及锁定版本 |
| Makefile | 常用开发命令入口，统一检查命令是 make check |
| .gitignore | 指定哪些本地文件不纳入版本管理 |

当前状态（2026-11-01）：M0、M1、M1.5、M2 的工单都已完成并合并，真实部署运行的是 `ed036c2`。M0 第 12 张（本地备份与恢复）只有规划，还没开工。M3–M6 是后续规划。

对你日常查看项目，最实用的是收藏这几个入口：

- 看项目能做什么：项目介绍 (README.md)
- 找文档：文档地图 (docs/README.md)
- 看整体方案和未决问题：平台规划总览 (.scratch/platform-v1/map.md)
- 看某个阶段要做什么：各阶段目录下的 spec.md，具体进度看同目录 issues/ 中的 Status:
- 安装、升级、出问题去哪看：运维手册 (docs/manual/运维手册.md)
- 遇到术语看不懂：术语表 (GLOSSARY.md)
