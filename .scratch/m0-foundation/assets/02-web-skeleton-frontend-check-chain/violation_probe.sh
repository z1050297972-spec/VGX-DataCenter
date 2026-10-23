#!/usr/bin/env bash
# 违规试验：工单「Web 骨架与前端检查链」验收第 8、9、11 条。
#
# 用法：violation_probe.sh <快照名> [--with-b]
#   例：violation_probe.sh A2-done          # 骨架关卡：不含过期检查和契约脚本 W3
#       violation_probe.sh B-done --with-b  # 派工 B 之后：加上过期检查、W3
# 输出写到标准输出，调用方 tee 成 assets/violation_probe-<快照名>.txt。
#
# 做法（codex-workflow.md 5.2，沿用第 1 张票的探针）：
#   1. 在临时目录里建探针工作目录，检出 refs/rdp/m0-02/<快照名>；uv sync --frozen；
#      src/web 里 pnpm install --frozen-lockfile --offline（store 已在第 7 步填好）。
#   2. 基线 make check 必须全绿，跑完 git status 不变（验收第 11 条）。
#   3. 逐个放入违规：跑 make check，核对退出码、失败在哪一步（最后打印的 [n/11] 行）、
#      输出里有没有期望的规则名（按规则名匹配，不按规则码）；去掉后工作区和基线相同、
#      make check 全绿。
#   4. "不能失败"的几种：放入后 make check 必须全绿。
#   5. 钩子试验：普通的 git commit（core.hooksPath 已在共用的 .git/config 里设为 .githooks），
#      不加 -c、不改任何 git 配置。
#   6. 删除探针工作目录。探针里的提交是游离提交，不在任何分支上。
# 只写探针工作目录，不碰工单工作目录和主仓库目录的文件。
set -uo pipefail

MAIN=/home/shawn/桌面/robot-data-platform
TICKET=m0-02
SNAP=${1:?用法：violation_probe.sh <快照名> [--with-b]}
WITH_B=${2:-}
PROBE=${PROBE_DIR:-/tmp/claude-1001/-home-shawn----robot-data-platform/311bf87f-07e3-4751-ad0e-0c1d85c02fd0/scratchpad/m0-02/probe-$TICKET}
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

