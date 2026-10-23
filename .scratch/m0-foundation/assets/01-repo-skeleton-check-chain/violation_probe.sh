#!/usr/bin/env bash
# 违规试验：工单「仓库骨架和检查链」验收第 5、6 条（派工 B 之后加上第 7 条）。
#
# 用法：violation_probe.sh <快照名> [--with-contracts]
#   例：violation_probe.sh A2-done             # 骨架关卡：不含契约检查的违规
#       violation_probe.sh B-done --with-contracts
# 输出写到标准输出，调用方 tee 成 assets/violation_probe-<快照名>.txt。
#
# 做法（codex-workflow.md 5.2）：
#   1. 在临时目录里建探针工作目录，检出 refs/rdp/m0-01/<快照名>，uv sync --frozen。
#   2. 基线 make check 必须全绿。
#   3. 逐个放入违规：跑 make check，记录退出码、失败在哪一步、输出里有没有预期的规则码；
#      去掉违规后核对工作区和基线相同，再跑一次 make check，必须全绿。
#   4. "不能失败"的几种：放入后 make check 必须全绿。
#   5. 钩子试验：git -c core.hooksPath=.githooks commit，不改任何 git 配置。
#   6. 删除探针工作目录。探针里的提交是游离提交，不在任何分支上。
# 只写探针工作目录，不碰工单工作目录和主仓库目录的文件。
set -uo pipefail

MAIN=/home/shawn/桌面/robot-data-platform
TICKET=m0-01
SNAP=${1:?用法：violation_probe.sh <快照名> [--with-contracts]}
WITH_CONTRACTS=${2:-}
PROBE=${PROBE_DIR:-/tmp/claude-1001/-home-shawn----robot-data-platform/311bf87f-07e3-4751-ad0e-0c1d85c02fd0/scratchpad/m0-01/probe-$TICKET}
# make check 每一步开始时打印的步骤行。按 Makefile 实际的写法设定。
STEP_RE=${STEP_RE:?需要设置 STEP_RE：匹配 make check 步骤行的正则}
OUT=$(mktemp -d)
PASS=0
FAIL=0

say() { printf '%s\n' "$*"; }
ok() { PASS=$((PASS + 1)); say "  结果：通过 —— $*"; }
bad() { FAIL=$((FAIL + 1)); say "  结果：不通过 —— $*"; }

# 跑一次 make check，设置 RC、STEP（最后打印的步骤行）、SECS。
run_check() {
  local t0 t1
  t0=$(date +%s.%N)
  make check >"$OUT/check.txt" 2>&1
  RC=$?
  t1=$(date +%s.%N)
  SECS=$(printf '%.1f' "$(echo "$t1 - $t0" | bc)")
  STEP=$(grep -E "$STEP_RE" "$OUT/check.txt" | tail -1)
}

# 违规必须失败在期望的步骤，输出里要有期望的标记；去掉以后恢复原样并全绿。
# 期望输出用规则名匹配：ruff 0.17.1 的默认输出格式写规则名（例如 print:），不写规则码。
# 用法：expect_fail <名字> <期望步骤的正则> <期望输出的正则> <文件> <内容> [no-format]
expect_fail() {
  local name=$1 want_step=$2 want_out=$3 file=$4 content=$5 nofmt=${6:-}
  say ""
  say "== 违规：$name（$file）"
  mkdir -p "$(dirname "$file")"
  printf '%s' "$content" >"$file"
  # 非格式类的违规先格式化，免得它提前失败在格式那一步。
  if [ -z "$nofmt" ]; then .venv/bin/ruff format --quiet "$file"; fi
  run_check
  say "  make check 退出码=$RC，用时 ${SECS}s，最后一步：$STEP"
  grep -nE "$want_out" "$OUT/check.txt" | head -3 | sed 's/^/  输出：/'
  if [ "$RC" -ne 0 ] && grep -qE "$want_step" <<<"$STEP" && grep -qE "$want_out" "$OUT/check.txt"; then
    ok "失败在期望的步骤，输出里有期望的标记"
  else
    bad "期望失败在 /$want_step/ 并输出 /$want_out/"
    sed 's/^/  | /' "$OUT/check.txt" | tail -25
  fi
  rm -f "$file"
  restore_and_recheck
}

