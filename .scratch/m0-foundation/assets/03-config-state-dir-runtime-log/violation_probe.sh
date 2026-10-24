#!/usr/bin/env bash
# 违规试验：工单「配置、状态目录与运行日志」。工单写明"只需要确认已有的检查链照常工作，不新增检查"，
# 所以只挑和本票代码相关的几种后端违规（放在 rdp.infra 里），外加一种前端违规和一次钩子试验。
#
# 用法：violation_probe.sh <快照名>，例：violation_probe.sh B-done
# 输出写到标准输出，调用方 tee 成 assets/violation_probe-<快照名>.txt。
# 辅助函数和探针工作目录的做法照搬第 2 张的 violation_probe.sh（codex-workflow.md 5.2）。
# 只写探针工作目录，不碰工单工作目录和主仓库目录的文件。
set -uo pipefail

MAIN=/home/shawn/桌面/robot-data-platform
TICKET=m0-03
SNAP=${1:?用法：violation_probe.sh <快照名>}
PROBE=${PROBE_DIR:-/tmp/claude-1001/-home-shawn----robot-data-platform/311bf87f-07e3-4751-ad0e-0c1d85c02fd0/scratchpad/m0-03/probe-$TICKET}
STEP_RE='^\[[0-9]+/11\] '
OUT=$(mktemp -d)
PASS=0
FAIL=0

say() { printf '%s\n' "$*"; }
ok() { PASS=$((PASS + 1)); say "  结果：通过 —— $*"; }
bad() { FAIL=$((FAIL + 1)); say "  结果：不通过 —— $*"; }

run_check() {
  local t0 t1
  t0=$(date +%s.%N)
  make check >"$OUT/check.txt" 2>&1
  RC=$?
  t1=$(date +%s.%N)
  SECS=$(printf '%.1f' "$(echo "$t1 - $t0" | bc)")
  STEP=$(grep -E "$STEP_RE" "$OUT/check.txt" | tail -1)
}

