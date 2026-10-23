**1. 改动清单**

[src/web/package.json](/home/shawn/桌面/robot-data-platform.wt/m0-02-web-skeleton-frontend-check-chain/src/web/package.json)：新建，仅含 `name`、`private`、`type`、`scripts`；脚本为 `dev`、`build`、`preview`。改动留在工作区，未暂存、未提交。

**2. `make check`**

A1 不跑检查。

`git status --porcelain --untracked-files=all` 原样输出：

```text
?? src/web/package.json
```

**3. 契约变更申请、依赖申请**

无。

**4. 拿不准、需要评审决定的地方**

无。只保留四个字段以满足 A1 范围，依赖表留给 Claude 用 `pnpm add` 写入。`scripts` 仅供本地开发，检查命令统一维护在 Makefile，避免两处不一致；A2 再将这些理由写入 Makefile 注释。