T=src/web/src/probe.ts
TX=src/web/src/probe.tsx
# 六项齐全的 TSDoc，供 ESLint 违规之外的部分合格。
doc() { # 用法：doc <首行> [额外的 @param 行...]
  local first=$1; shift
  printf '/**\n * %s\n *\n' "$first"
  if [ $# -eq 0 ]; then printf ' * @param value - 输入数字，无单位。\n'; else for p in "$@"; do printf ' * %s\n' "$p"; done; fi
  printf ' * @returns 输入值。\n * @throws 无。\n * @sideEffects 无。\n * @timeSemantics 无。\n */\n'
}

# ---------- 3a. tsc ----------
expect_fail "tsc：类型错误" "$S_TSC" 'error TS2322' "$T" "/** 探针常量。 */
export const probeValue: number = \"x\";
"
expect_fail "tsc：越界下标当成非 undefined 用（noUncheckedIndexedAccess）" "$S_TSC" "error TS2322.*undefined" "$T" "const values: number[] = [1];
/** 探针常量。 */
export const first: number = values[0];
"

# ---------- 3b. ESLint ----------
expect_fail "ESLint：no-floating-promises" "$S_ESLINT" 'no-floating-promises' "$T" "$(doc '异步返回输入值。')
export async function probeAsync(value: number): Promise<number> {
  return Promise.resolve(value);
}

$(doc '调用异步函数却不处理 Promise。')
export function probeCaller(value: number): void {
  probeAsync(value);
}
"
expect_fail "ESLint：rules-of-hooks" "$S_ESLINT" 'rules-of-hooks' "$TX" "import { useState } from \"react\";

$(doc '在条件分支里调用 hook。')
export function useProbe(value: number): number {
  if (value > 0) {
    const [state] = useState(value);
    return state;
  }
  return value;
}
"
expect_fail "ESLint：complexity（> 10）" "$S_ESLINT" '\bcomplexity\b' "$T" "$(doc '把输入映射成另一个数。')
export function probeComplex(value: number): number {
  if (value === 1) return 10;
  if (value === 2) return 20;
  if (value === 3) return 30;
  if (value === 4) return 40;
  if (value === 5) return 50;
  if (value === 6) return 60;
  if (value === 7) return 70;
  if (value === 8) return 80;
  if (value === 9) return 90;
  if (value === 10) return 100;
  if (value === 11) return 110;
  return value;
}
"
expect_fail "ESLint：max-params（6 个参数）" "$S_ESLINT" 'max-params' "$T" "$(doc '把六个数相加。' '@param a - 第一个数。' '@param b - 第二个数。' '@param c - 第三个数。' '@param d - 第四个数。' '@param e - 第五个数。' '@param f - 第六个数。')
export function probeSum(a: number, b: number, c: number, d: number, e: number, f: number): number {
  return a + b + c + d + e + f;
}
"
expect_fail "ESLint：no-console" "$S_ESLINT" 'no-console' "$T" "$(doc '打印输入值。')
export function probeLog(value: number): number {
  console.log(value);
  return value;
}
"
expect_fail "ESLint：直接调用 fetch（no-restricted-globals）" "$S_ESLINT" 'no-restricted-globals' "$T" "$(doc '绕过客户端直接请求。')
export function probeFetch(value: number): number {
  void fetch(\"/api/health\");
  return value;
}
"
expect_fail "ESLint：导出函数没有 TSDoc（jsdoc/require-jsdoc）" "$S_ESLINT" 'jsdoc/require-jsdoc' "$T" "export function probeNoDoc(value: number): number {
  return value;
}
"
expect_fail "ESLint：导出箭头函数没有 TSDoc（jsdoc/require-jsdoc）" "$S_ESLINT" 'jsdoc/require-jsdoc' "$T" "export const probeArrow = (value: number): number => value;
"
expect_fail "ESLint：TSDoc 缺 @sideEffects（jsdoc/require-tags）" "$S_ESLINT" 'sideEffects.*jsdoc/require-tags|jsdoc/require-tags' "$T" "/**
 * 返回输入值。
 *
 * @param value - 输入数字，无单位。
 * @returns 输入值。
 * @throws 无。
 * @timeSemantics 无。
 */
export function probeNoSide(value: number): number {
  return value;
}
"
expect_fail "ESLint（补充）：@timeSemantics 为空（jsdoc/match-description）" "$S_ESLINT" 'jsdoc/match-description' "$T" "/**
 * 返回输入值。
 *
 * @param value - 输入数字，无单位。
 * @returns 输入值。
 * @throws 无。
 * @sideEffects 无。
 * @timeSemantics
 */
export function probeEmptyTime(value: number): number {
  return value;
}
"
expect_fail "ESLint：未登记的标签（jsdoc/check-tag-names）" "$S_ESLINT" 'jsdoc/check-tag-names' "$T" "/**
 * 返回输入值。
 *
 * @param value - 输入数字，无单位。
 * @returns 输入值。
 * @throws 无。
 * @sideEffects 无。
 * @timeSemantics 无。
 * @unregisteredProbe 无。
 */
export function probeTag(value: number): number {
  return value;
}
"
expect_fail "豁免：不带规则名的 eslint-disable（no-unlimited-disable）" "$S_ESLINT" 'no-unlimited-disable' "$T" "/* eslint-disable */
$(doc '返回输入值。')
export function probeValue(value: number): number {
  return value;
}
"
expect_fail "豁免：不带理由的 eslint-disable-next-line（require-description）" "$S_ESLINT" 'eslint-comments/require-description' "$T" "$(doc '打印输入值。')
export function probeLog(value: number): number {
  // eslint-disable-next-line no-console
  console.log(value);
  return value;
}
"
expect_fail "豁免：多余的 eslint-disable（reportUnusedDisableDirectives）" "$S_ESLINT" 'Unused eslint-disable directive' "$T" "$(doc '返回输入值。')
export function probeValue(value: number): number {
  // eslint-disable-next-line no-console -- 理由：探针，这一行没有 console。
  return value;
}
"
expect_fail "豁免：@ts-ignore（ban-ts-comment）" "$S_ESLINT" 'ban-ts-comment' "$T" "$(doc '返回输入值。')
export function probeValue(value: number): number {
  // @ts-ignore
  return value;
}
"
expect_fail "豁免：不带说明的 @ts-expect-error（ban-ts-comment）" "$S_ESLINT" 'ban-ts-comment' "$T" "$(doc '返回输入值。')
export function probeValue(value: number): number {
  // @ts-expect-error
  const wrong: number = \"x\";
  return value + wrong;
}
"

# ---------- 3c. Prettier、Vitest ----------
expect_fail "Prettier：一处不合格式" "$S_PRETTIER" 'probe\.ts' "$T" "/** 探针常量。 */
export const probeValue:number=1
" no-format
expect_fail "Vitest：一个失败的断言" "$S_VITEST" 'FAIL|failed' "src/web/src/probe.test.ts" "import { expect, it } from \"vitest\";

it(\"验证契约：探针。断言失败时 make check 失败在 Vitest 那一步\", () => {
  expect(1 + 1).toBe(3);
});
"

