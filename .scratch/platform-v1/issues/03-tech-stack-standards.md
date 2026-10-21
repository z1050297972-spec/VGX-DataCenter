# 技术栈与工程规范

Type: grilling
Status: open
Blocked by: 02

## Question

确认平台的技术栈和"防屎山"机制。0003 第五、六、七节已有推荐答案，原始需求 (11)、(12)、(13) 是来源；前端路线以「[交互形态与前端路线](02-interaction-frontend.md)」的结论为准。

要定的：

- **后端运行环境**：Python 版本；用 uv 管理；平台本身不进 Docker（0003 第五节）。
- **数据库**：SQLite（WAL）+ SQLAlchemy 2 + Alembic。
- **模块划分与依赖方向**：按领域分模块，用 import-linter 合约强制单向依赖。
- **检查链**：
  - 后端：ruff 的规则集和阈值（复杂度、参数个数、语句数）、pyright 严格模式、pytest。
  - 前端：React 对应的检查（TypeScript 严格模式、lint、测试）。
  - 两边都汇总进 `make check`，并接到 pre-commit 上。
- **函数契约模板**：docstring 六项的固定格式（0003 第七节）；前端函数和组件对应的契约要求。
- **新增依赖的审批流程**：后端和前端各怎么走。
- **lerobot 的依赖方式**：平台运行时直接依赖 lerobot，还是只在测试里拿它当格式判定的基准。lerobot 0.6.x 要求 Python 3.12，而且库版本必须锁定，见「[平台统一的 LeRobot 版本](07-lerobot-version.md)」。

**完成标准**：以上各项都有结论。技术栈写成 ADR；`docs/standards/CODING_STANDARDS.md` 的条目要点写在本票 Answer 里，正文在 M0 成文（从 `docs/standards/engineering-control/` 派生）。
