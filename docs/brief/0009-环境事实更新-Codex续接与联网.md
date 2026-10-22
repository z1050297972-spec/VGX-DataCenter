# 0009 环境事实更新：Codex 续接与联网

> 类别：输入（只追加，不改写）。记录日期：2026-10-21。
> 本文补充 0006，来自走「Codex 协作规程」时 Claude 的实测。版本：codex-cli 0.163.0。
> 实验脚本和原始输出在 `.scratch/platform-v1/assets/08-codex-workflow/`（`sandbox_probe.sh`、`sandbox_probe-20261021.txt`）。实验在临时目录里新建的一个 git 仓库上进行，没有碰本仓库。

## 在 git worktree 里运行

- 用 `codex exec -C <worktree> -s workspace-write` 时，Codex 能在 worktree 里写文件，也能跑 `git status`。
- 但 `git add` 和 `git commit` 都会失败：worktree 的索引在主仓库的 `.git/worktrees/<名字>/` 下，在沙箱里是只读的（`Unable to create '…/index.lock': Read-only file system`）。
- 所以在 worktree 里，Codex 连暂存都做不了，改动只能留在工作区。

## `codex exec resume` 在当前目录工作

- `codex exec resume` 没有 `-C` 和 `-s` 参数。
- 续接的会话**在执行这条命令时所在的目录里工作**，不在第一次 `-C` 指定的目录里。
- 实测：第一次在 worktree 里运行，两次续接都是在主仓库目录里执行的，结果两轮新建的文件都写进了主仓库目录，worktree 里没有。Codex 回复"已创建"，这句话本身没错，只是写错了地方。
- 不带沙箱参数续接时仍然能写文件。为了行为确定，续接时用 `-c 'sandbox_mode="…"'` 显式写明沙箱模式。

## 联网

- **联网搜索可用**：`-s read-only` 加 `-c 'web_search="live"'` 时，Codex 能用自带的联网搜索。实测它查到了 pypi.org 上的 lerobot 页面，运行日志里有 `web_search` 事件。
- **命令行不能联网**：只读沙箱里，`curl https://pypi.org/…` 报 `failed to open socket: Operation not permitted`。所以下载文件、克隆仓库、安装包都做不了。

## 读权限

- 只读沙箱能读工作目录以外的文件：实测读到了 `/etc/os-release`，也列出了 `/mnt/dataset1`、`/mnt/dataset2`、`/mnt/datasets`。
- 所以 `AGENTS.md` 禁止参考的两个旧项目，沙箱也挡不住（没有实测去读它们）。本机 `~/.codex/config.toml` 还把 `/` 和这两个旧项目都标成了 trusted。
- "不读旧项目"这一条只能靠派工提示，加上事后检查运行日志里的命令。
