> 本文是 2026-10-23 的目录说明快照；最新项目能力、目录和阶段说明请见 [README.md](README.md)。

# 1.首次接触项目，请先阅读本文档，

# 2.本文档主要是介绍项目中各个目录的内容、每个目录都讲了什么，

# PS. 这非常重要！！！避免被淹没在文档的海洋里！

# 后续开发时，AI的节奏很快，but make it slow,make AI in control!

# docs看说明，.scratch看任务进度和进度，src看程序，tests看测试

robot-data-platform/
│
├── docs/                       项目的说明书
│   ├── README.md               文档导航：不知道去哪找，先看它
│   ├── brief/                  原始需求、环境事实及后续更新
│   ├── adr/                    重要架构决定，以及为什么这样选
│   ├── research/               技术调研结果和依据
│   ├── manual/                 使用、维护方面的操作手册
│   ├── standards/              代码和工程规范
│   │   └── engineering-control/  制定规范时使用的参考材料
│   └── agents/                 Claude、Codex 如何派工、评审和协作
│
├── .scratch/                   项目任务和过程记录
│   ├── platform-v1/            整个平台的规划、方案讨论
│   │   ├── map.md              规划总览：已决定什么，还有什么没定
│   │   ├── issues/             决策票：逐个讨论需要确定的问题
│   │   └── assets/             支撑讨论的脚本、样例和采集记录
│   └── m0-foundation/          M0 阶段：搭建平台基础
│       ├── spec.md             这个阶段要交付什么、如何验收
│       ├── issues/             实现工单：具体开发任务及其进度
│       └── assets/             派工提示、执行回复、检查记录等
│
├── src/                        平台的正式源代码
│   └── rdp/                    平台的 Python 包
│       ├── api/                Web 接口入口
│       ├── infra/              基础能力：时间、配置、数据库、日志等
│       └── ops/                运维命令入口
│
├── tests/                      自动测试，验证程序是否符合约定
└── scripts/                    开发辅助脚本，目前有函数契约检查工具
|
├── AGENTS.md                   CODEX作为执行者的规范文档
|
└── CLAUDE.md                   CLAUDE作为项目管理和审核者的规范文档
|
└── GLOSSARY.md                 系统开发过程中所用术语的解释文档


| 你想了解什么 | 去哪里找 |
|---|---|
| 最开始提出了什么需求？ | docs/brief/ |
| 调研过哪些选择？ | docs/research/ |
| 当时讨论了什么、负责人怎么拍板？ | .scratch/platform-v1/issues/ |
| 最终的重要架构决定是什么？ | docs/adr/ |
| 接下来具体怎么开发？ | .scratch/m0-foundation/issues/ |
| 做好以后怎么使用？ | docs/manual/ |

.scratch/ 在这个项目里需要保留。 虽然名字像临时目录，但它承担了工单系统的作用，里面保存着计划、状态和评审历史。

它下面那些 05-robot-facts/、16-dataset-browser/ 等编号目录，只是对应事项的附件夹，不必逐个记住。常见名称可以这样理解：

- assets/：该事项的附件和证据，在这里也包括脚本、提示词和报告。
- raw/：未经整理的原始采集输出。
- prompt-*.md：给执行者的派工提示。
- out-*.md：执行者返回的结果。
- violation_probe*：检查违规行为能否被自动检查拦住的验证材料。

还有一批隐藏目录，平时可以折叠起来：

| 目录 | 含义 |
|---|---|
| .git/ | Git 的版本历史和分支信息，由 Git 管理 |
| .githooks/ | 提交时自动执行的检查，目前有 pre-commit |
| .venv/ | 项目专用的 Python 环境和安装的依赖 |
| .pytest_cache/、.ruff_cache/ | 测试、代码检查工具生成的缓存 |
| 各处的 __pycache__/ | Python 自动生成的缓存 |
| .agents/、.codex/、.aws/ | 本次查看时均为空，暂无项目内容需要阅读 |

根目录的几个文件也可以按用途记：

| 文件 | 用途 |
|---|---|
| AGENTS.md | AI 在这个项目里必须遵守的规则 |
| CLAUDE.md | Claude 的规划、派工、评审职责 |
| GLOSSARY.md | 项目术语词典，例如“导航层”“存储根”“作业” |
| pyproject.toml、uv.lock | Python 项目配置、依赖清单及锁定版本 |
| Makefile | 常用开发命令入口，统一检查命令是 make check |
| .gitignore | 指定哪些本地文件不纳入版本管理 |

当前这份工作目录里，api/ 和 ops/ 还只是预留入口，infra/ 已有时间处理工具；前端 src/web/ 尚未出现在这里。工单中写到的数据库、账号、作业等功能，需要区分“已经规划”和“已经实现”。

对你日常查看项目，最实用的是收藏这几个入口：

- 找文档：文档地图 (docs/README.md)
- 看整体方案和未决问题：平台规划总览 (.scratch/platform-v1/map.md)
- 看当前阶段要做什么：M0 底座计划 (.scratch/m0-foundation/spec.md)，具体进度看同目录 issues/ 中的 Status:
- 遇到术语看不懂：术语表 (GLOSSARY.md)
