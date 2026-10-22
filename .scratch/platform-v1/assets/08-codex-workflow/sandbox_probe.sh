#!/usr/bin/env bash
# 实测三件事：resume 是否保留 workspace-write；worktree 里能否写、能否 git commit；read-only 下能否联网搜索。
set -u
S=$(cd "$(dirname "$0")" && pwd)
rm -rf "$S/repo" "$S/wt" "$S/ro"; mkdir -p "$S/repo" "$S/ro"
cd "$S/repo" && git init -q -b main && echo hi > README && git add README && git -c user.name=t -c user.email=t@t commit -qm init
git worktree add -q "$S/wt" -b t/M0-01-probe
sid() { grep -o '"thread_id":"[^"]*"' "$1" | head -1 | cut -d'"' -f4; }

echo "== 1. exec -s workspace-write in worktree"
codex exec -C "$S/wt" -s workspace-write --json -o "$S/out1.md" \
  "在当前目录创建文件 a.txt，内容为 hello。然后依次运行 git status --porcelain 和 git -c user.name=t -c user.email=t@t commit -am x 以及 git add a.txt，把每条命令的原始输出和退出码原样报告。不要做别的事。" > "$S/ev1.jsonl" 2>"$S/err1.txt"
echo "rc=$? sid=$(sid "$S/ev1.jsonl")"; ls "$S/wt"; cat "$S/out1.md"

ID=$(sid "$S/ev1.jsonl")
echo "== 2. resume without sandbox flag"
codex exec resume "$ID" --json -o "$S/out2.md" "再在当前目录创建 b.txt，内容为 world。如果写入失败，把错误原样报告。不要做别的事。" > "$S/ev2.jsonl" 2>"$S/err2.txt"
echo "rc=$?"; ls "$S/wt"; cat "$S/out2.md"

echo "== 3. resume with -c sandbox_mode=workspace-write"
codex exec resume "$ID" -c 'sandbox_mode="workspace-write"' --json -o "$S/out3.md" "再在当前目录创建 c.txt，内容为 again。如果写入失败，把错误原样报告。不要做别的事。" > "$S/ev3.jsonl" 2>"$S/err3.txt"
echo "rc=$?"; ls "$S/wt"; cat "$S/out3.md"

echo "== 4. read-only + web_search live"
codex exec -C "$S/ro" --skip-git-repo-check -s read-only -c 'web_search="live"' --json -o "$S/out4.md" \
  "用联网搜索查 PyPI 上 lerobot 包的最新版本号。只回答版本号和来源网址。如果你没有联网搜索工具，或者搜索失败，只回答 NO_SEARCH 并说明原因。不要运行 shell 命令。" > "$S/ev4.jsonl" 2>"$S/err4.txt"
echo "rc=$?"; cat "$S/out4.md"; grep -o '"type":"[a-z_]*search[a-z_]*"' "$S/ev4.jsonl" | sort | uniq -c

echo "== 5. read-only: network from shell"
codex exec -C "$S/ro" --skip-git-repo-check -s read-only --json -o "$S/out5.md" \
  "运行 curl -sS -m 8 -o /dev/null -w '%{http_code}' https://pypi.org/simple/lerobot/ ，把输出和退出码原样报告。不要做别的事。" > "$S/ev5.jsonl" 2>"$S/err5.txt"
echo "rc=$?"; cat "$S/out5.md"
