# 0006 环境事实更新：Codex 沙箱

> 类别：输入（只追加，不改写）。记录日期：2026-10-21。
> 本文补充 0002 F10 里关于 Codex 的事实，来自走「技术栈与工程规范」时负责人的告知。

## 补充 F10：`workspace-write` 沙箱里的两项限制

- **Codex 不能提交。** 在 `workspace-write` 沙箱里，Codex 写不了 `.git`，所以 `git commit` 会失败。Codex 只能把改动留在工作区，由 Claude 审核后提交。
- **pyright 跑不起来。** 沙箱不能联网，PyPI 上的 `pyright` 包是一层包装，它要联网下载 npm 上的 pyright，所以在沙箱里无法运行。平台改用 basedpyright：它自带 Node，装进 uv 的开发依赖以后不需要联网。basedpyright 能不能在沙箱里正常运行，要在 M0 的第一张工单里实测。
- 来源：负责人在 Codex 沙箱里确认（2026-10-21）。
