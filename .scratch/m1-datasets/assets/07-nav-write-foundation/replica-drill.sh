#!/usr/bin/env bash
# M1-07 真实导航层副本演练入口（验收 1）。由执行线在沙箱外运行。
#
# 用法：
#   bash replica-drill.sh <nav_root_source> <work_dir>
# 真实演练：
#   bash replica-drill.sh /mnt/datasets ~/.cache/rdp-drill/m1-07
# 可选环境变量：
#   WORKTREE       m1-07 工作目录，默认 ~/桌面/robot-data-platform.wt/m1-07-nav-write-foundation
#   DRILL_DATASET  断电演练用的数据集目录名，默认 agibot_world_2026（假导航层自测时改用别的名字）
#   DRILL_RESET=1  work_dir 已有上次的 nav/ state/ tmp/ 时，先删掉它们再开始
#
# 对 <nav_root_source> 只读（find、cp 读源）；只写 <work_dir>。
set -u
export LC_ALL=C

if [ "$#" -ne 2 ]; then
    sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'
    exit 2
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKTREE="${WORKTREE:-$HOME/桌面/robot-data-platform.wt/m1-07-nav-write-foundation}"
PY="$WORKTREE/.venv/bin/python"
SRC="$(realpath -e -- "$1")" || { echo "源目录不存在：$1" >&2; exit 2; }
WORK="$(realpath -m -- "$2")"
NAV="$WORK/nav"

[ -x "$PY" ] || { echo "找不到 $PY" >&2; exit 2; }
[ -d "$SRC" ] || { echo "源不是目录：$SRC" >&2; exit 2; }
case "$WORK/" in
    /mnt/*) echo "拒绝：work_dir 不能在 /mnt 之下：$WORK" >&2; exit 2 ;;
esac
case "$WORK/" in
    "$SRC"/*) echo "拒绝：work_dir 不能在源目录之内：$WORK" >&2; exit 2 ;;
esac
case "$SRC/" in
    "$WORK"/*) echo "拒绝：源目录不能在 work_dir 之内：$SRC" >&2; exit 2 ;;
esac
if [ "$WORK" = "/" ] || [ "$WORK" = "$HOME" ]; then
    echo "拒绝：work_dir 不能是 / 或家目录" >&2; exit 2
fi

mkdir -p -- "$WORK" || exit 2
if [ -e "$NAV" ] || [ -e "$WORK/state" ] || [ -e "$WORK/tmp" ]; then
    if [ "${DRILL_RESET:-0}" = "1" ]; then
        rm -rf -- "$NAV" "$WORK/state" "$WORK/tmp"
    else
        echo "work_dir 里已有上次的演练现场（nav/ state/ tmp/）。确认可丢弃后加 DRILL_RESET=1 重跑。" >&2
        exit 2
    fi
fi
mkdir -p -- "$WORK/lists" "$WORK/tmp" || exit 2

disk_sectors_written() {
    # /sys/block/<dev>/stat 的第 7 列 = 写入扇区数
    local dev="$1" file="/sys/block/$1/stat"
    if [ -r "$file" ]; then awk '{print $7}' "$file"; else echo "n/a"; fi
}

snapshot() {
    local tag="$1"
    find "$SRC" -printf '%p %T@ %s\n' | sort > "$WORK/lists/find-$tag.txt"
    echo "sda $(disk_sectors_written sda)" > "$WORK/lists/disk-$tag.txt"
    echo "sdb $(disk_sectors_written sdb)" >> "$WORK/lists/disk-$tag.txt"
}

echo "== 演练开始 $(date '+%F %T')"
echo "源（只读）: $SRC"
echo "work_dir  : $WORK"
echo "worktree  : $WORKTREE"

echo
echo "== [0] 跑前清单"
snapshot before
echo "清单行数: $(wc -l < "$WORK/lists/find-before.txt")"
cat "$WORK/lists/disk-before.txt"

echo
echo "== [1] 建副本（cp -a --no-dereference；解压样本/ 工具/ VGX_video/ 只建空目录）"
mkdir -p -- "$NAV" || exit 2
copy_failed=0
while IFS= read -r -d '' item; do
    name="$(basename -- "$item")"
    case "$name" in
        解压样本|工具|VGX_video)
            mkdir -p -- "$NAV/$name"
            echo "  空目录: $name"
            ;;
        *)
            if cp -a --no-dereference -- "$item" "$NAV/"; then
                echo "  复制  : $name"
            else
                echo "  复制失败: $name" >&2
                copy_failed=1
            fi
            ;;
    esac
done < <(find "$SRC" -mindepth 1 -maxdepth 1 -print0 | sort -z)
echo "副本里的文件/链接/目录数: $(find "$NAV" | wc -l)；其中软链接 $(find "$NAV" -type l | wc -l) 条"
if [ "$copy_failed" -ne 0 ]; then
    echo "副本没有建完整，停止。" >&2
    snapshot after
    exit 1
fi

echo
echo "== [2] Python 演练（a 副本生成对拍 / b 原样写回 / c 断电演练 / d 恢复失败）"
PYTHONPATH="$WORKTREE/src" PYTHONDONTWRITEBYTECODE=1 \
    timeout 1800 "$PY" "$HERE/replica_drill.py" \
    --work-dir "$WORK" --dataset "${DRILL_DATASET:-agibot_world_2026}"
PY_STATUS=$?
echo "Python 演练退出码: $PY_STATUS"

echo
echo "== [3] 跑后清单与比对"
snapshot after
verdict=0
if diff -q "$WORK/lists/find-before.txt" "$WORK/lists/find-after.txt" > /dev/null; then
    echo "源清单（路径 mtime 大小）跑前跑后逐字节相同：是"
else
    echo "源清单跑前跑后不同：是的，差异如下（前 40 行）"
    diff "$WORK/lists/find-before.txt" "$WORK/lists/find-after.txt" | head -40
    verdict=1
fi
echo "磁盘写入扇区（第 7 列）前 -> 后:"
for dev in sda sdb; do
    b="$(grep "^$dev " "$WORK/lists/disk-before.txt" | cut -d' ' -f2)"
    a="$(grep "^$dev " "$WORK/lists/disk-after.txt" | cut -d' ' -f2)"
    if [[ "$b" =~ ^[0-9]+$ && "$a" =~ ^[0-9]+$ ]]; then
        echo "  $dev: $b -> $a（增加 $((a - b))；系统盘上的状态目录写入和别的进程也会让它增加，数据盘应当不变）"
    else
        echo "  $dev: $b -> $a"
    fi
done
echo "清单文件: $WORK/lists/find-before.txt  find-after.txt"

echo
echo "== 演练结束 $(date '+%F %T')；Python 退出码 $PY_STATUS，源清单比对 $([ $verdict -eq 0 ] && echo 通过 || echo 不一致)"
if [ "$PY_STATUS" -ne 0 ] || [ "$verdict" -ne 0 ]; then exit 1; fi
exit 0