# ---------- 3d. 后端 ----------
expect_fail "import-linter：rdp.infra 里 import fastapi" "$S_IMPORTS" 'BROKEN|broken' "src/rdp/infra/_probe.py" '"""探针（基础层）：违规试验用，试完删除。"""

from fastapi import FastAPI

__all__ = ["FastAPI"]
'

# ---------- 3e. node_modules 不存在 ----------
say ""
say "== 违规（补充）：src/web/node_modules 不存在，应在第一个前端步骤之前失败并提示"
mv src/web/node_modules "$OUT/node_modules.off"
run_check
say "  make check 退出码=$RC，最后一步：$STEP"
grep -n 'pnpm install --frozen-lockfile' "$OUT/check.txt" | sed 's/^/  输出：/'
if [ "$RC" -ne 0 ] && grep -q 'pnpm install --frozen-lockfile' "$OUT/check.txt" && ! grep -qE '^\[(8|9|10|11)/11\] ' "$OUT/check.txt"; then
  ok "前端步骤之前就失败，提示 pnpm install --frozen-lockfile，没有自动安装"
else
  bad "没有按约定失败"; tail -10 "$OUT/check.txt" | sed 's/^/  | /'
fi
[ -e src/web/node_modules ] && bad "make check 自己建了 node_modules"
rm -rf src/web/node_modules
mv "$OUT/node_modules.off" src/web/node_modules
restore_and_recheck

if [ -n "$WITH_B" ]; then
  expect_fail "契约脚本（W3）：src/rdp 里没有六项的公开函数 test_probe" "$S_CONTRACTS" 'test_probe' "src/rdp/infra/probe_contract.py" '"""探针（基础层）：W3 违规试验用，试完删除。"""


def test_probe() -> None:
    """只有一句职责。"""
'
  # 过期检查：给健康检查的响应模型加一个字段，不重新生成。
  say ""
  say "== 违规：过期检查（HealthResponse 加一个字段，不重新生成）"
  hf=$(grep -rl 'class HealthResponse' src/rdp/api)
  cp "$hf" "$OUT/health.bak"
  .venv/bin/python -I - "$hf" <<'PY'
import sys, re
p = sys.argv[1]
s = open(p, encoding="utf-8").read()
s = re.sub(r'(\n    status: Literal\["ok"\]\n)', r'\1    probe: int = 0\n', s, count=1)
open(p, "w", encoding="utf-8").write(s)
PY
  grep -n 'probe: int' "$hf" | sed 's/^/  改动：/'
  run_check
  say "  make check 退出码=$RC，最后一步：$STEP"
  grep -n 'make api-types' "$OUT/check.txt" | head -2 | sed 's/^/  输出：/'
  if [ "$RC" -ne 0 ] && grep -qE "$S_STALE" <<<"$STEP" && grep -q 'make api-types' "$OUT/check.txt"; then ok "失败在过期检查，提示 make api-types"; else bad "过期检查没有按约定失败"; tail -15 "$OUT/check.txt" | sed 's/^/  | /'; fi
  cp "$OUT/health.bak" "$hf"
  restore_and_recheck
fi

# ---------- 4. 不能失败 ----------
expect_pass "中文注释和 TSDoc、@throws 无" "src/web/src/probeOk.ts" "// 探针（前端）：验证中文全角标点不报错，试完删除。全角：，。：；（）！？「」、“”‘’《》【】——……

/**
 * 什么也不做，只用来验证中文 TSDoc 和“无”的写法（规则 4）。
 *
 * @param flag - 开关，取值 true 或 false。
 * @returns 原样返回 flag。
 * @throws 无
 * @sideEffects 无（不读也不写任何东西）。
 * @timeSemantics 无。
 */