# 不能失败的写法：放入后 make check 必须全绿。
expect_pass() {
  local name=$1 file=$2 content=$3
  say ""
  say "== 不能失败：$name（$file）"
  mkdir -p "$(dirname "$file")"
  printf '%s' "$content" >"$file"
  .venv/bin/ruff format --quiet "$file"
  run_check
  say "  make check 退出码=$RC，用时 ${SECS}s，最后一步：$STEP"
  if [ "$RC" -eq 0 ]; then ok "全绿"; else
    bad "不该失败"
    sed 's/^/  | /' "$OUT/check.txt" | tail -25
  fi
  rm -f "$file"
  restore_and_recheck quiet
}

# 去掉违规后：工作区和基线相同；再跑一次 make check 必须全绿。
restore_and_recheck() {
  local now
  now=$(git status --porcelain --untracked-files=all)
  if [ "$now" != "$BASE_STATUS" ]; then
    bad "去掉违规后工作区和基线不同：$now"
    return
  fi
  [ "${1:-}" = quiet ] && return
  run_check
  if [ "$RC" -eq 0 ]; then say "  去掉以后：工作区和基线相同，make check 全绿（${SECS}s）"; else
    bad "去掉以后 make check 没恢复全绿"
    tail -15 "$OUT/check.txt" | sed 's/^/  | /'
  fi
}

# ---------- 1. 探针工作目录 ----------
say "# violation_probe：快照 refs/rdp/$TICKET/$SNAP，$(date '+%F %T %z')"
git -C "$MAIN" worktree remove --force "$PROBE" 2>/dev/null
rm -rf "$PROBE"
git -C "$MAIN" worktree add --detach "$PROBE" "refs/rdp/$TICKET/$SNAP" >/dev/null 2>&1 || { say "建探针工作目录失败"; exit 2; }
cd "$PROBE" || exit 2
say "探针工作目录：$PROBE，HEAD $(git rev-parse --short HEAD)"
uv sync --frozen --quiet || { say "uv sync --frozen 失败"; exit 2; }
say "uv $(uv --version | cut -d' ' -f2)；$(.venv/bin/python --version)；$(.venv/bin/ruff --version)；$(.venv/bin/basedpyright --version | head -1)；pytest $(.venv/bin/pytest --version 2>&1 | awk '{print $2}')"

# ---------- 2. 基线 ----------
BASE_STATUS=$(git status --porcelain --untracked-files=all)
say ""
say "== 基线 make check"
run_check
say "  退出码=$RC，用时 ${SECS}s"
grep -E "$STEP_RE" "$OUT/check.txt" | sed 's/^/  步骤：/'
if [ "$RC" -ne 0 ]; then
  say "基线不是全绿，停止。"
  tail -30 "$OUT/check.txt"
  exit 1
fi
after=$(git status --porcelain --untracked-files=all)
if [ "$after" = "$BASE_STATUS" ]; then say "  跑完以后 git status 和跑之前相同（验收第 8 条）"; else bad "跑完以后 git status 多出：$after"; fi

# 步骤名的正则：按 Makefile 的写法设定（见调用处的环境变量）。
S_FMT=${S_FMT:?}
S_RUFF=${S_RUFF:?}
S_PYRIGHT=${S_PYRIGHT:?}
S_IMPORTS=${S_IMPORTS:?}
S_CONTRACTS=${S_CONTRACTS:-}
S_PYTEST=${S_PYTEST:?}
P=src/rdp/infra/_probe.py
H='"""探针（基础层）：违规试验用，试完删除。"""'

# ---------- 3. 违规必须失败 ----------
expect_fail "格式：一行不符合 ruff format" "$S_FMT" 'Would reformat|would be reformatted' "$P" "$H
VALUE = {  'a':1 }
" no-format

expect_fail "ruff：print(...)" "$S_RUFF" '^print: ' "$P" "$H