# 按扩展名格式化，免得违规提前失败在格式那一步。
fmt_file() {
  case "$1" in
    *.py) .venv/bin/ruff format --quiet "$1" ;;
    src/web/*) (cd src/web && node_modules/.bin/prettier --write --log-level silent "${1#src/web/}") ;;
  esac
}

# 用法：expect_fail <名字> <期望步骤的正则> <期望输出的正则> <文件> <内容> [no-format]
expect_fail() {
  local name=$1 want_step=$2 want_out=$3 file=$4 content=$5 nofmt=${6:-}
  say ""
  say "== 违规：$name（$file）"
  mkdir -p "$(dirname "$file")"
  printf '%s' "$content" >"$file"
  if [ -z "$nofmt" ]; then fmt_file "$file"; fi
  run_check
  say "  make check 退出码=$RC，用时 ${SECS}s，最后一步：$STEP"
  grep -nE "$want_out" "$OUT/check.txt" | head -3 | sed 's/^/  输出：/'
  if [ "$RC" -ne 0 ] && grep -qE "$want_step" <<<"$STEP" && grep -qE "$want_out" "$OUT/check.txt"; then
    ok "失败在期望的步骤，输出里有期望的规则名"
  else
    bad "期望失败在 /$want_step/ 并输出 /$want_out/"
    sed 's/^/  | /' "$OUT/check.txt" | tail -25
  fi
  rm -f "$file"
  restore_and_recheck
}

expect_pass() {
  local name=$1 file=$2 content=$3
  say ""
  say "== 不能失败：$name（$file）"
  mkdir -p "$(dirname "$file")"
  printf '%s' "$content" >"$file"
  fmt_file "$file"
  run_check
  say "  make check 退出码=$RC，用时 ${SECS}s，最后一步：$STEP"
  if [ "$RC" -eq 0 ]; then ok "全绿"; else
    bad "不该失败"
    sed 's/^/  | /' "$OUT/check.txt" | tail -25
  fi
  rm -f "$file"
  restore_and_recheck quiet
}

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
say "# violation_probe：快照 refs/rdp/$TICKET/$SNAP，$(TZ=Asia/Shanghai date '+%F %T %z')"
git -C "$MAIN" worktree remove --force "$PROBE" 2>/dev/null
rm -rf "$PROBE"
git -C "$MAIN" worktree add --detach "$PROBE" "refs/rdp/$TICKET/$SNAP" >/dev/null 2>&1 || { say "建探针工作目录失败"; exit 2; }
cd "$PROBE" || exit 2
say "探针工作目录：$PROBE，HEAD $(git rev-parse --short HEAD)；core.hooksPath=$(git config core.hooksPath)"
uv sync --frozen --quiet || { say "uv sync --frozen 失败"; exit 2; }
# 探针在 tmpfs 上，pnpm 默认按文件系统另找 store（/tmp/.pnpm-store），所以显式指定真实的 store。
(cd src/web && pnpm install --frozen-lockfile --offline --reporter silent --store-dir "$HOME/.local/share/pnpm/store") || { say "pnpm install --offline 失败"; exit 2; }
W=src/web/node_modules/.bin
say "$(.venv/bin/python --version)；$(.venv/bin/ruff --version)；tsc $($W/tsc --version | awk '{print $2}')；eslint $($W/eslint --version)；prettier $($W/prettier --version)；$($W/vitest --version | awk '{print $1}')"

# ---------- 2. 基线 ----------
BASE_STATUS=$(git status --porcelain --untracked-files=all)
say ""
say "== 基线 make check"
run_check
say "  退出码=$RC，用时 ${SECS}s"
grep -E "$STEP_RE" "$OUT/check.txt" | sed 's/^/  步骤：/'
grep -E 'passed|skipped|Tests ' "$OUT/check.txt" | sed 's/^/  /'
if [ "$RC" -ne 0 ]; then
  say "基线不是全绿，停止。"
  tail -30 "$OUT/check.txt"
  exit 1
fi
after=$(git status --porcelain --untracked-files=all)
if [ "$after" = "$BASE_STATUS" ]; then ok "跑完以后 git status 和跑之前相同（验收第 11 条）"; else bad "跑完以后 git status 多出：$after"; fi

S_TSC='^\[8/11\] '
S_ESLINT='^\[9/11\] '
S_PRETTIER='^\[10/11\] '
S_VITEST='^\[11/11\] '
S_IMPORTS='^\[4/11\] '
S_CONTRACTS='^\[5/11\] '
S_STALE='^\[7/11\] '
S_FORMAT='^\[1/11\] '
S_RUFF='^\[2/11\] '
S_PYRIGHT='^\[3/11\] '
S_PYTEST='^\[6/11\] '

PY=src/rdp/infra/probe_violation.py
HDR='"""探针（基础层）：违规试验用，试完删除。"""
'

# ---------- 3. 违规：都必须失败在对应的那一步 ----------
expect_fail "ruff：print（T20）" "$S_RUFF" 'T201|print' "$PY" "$HDR
def probe_print() -> None:
    \"\"\"打印一行。

    Args:
        无。

    Returns:
        无。

    Raises:
        无。

    Side Effects:
        无。

    Time Semantics:
        无。
    \"\"\"
    print(\"x\")
"
expect_fail "ruff：不带时区的 datetime.now()（DTZ）" "$S_RUFF" 'DTZ005|call-datetime-now-without-tzinfo|tz' "$PY" "${HDR}
from datetime import datetime


def probe_now() -> datetime:
    \"\"\"返回当前时刻。

    Args:
        无。

    Returns:
        当前时刻。

    Raises:
        无。

    Side Effects:
        无。

    Time Semantics:
        本地时间。
    \"\"\"
    return datetime.now()
"
expect_fail "ruff：不带规则码的 noqa（blanket-noqa）" "$S_RUFF" 'PGH004|blanket' "$PY" "${HDR}
import os  # noqa
"
expect_fail "basedpyright：类型错误" "$S_PYRIGHT" 'error' "$PY" "${HDR}
PROBE_VALUE: int = \"x\"
"
expect_fail "import-linter：rdp.infra 里 import uvicorn" "$S_IMPORTS" 'BROKEN|broken' "$PY" "${HDR}
import uvicorn

PROBE_NAME = uvicorn.__name__
"
expect_fail "契约检查：公开函数缺 Time Semantics:" "$S_CONTRACTS" 'Time Semantics|probe_missing' "$PY" "${HDR}
def probe_missing() -> None:
    \"\"\"缺一项。

    Args:
        无。

    Returns:
        无。

    Raises:
        无。

    Side Effects:
        无。
    \"\"\"
"
expect_fail "pytest：一个失败的断言" "$S_PYTEST" 'FAILED|failed' "tests/test_probe_violation.py" '"""探针：违规试验用，试完删除。"""


def test_probe_fails() -> None:
    """验证契约：探针，必然失败。"""
    assert 1 == 2
'
expect_fail "ruff format：一处不合格式" "$S_FORMAT" 'probe_violation' "$PY" "${HDR}
PROBE_VALUE:int=1
" no-format
expect_fail "ESLint：no-console" "$S_ESLINT" 'no-console' "src/web/src/probe.ts" "/**
 * 打印输入值。
 *
 * @param value - 任意数。
 * @returns 原值。
 * @throws 无。
 * @sideEffects 无。
 * @timeSemantics 无。
 */
export function probeLog(value: number): number {
  console.log(value);
  return value;
}
"

# ---------- 4. 不能失败的 ----------
expect_pass "带理由的单条豁免和中文注释" "$PY" "${HDR}
# 探针：中文全角标点不报错，，。：；（）
PROBE_TMP = \"/tmp/rdp-probe\"  # noqa: S108  # 理由：探针，验证带规则码和理由的豁免能过。
"

# ---------- 5. 钩子：普通 git commit ----------
hook_commit() { git commit -q -m "$1" >"$OUT/hook.txt" 2>&1; HRC=$?; }
say ""
say "== 钩子：提交带 print 的代码"
head0=$(git rev-parse HEAD)
printf '%s\n\n\ndef _probe() -> None:\n    """探针。"""\n    print("x")\n' "$HDR" >"$PY"
.venv/bin/ruff format --quiet "$PY"
git add "$PY"
hook_commit "探针：违规提交"
grep -E 'T201|print|检查失败' "$OUT/hook.txt" | head -3 | sed 's/^/  | /'
if [ "$HRC" -ne 0 ] && [ "$(git rev-parse HEAD)" = "$head0" ]; then ok "提交被拒，没有产生新提交"; else bad "违规提交没被拦住"; fi
git reset -q HEAD -- "$PY"; rm -f "$PY"
restore_and_recheck quiet

# ---------- 6. 收尾 ----------
cd /
git -C "$MAIN" worktree remove --force "$PROBE"
rm -rf "$OUT"
say ""
say "# 合计：通过 $PASS 项，不通过 $FAIL 项"
[ "$FAIL" -eq 0 ]