export function probeNoop(flag: boolean): boolean {
  return flag;
}
"
expect_pass "带理由的单条豁免（eslint-disable-next-line 规则 -- 理由、@ts-expect-error 说明）" "$T" "$(doc '打印输入值。')
export function probeLog(value: number): number {
  // eslint-disable-next-line no-console -- 理由：探针，验证带理由的单条豁免能用。
  console.log(value);
  // @ts-expect-error 探针：验证带说明的 ts-expect-error 能用。
  const wrong: number = \"x\";
  return value + wrong;
}
"
expect_pass "tests/ 下没有六项的 test_*" "tests/test_probe_ok.py" '"""探针：违规试验用，试完删除。"""


def test_probe_ok() -> None:
    """验证契约：探针。tests/ 下的测试函数只写一句，契约脚本不报。"""
    assert len([1]) == 1
'

# ---------- 5. 钩子试验（验收第 9 条） ----------
hook_commit() { git commit -q -m "$1" >"$OUT/hook.txt" 2>&1; HRC=$?; }
CONSOLE_PROBE="$(doc '打印输入值。')
export function probeLog(value: number): number {
  console.log(value);
  return value;
}
"
OK_PROBE="$(doc '返回输入值。')
export function probeValue(value: number): number {
  return value;
}
"

say ""
say "== 钩子：提交一处前端违规（no-console），应被拒"
head0=$(git rev-parse HEAD)
printf '%s' "$CONSOLE_PROBE" >"$T"; fmt_file "$T"
git add -A
hook_commit "探针：前端违规提交"
say "  退出码=$HRC，HEAD $( [ "$(git rev-parse HEAD)" = "$head0" ] && echo 没变 || echo 变了 )"
grep -E 'no-console|检查失败' "$OUT/hook.txt" | head -3 | sed 's/^/  | /'
if [ "$HRC" -ne 0 ] && [ "$(git rev-parse HEAD)" = "$head0" ] && grep -q 'no-console' "$OUT/hook.txt"; then ok "提交被拒（ESLint no-console），没有产生新提交"; else bad "前端违规提交没被拦住"; fi

say ""
say "== 钩子：去掉违规后，同样的命令提交成功"
printf '%s' "$OK_PROBE" >"$T"; fmt_file "$T"
git add -A
hook_commit "探针：去掉违规后提交"
say "  退出码=$HRC"
grep -E "$STEP_RE" "$OUT/hook.txt" | tail -2 | sed 's/^/  | /'
if [ "$HRC" -eq 0 ] && [ "$(git rev-parse HEAD)" != "$head0" ]; then ok "提交成功（游离提交 $(git rev-parse --short HEAD)）"; else bad "提交没成功"; tail -10 "$OUT/hook.txt" | sed 's/^/  | /'; fi

say ""
say "== 钩子（D2）：只暂存规划文件（中文文件名），工作区里另有未暂存的违规，应跳过检查"
head1=$(git rev-parse HEAD)
git reset -q
mkdir -p docs/brief
printf '探针\n' >"docs/brief/9999-环境事实更新-探针.md"
printf '%s' "$CONSOLE_PROBE" >"$T"; fmt_file "$T"
git add "docs/brief/9999-环境事实更新-探针.md"
hook_commit "探针：只改规划文件"
say "  退出码=$HRC"
sed 's/^/  | /' "$OUT/hook.txt" | head -3
if [ "$HRC" -eq 0 ] && [ "$(git rev-parse HEAD)" != "$head1" ] && ! grep -qE "$STEP_RE" "$OUT/hook.txt"; then ok "跳过检查并提交成功，没跑 make check"; else bad "只改规划文件时没有跳过"; fi
git checkout -q -- "$T"

say ""
say "== 钩子（D2）：规划文件和代码一起暂存，代码有违规，应跑全量并被拒"
head2=$(git rev-parse HEAD)
printf '探针二\n' >>"docs/brief/9999-环境事实更新-探针.md"
printf '%s' "$CONSOLE_PROBE" >"$T"; fmt_file "$T"
git add -A
hook_commit "探针：规划文件加代码"
say "  退出码=$HRC"
grep -E 'no-console|检查失败' "$OUT/hook.txt" | head -2 | sed 's/^/  | /'
if [ "$HRC" -ne 0 ] && [ "$(git rev-parse HEAD)" = "$head2" ] && grep -qE "$STEP_RE" "$OUT/hook.txt"; then ok "跑了 make check，提交被拒"; else bad "混合暂存时没有跑全量检查"; fi

say ""
say "== 钩子（D2）：改名，把代码文件挪进 docs/，应跑全量"
git reset -q --hard "$head2"
git mv -f "$T" "docs/probe_moved.ts" 2>/dev/null
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