def show() -> None:
    \"\"\"打印一行。\"\"\"
    print(\"x\")
"

expect_fail "ruff：不带时区的 datetime.now()" "$S_RUFF" 'call-datetime-now-without-tzinfo' "$P" "$H

from datetime import datetime


def now() -> datetime:
    \"\"\"取当前时刻。\"\"\"
    return datetime.now()
"

expect_fail "ruff：裸 except" "$S_RUFF" 'bare-except' "$P" "$H


def safe() -> int:
    \"\"\"吞掉所有异常。\"\"\"
    try:
        return int(\"1\")
    except:
        return 0
"

expect_fail "ruff：被注释掉的代码" "$S_RUFF" 'commented-out-code' "$P" "$H


def value() -> int:
    \"\"\"返回一个整数。\"\"\"
    # result = compute(1, 2)
    return 1
"

expect_fail "ruff：6 个参数的函数" "$S_RUFF" 'too-many-arguments' "$P" "$H


def many(a: int, b: int, c: int, d: int, e: int, f: int) -> int:
    \"\"\"把六个整数相加。\"\"\"
    return a + b + c + d + e + f
"

expect_fail "basedpyright：一个类型错误" "$S_PYRIGHT" 'reportReturnType|error' "$P" "$H


def value() -> int:
    \"\"\"返回一个整数。\"\"\"
    return \"x\"
"

expect_fail "import-linter：基础层 import 入口层" "$S_IMPORTS" 'BROKEN|broken' "$P" "$H

from rdp import api

__all__ = [\"api\"]
"

expect_fail "pytest：一个失败的断言" "$S_PYTEST" 'failed|FAILED' "tests/test_probe_fail.py" '"""探针：违规试验用，试完删除。"""


def test_probe_fails() -> None:
    """验证契约：探针。断言失败时，make check 失败在 pytest 那一步。"""
    values = [1, 1]
    assert sum(values) == len(values) + 1
'

expect_fail "豁免：不带规则码的 # noqa（本行没有别的问题）" "$S_RUFF" 'blanket-noqa' "$P" "$H

VALUE = 1  # noqa
"

expect_fail "豁免：不带规则码的 # noqa（压在真实违规上）" "$S_RUFF" 'blanket-noqa' "$P" "$H


def show() -> None:
    \"\"\"打印一行。\"\"\"
    print(\"x\")  # noqa
"

expect_fail "豁免：不带规则码的 # type: ignore" "$S_RUFF|$S_PYRIGHT" 'blanket-type-ignore|reportIgnoreCommentWithoutRule' "$P" "$H


def value() -> int:
    \"\"\"返回一个整数。\"\"\"
    return \"x\"  # type: ignore
"

expect_fail "豁免：多余的 # noqa: <规则码>" "$S_RUFF" 'unused-noqa' "$P" "$H

VALUE = 1  # noqa: T201
"

expect_fail "豁免（补充）：不带规则名的 # pyright: ignore" "$S_RUFF|$S_PYRIGHT" 'blanket-type-ignore|reportIgnoreCommentWithoutRule|rule' "$P" "$H


def value() -> int:
    \"\"\"返回一个整数。\"\"\"
    return \"x\"  # pyright: ignore
"

expect_fail "豁免（补充）：多余的 # pyright: ignore[<规则名>]" "$S_PYRIGHT" 'reportUnnecessaryTypeIgnoreComment|Unnecessary' "$P" "$H


def value() -> int:
    \"\"\"返回一个整数。\"\"\"
    return 1  # pyright: ignore[reportReturnType]
"

if [ -n "$WITH_CONTRACTS" ]; then
  # 契约检查的违规（验收第 5 条后半、第 7 条）。放在公开模块里，按公开函数的规则查。
  # 每种违规只在契约检查那一步失败：私有函数由公开函数调用，免得 basedpyright 报未使用；
  # 空的那一项选 Side Effects:，它不是 Google 标准小节，ruff 的 D414 不管它。
  C=src/rdp/infra/probe_contract.py
  CH='"""探针（基础层）：契约检查的违规试验用，试完删除。"""'
  six() { # 用法：six <首行>；输出一段六项齐全的 docstring 正文（不含引号），参数名 flag
    printf '%s\n\n    Args:\n        flag: 开关，True 或 False。\n\n    Returns:\n        原值。\n\n    Raises:\n        无。\n\n    Side Effects:\n        无。\n\n    Time Semantics:\n        无。\n    ' "$1"
  }
  expect_fail "契约：公开函数缺 Time Semantics:" "$S_CONTRACTS" 'probe_contract\.py:[0-9]+ .*no_time.*Time Semantics' "$C" "$CH


def no_time(flag: bool) -> bool:
    \"\"\"返回原值。

    Args:
        flag: 开关，True 或 False。

    Returns:
        原值。

    Raises:
        无。

    Side Effects:
        无。
    \"\"\"
    return flag
"
  expect_fail "契约：私有函数没有 docstring" "$S_CONTRACTS" 'probe_contract\.py:[0-9]+ .*_helper' "$C" "$CH


def uses_private(flag: bool) -> bool:
    \"\"\"$(six '调用私有函数。')\"\"\"
    return _helper(flag)


def _helper(flag: bool) -> bool:
    return flag
"
  expect_fail "契约：@dataclass 没有 Attributes:" "$S_CONTRACTS" 'probe_contract\.py:[0-9]+ .*Point.*Attributes' "$C" "$CH

from dataclasses import dataclass


@dataclass(frozen=True)
class Point:
    \"\"\"平面上的一个点。\"\"\"

    x: int
"
  expect_fail "契约：小节顺序颠倒（Raises 在 Returns 前）" "$S_CONTRACTS" 'probe_contract\.py:[0-9]+ .*swapped' "$C" "$CH


def swapped(flag: bool) -> bool:
    \"\"\"返回原值。

    Args:
        flag: 开关，True 或 False。

    Raises:
        无。

    Returns:
        原值。

    Side Effects:
        无。

    Time Semantics:
        无。
    \"\"\"
    return flag
"
  expect_fail "契约：某一项为空（Side Effects:）" "$S_CONTRACTS" 'probe_contract\.py:[0-9]+ .*empty_side.*Side Effects' "$C" "$CH


def empty_side(flag: bool) -> bool:
    \"\"\"返回原值。

    Args:
        flag: 开关，True 或 False。

    Returns:
        原值。

    Raises:
        无。

    Side Effects:

    Time Semantics:
        无。
    \"\"\"
    return flag
"
  # 验收第 7 条的退出码：直接运行脚本。
  say ""
  say "== 契约脚本退出码（验收第 7 条）"
  .venv/bin/python scripts/check_contracts.py >"$OUT/c0.txt" 2>&1; c0=$?
  say "  无参数（src/rdp、scripts）：退出码 $c0，$(tail -1 "$OUT/c0.txt")"
  printf '%s\n\n\ndef no_time(flag: bool) -> bool:\n    """返回原值。\n\n    Args:\n        flag: 开关。\n\n    Returns:\n        原值。\n    """\n    return flag\n' "$CH" >"$C"
  .venv/bin/python scripts/check_contracts.py "$C" >"$OUT/c1.txt" 2>&1; c1=$?
  say "  有问题的文件：退出码 $c1"; sed 's/^/  | /' "$OUT/c1.txt"
  rm -f "$C"
  .venv/bin/python scripts/check_contracts.py does/not/exist.py >"$OUT/c2.txt" 2>&1; c2=$?
  say "  不存在的路径：退出码 $c2"; sed 's/^/  | /' "$OUT/c2.txt"
  if [ "$c0" -eq 0 ] && [ "$c1" -eq 1 ] && [ "$c2" -eq 2 ]; then ok "0 / 1 / 2"; else bad "退出码是 $c0 / $c1 / $c2"; fi
  restore_and_recheck quiet
fi

# ---------- 4. 不能失败 ----------
expect_pass "注释和 docstring 里的中文全角标点；以"。"结尾的 docstring；Returns: 无、Raises: 无" "src/rdp/infra/probe_ok.py" '"""探针（基础层）：验证中文全角标点不报错，试完删除。

全角标点：，。：；（）！？「」『』、“”‘’《》【】——……
"""

# 注释里的全角标点：，。：；（）！？「」、“”‘’《》【】——……


def noop(flag: bool) -> None:
    """什么也不做，只用来验证 Returns: 无、Raises: 无的写法（规则 4）。

    Args:
        flag: 开关，取值 True 或 False；不影响结果。

    Returns:
        无。

    Raises:
        无。

    Side Effects:
        无（不读也不写任何东西）。

    Time Semantics:
        无。
    """
    _ = flag
'

expect_pass "带理由的单条豁免（# noqa: T201、# pyright: ignore[...]）" "$P" "$H


def show() -> None:
    \"\"\"打印一行。\"\"\"
    print(\"x\")  # noqa: T201  # 理由：探针，验证带理由的单条豁免能用。


def value() -> int:
    \"\"\"返回一个整数。\"\"\"
    return \"x\"  # pyright: ignore[reportReturnType]  # 理由：探针，同上。
"

# ---------- 5. 钩子试验（验收第 6 条） ----------
say ""
say "== 钩子：.githooks/pre-commit 在快照里的权限"
mode=$(git ls-tree HEAD .githooks/pre-commit | awk '{print $1}')
say "  git ls-tree HEAD .githooks/pre-commit → $mode"
if [ "$mode" = 100755 ]; then ok "100755"; else bad "权限是 $mode"; fi

hook_commit() { # 用法：hook_commit <说明>；设置 HRC，输出存到 $OUT/hook.txt
  git -c core.hooksPath=.githooks commit -q -m "$1" >"$OUT/hook.txt" 2>&1
  HRC=$?
}

say ""
say "== 钩子：提交一处违规（print），应被拒"
head0=$(git rev-parse HEAD)
printf '%s\n\n\ndef show() -> None:\n    """打印一行。"""\n    print("x")\n' "$H" >"$P"
git add -A
hook_commit "探针：违规提交"
say "  退出码=$HRC，HEAD $( [ "$(git rev-parse HEAD)" = "$head0" ] && echo 没变 || echo 变了 )"
tail -4 "$OUT/hook.txt" | sed 's/^/  | /'
if [ "$HRC" -ne 0 ] && [ "$(git rev-parse HEAD)" = "$head0" ]; then ok "提交被拒，没有产生新提交"; else bad "违规提交没被拦住"; fi

say ""
say "== 钩子：去掉违规后，同样的命令提交成功"
printf '%s\n\n\ndef value() -> int:\n    """返回一个整数。"""\n    return 1\n' "$H" >"$P"
git add -A
hook_commit "探针：去掉违规后提交"
say "  退出码=$HRC"
tail -3 "$OUT/hook.txt" | sed 's/^/  | /'
if [ "$HRC" -eq 0 ] && [ "$(git rev-parse HEAD)" != "$head0" ]; then ok "提交成功（游离提交 $(git rev-parse --short HEAD)）"; else bad "提交没成功"; fi

say ""
say "== 钩子（D2）：只暂存规划文件（中文文件名），工作区里另有未暂存的违规，应跳过检查"
head1=$(git rev-parse HEAD)
git reset -q  # 暂存区先清空，免得上一步残留的暂存影响"只暂存规划文件"的判断
mkdir -p docs/brief
printf '探针\n' >"docs/brief/9999-环境事实更新-探针.md"
printf '%s\n\n\ndef show() -> None:\n    """打印一行。"""\n    print("x")\n' "$H" >"$P"
git add "docs/brief/9999-环境事实更新-探针.md"
hook_commit "探针：只改规划文件"
say "  退出码=$HRC"
sed 's/^/  | /' "$OUT/hook.txt" | head -5
if [ "$HRC" -eq 0 ] && [ "$(git rev-parse HEAD)" != "$head1" ] && ! grep -qE "$STEP_RE" "$OUT/hook.txt"; then ok "跳过检查并提交成功，没跑 make check"; else bad "只改规划文件时没有跳过"; fi
git checkout -q -- "$P"

say ""
say "== 钩子（D2）：规划文件和代码一起暂存，代码有违规，应跑全量并被拒"
head2=$(git rev-parse HEAD)
printf '探针二\n' >>"docs/brief/9999-环境事实更新-探针.md"
printf '%s\n\n\ndef show() -> None:\n    """打印一行。"""\n    print("x")\n' "$H" >"$P"
git add -A
hook_commit "探针：规划文件加代码"
say "  退出码=$HRC"
tail -3 "$OUT/hook.txt" | sed 's/^/  | /'
if [ "$HRC" -ne 0 ] && [ "$(git rev-parse HEAD)" = "$head2" ] && grep -qE "$STEP_RE" "$OUT/hook.txt"; then ok "跑了 make check，提交被拒"; else bad "混合暂存时没有跑全量检查"; fi

say ""
say "== 钩子（D2）：改名，把代码文件挪进 docs/，应跑全量"
git reset -q --hard "$head2"
git mv -f "$P" "docs/probe_moved.py" 2>/dev/null
git status --porcelain | sed 's/^/  暂存：/'
hook_commit "探针：代码改名进规划目录"
say "  退出码=$HRC"
if grep -qE "$STEP_RE" "$OUT/hook.txt"; then ok "跑了 make check（旧路径在 src/ 下）"; else bad "改名时只看了新路径，跳过了检查"; fi

# ---------- 6. 收尾 ----------
cd / || exit 2
git -C "$MAIN" worktree remove --force "$PROBE"
rm -rf "$OUT"
say ""
say "# 汇总：通过 $PASS 项，不通过 $FAIL 项。探针工作目录已删除。"
[ "$FAIL" -eq 0 ]
