"""机器人数据管理平台包 rdp 的根，提供统一的包命名空间。

根包本身不属于具体业务层，不放入口、领域或基础设施逻辑。
包内分为三层，只能从上往下依赖：入口层（rdp.api、rdp.ops）→ 领域层
→ 基础层（rdp.infra，负责数据库、配置、日志等）。

依据：ADR 0002（docs/adr/0002-技术栈.md）、CODING_STANDARDS 1.1、4.1，
以及工单「仓库骨架和检查链」
（.scratch/m0-foundation/issues/01-repo-skeleton-check-chain.md）的派工 A1。
"""
