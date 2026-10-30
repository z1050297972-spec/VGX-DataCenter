"""M1-07 副本演练的 Python 部分（由 replica-drill.sh 调用，不单独运行）。

只读写 <work_dir>/nav（副本）、<work_dir>/state、<work_dir>/tmp；开头断言路径不在 /mnt 之下，
并装一个审计钩子，拒绝任何指向 /mnt 的写类操作。
子命令 --child 是断电演练里被 SIGKILL 的"worker"，同一个文件，免得再放一个脚本。
"""

from __future__ import annotations

import argparse
import contextlib
import difflib
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

FAILURES: list[str] = []
DERIVED_KEYS = ("version", "view", "format", "entry_path")
DERIVED_LINE = re.compile(r'^[+-]\s*"(' + "|".join(DERIVED_KEYS) + r')":')
TEMP_NAME = re.compile(r"^\..*\.rdp-\d+-\d+\.tmp$")
STEP_TIMEOUT_S = 120


# --------------------------------------------------------------------------- 安全护栏


def under(path: str | os.PathLike[str], root: str) -> bool:
    absolute = os.path.abspath(os.fspath(path))
    return absolute == root or absolute.startswith(root.rstrip("/") + "/")


def install_guard(work: Path) -> None:
    """拒绝任何指向 /mnt 的写类操作（读不拦，副本里的链接目标在 /mnt 但我们从不跟随它们写）。"""
    write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC
    path_events = {
        "os.rename", "os.remove", "os.rmdir", "os.mkdir", "os.symlink", "os.link",
        "os.truncate", "os.chmod", "os.utime", "shutil.copyfile", "shutil.rmtree",
    }  # fmt: skip

    def hook(event: str, args: tuple[object, ...]) -> None:
        if event == "open":
            target, mode, flags = args[0], args[1], args[2]
            writing = (isinstance(flags, int) and flags & write_flags) or (
                isinstance(mode, str) and any(c in mode for c in "wax+")
            )
            if writing and isinstance(target, (str, bytes, os.PathLike)):
                text = os.fsdecode(target)
                if under(text, "/mnt"):
                    raise RuntimeError(f"护栏：拒绝写 /mnt 下的路径 {text}")
        elif event in path_events:
            for item in args:
                if isinstance(item, (str, bytes, os.PathLike)) and under(os.fsdecode(item), "/mnt"):
                    raise RuntimeError(f"护栏：拒绝 {event} 触碰 /mnt 下的路径 {os.fsdecode(item)}")

    sys.addaudithook(hook)


def assert_safe_paths(work: Path, nav: Path) -> None:
    for path in (work, nav):
        real = os.path.realpath(path)
        assert not under(real, "/mnt"), f"路径在 /mnt 之下：{real}"
    assert under(nav, str(work)), "nav 必须在 work_dir 之内"


@contextlib.contextmanager
def deadline(seconds: int, what: str):
    def fire(_signo: int, _frame: object) -> None:
        raise TimeoutError(f"{what} 超过 {seconds} 秒")

    previous = signal.signal(signal.SIGALRM, fire)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def check(ok: bool, label: str, detail: str = "") -> bool:
    print(f"    [{'通过' if ok else '失败'}] {label}" + (f"：{detail}" if detail else ""))
    if not ok:
        FAILURES.append(label + (f"（{detail}）" if detail else ""))
    return ok


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def noop() -> None:
    return None


# --------------------------------------------------------------------------- 比较工具


def classify(old: bytes, new: bytes) -> tuple[str, list[str]]:
    """返回 (种类, 摘要行)。种类：same / newline / derived / other。"""
    if old == new:
        return "same", []
    try:
        old_text, new_text = old.decode("utf-8"), new.decode("utf-8")
    except UnicodeDecodeError:
        return "other", ["原文件不是 UTF-8"]
    if old_text.rstrip("\n") == new_text.rstrip("\n"):
        return "newline", ["只差结尾换行"]
    changed = [
        line
        for line in difflib.unified_diff(
            old_text.splitlines(), new_text.splitlines(), lineterm="", n=0
        )
        if line[:1] in "+-" and not line.startswith(("+++", "---"))
    ]
    summary = [f"改动行 {len(changed)}（-{sum(c[0] == '-' for c in changed)} +{sum(c[0] == '+' for c in changed)}）"]
    summary += [c[:160] for c in changed[:8]]
    if len(changed) > 8:
        summary.append(f"... 另有 {len(changed) - 8} 行")
    if changed and all(DERIVED_LINE.match(line) for line in changed):
        keys = sorted({DERIVED_LINE.match(line).group(1) for line in changed})  # type: ignore[union-attr]
        return "derived", [f"只差推导字段 {keys}", *summary]
    return "other", summary


def task_and_source_counts(content: bytes) -> str:
    try:
        data = json.loads(content)
        parts = []
        if isinstance(data.get("tasks"), list):
            parts.append(f"tasks={len(data['tasks'])}")
        if "task_count" in data:
            parts.append(f"task_count={data['task_count']}")
        if isinstance(data.get("sources"), list):
            parts.append(f"sources={len(data['sources'])}")
        if isinstance(data.get("links"), list):
            parts.append(f"links={len(data['links'])}")
        return " ".join(parts)
    except (ValueError, AttributeError):
        return "?"


# --------------------------------------------------------------------------- (a)


def step_a(nav: Path) -> None:
    from rdp.jobs.datasets.reading import discover_entries, read_entry
    from rdp.jobs.datasets.types import View
    from rdp.jobs.navwrite.replica import generate_format_entry

    print("\n==== (a) 副本生成对拍（L8、L9）：规范副本 -> 按格式入口，对比副本里现有文件")
    catalog = discover_entries(nav)
    snapshots = [read_entry(nav, loc, checkpoint=noop) for loc in catalog.entries]
    tasks = {s.dataset_id: s for s in snapshots if s.location.view is View.TASK and s.dataset_id}
    formats = [s for s in snapshots if s.location.view is View.FORMAT]
    print(f"  按任务入口 {len(tasks)} 个（有 dataset_id 的），按格式入口 {len(formats)} 个，发现项 {len(catalog.findings)} 条")
    tally: Counter[str] = Counter()
    for current in formats:
        label = str(current.location.path)
        canonical = tasks.get(current.dataset_id)
        if canonical is None:
            print(f"  - {label}: 找不到 dataset_id={current.dataset_id} 的规范副本")
            tally["no_canonical"] += 1
            continue
        try:
            generated = generate_format_entry(canonical, current)
        except Exception as error:  # 如实报告，不中断
            print(f"  - {label}: 生成失败 {type(error).__name__}: {error}")
            tally["generate_error"] += 1
            continue
        kinds, notes = [], []
        for file in generated.files:
            actual = (nav / current.location.path / file.name).read_bytes()
            kind, summary = classify(actual, file.content)
            kinds.append(kind)
            counts = f"{task_and_source_counts(actual)} -> {task_and_source_counts(file.content)}"
            if file.name != "数据集信息.json":
                notes.append(f"      {file.name}: {kind_cn(kind)}；现有 -> 生成 {counts}")
            else:
                notes.append(f"      {file.name}: {kind_cn(kind)}")
            if kind in ("other", "derived") or (kind == "newline"):
                notes.extend("        " + s for s in summary[: 10 if kind == "other" else 2])
        overall = "other" if "other" in kinds else "derived" if "derived" in kinds else "newline" if "newline" in kinds else "same"
        tally[overall] += 1
        extra = ""
        if generated.omitted_source_ids:
            extra += f"；链接够不着的数据块 {len(generated.omitted_source_ids)} 个"
        if generated.omitted_task_references or generated.dropped_task_keys:
            extra += f"；子任务筛掉引用 {generated.omitted_task_references} 条、整体去掉任务 {len(generated.dropped_task_keys)} 个"
        print(f"  - {label}: {kind_cn(overall)}{extra}")
        if overall != "same" or extra:
            print("\n".join(notes))
    print("  汇总：" + "，".join(f"{kind_cn(k)} {v}" for k, v in sorted(tally.items())) + f"，共 {len(formats)} 个按格式入口")


def kind_cn(kind: str) -> str:
    return {
        "same": "相同",
        "derived": "只差 L10 推导字段",
        "newline": "只差结尾换行",
        "other": "其他差异",
        "no_canonical": "无规范副本",
        "generate_error": "生成失败",
    }.get(kind, kind)


# --------------------------------------------------------------------------- (b)


def step_b(nav: Path, work: Path) -> None:
    from rdp.jobs.navwrite.jsonio import dump_navigation_json, load_navigation_json

    print("\n==== (b) 原样写回（L11）：每份 JSON 读进来再写出到 work_dir/tmp/roundtrip")
    out_root = work / "tmp" / "roundtrip"
    tally: Counter[str] = Counter()
    others: list[tuple[str, list[str]]] = []
    for directory, subdirs, files in os.walk(nav, followlinks=False):
        subdirs.sort()
        for name in sorted(files):
            if not name.endswith(".json"):
                continue
            path = Path(directory) / name
            if path.is_symlink():
                tally["symlink_skipped"] += 1
                continue
            relative = path.relative_to(nav)
            original = path.read_bytes()
            try:
                written = dump_navigation_json(load_navigation_json(original))
            except Exception as error:
                tally["load_error"] += 1
                others.append((str(relative), [f"{type(error).__name__}: {error}"]))
                continue
            target = out_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(written)
            kind, summary = classify(original, written)
            tally[kind] += 1
            if kind != "same":
                others.append((str(relative), summary))
    total = sum(tally.values())
    print(f"  共 {total} 份：" + "，".join(f"{kind_cn(k) if k != 'load_error' else '读取失败'} {v}" for k, v in sorted(tally.items())))
    for relative, summary in others[:25]:
        print(f"  - {relative}")
        print("\n".join("      " + line for line in summary[:6]))
    if len(others) > 25:
        print(f"  ... 另有 {len(others) - 25} 份有差异未列出")


# --------------------------------------------------------------------------- (c)(d) 公共


def tree_state(root: Path) -> dict[str, str]:
    state: dict[str, str] = {}
    for directory, subdirs, files in os.walk(root, followlinks=False):
        subdirs.sort()
        for name in subdirs + files:
            path = Path(directory) / name
            rel = str(path.relative_to(root))
            if path.is_symlink():
                state[rel] = "link:" + os.readlink(path)
            elif path.is_dir():
                state[rel] = "dir"
            else:
                state[rel] = "file:" + sha(path.read_bytes())
    return state


def leftover_temp_files(nav: Path) -> list[str]:
    found = []
    for directory, subdirs, files in os.walk(nav, followlinks=False):
        for name in files + subdirs:
            if TEMP_NAME.match(name):
                found.append(str(Path(directory) / name))
    return found


def build_plan(nav: Path, dataset: str):
    """对 <dataset> 的按任务入口和全部按格式入口各三份 JSON，各构造一步"追加 drill_marker 键"的 write_file。"""
    from rdp.jobs.datasets.reading import discover_entries, read_entry
    from rdp.jobs.datasets.types import View
    from rdp.jobs.navwrite.jsonio import dump_navigation_json, load_navigation_json
    from rdp.jobs.navwrite.models import (
        FileImage,
        NavOperation,
        NavWritePlan,
        PreviewState,
        WriteFileStep,
    )

    locations = [e for e in discover_entries(nav).entries if e.dataset_name == dataset]
    locations.sort(key=lambda e: (e.view is not View.TASK, str(e.path)))  # 先规范副本，再按格式（ADR 0006）
    if not locations:
        raise SystemExit(f"副本里找不到数据集 {dataset}")
    ids = {read_entry(nav, e, checkpoint=noop).dataset_id for e in locations}
    ids.discard(None)
    steps = []
    for location in locations:
        for name in ("原始路径.json", "数据集信息.json", "子任务.json"):
            relative = f"{location.path}/{name}"
            before = (nav / relative).read_bytes()
            payload = load_navigation_json(before)
            payload["drill_marker"] = "m1-07-replica-drill"  # 新键追加在末尾，无害
            after = dump_navigation_json(payload)
            steps.append(
                WriteFileStep(
                    path=relative,
                    before=FileImage(exists=True, sha256=sha(before), size_bytes=len(before)),
                    after=FileImage(exists=True, sha256=sha(after), size_bytes=len(after)),
                    after_content=after.decode("utf-8"),
                )
            )
    plan = NavWritePlan(
        operation=NavOperation.REPOINT_DATASET,
        dataset_ids=tuple(sorted(str(i) for i in ids)),
        steps=tuple(steps),
        state=PreviewState(nav_root=str(nav), datasets=(), new_dataset=None),
    )
    return plan


def make_environment(work: Path, nav: Path):
    from rdp.infra.config import PlatformConfig
    from rdp.infra.db.connection import create_database_engine
    from rdp.infra.db.migration import migrate
    from rdp.infra.state import initialize_state, state_paths
    from rdp.jobs.navwrite.recovery import RecoveryDependencies
    from rdp.jobs.types import JobClock

    config = PlatformConfig(state_dir=work / "state", nav_root=nav)
    paths = state_paths(config, ())
    initialize_state(paths)
    migrate(paths, now=datetime.now(UTC))
    engine = create_database_engine(paths.database)
    clock = JobClock(lambda: datetime.now(UTC), time.monotonic)
    return paths, engine, RecoveryDependencies(engine, paths, nav, clock)


def run_child_and_kill(work: Path, plan_file: Path, nav: Path, kill_after: int, job_id: int) -> None:
    ready = work / "tmp" / f"ready-{job_id}"
    ready.unlink(missing_ok=True)
    log = work / "tmp" / f"child-{job_id}.log"
    command = [
        sys.executable, os.path.abspath(__file__), "--child",
        str(plan_file), str(nav), str(work / "state"), str(kill_after), str(ready), str(job_id),
    ]  # fmt: skip
    with log.open("wb") as stderr:
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=stderr)  # noqa: S603
        try:
            limit = time.monotonic() + 60
            while not ready.exists():
                if process.poll() is not None:
                    raise RuntimeError(f"子进程提前退出（{process.returncode}）：{log.read_text(errors='replace')[-600:]}")
                if time.monotonic() > limit:
                    raise TimeoutError("等子进程写到第 k 步超时")
                time.sleep(0.02)
            ready_text = ready.read_text(encoding="utf-8")
            process.kill()  # SIGKILL，没有清理机会
            code = process.wait(timeout=10)
            check(ready_text == "ready" and code == -9, f"子进程写完第 {kill_after} 步后被 SIGKILL", f"returncode={code}")
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)


def child_main(args: list[str]) -> None:
    from rdp.infra.config import PlatformConfig
    from rdp.infra.state import state_paths
    from rdp.jobs.navwrite.atomic import apply_plan, capture_before_images
    from rdp.jobs.navwrite.journal import write_journal
    from rdp.jobs.navwrite.models import NavWritePlan

    plan_file, nav_text, state_text, kill_text, ready_text, job_text = args
    plan = NavWritePlan.model_validate_json(Path(plan_file).read_text(encoding="utf-8"))
    nav, ready = Path(nav_text), Path(ready_text)
    job_id, kill_after = int(job_text), int(kill_text)
    paths = state_paths(PlatformConfig(state_dir=Path(state_text), nav_root=nav), ())
    write_journal(paths, plan, capture_before_images(nav, plan), job_id, datetime.now(UTC))
    real_replace, done = os.replace, [0]

    def replace(source, target, *a, **k):  # type: ignore[no-untyped-def]
        real_replace(source, target, *a, **k)
        done[0] += 1
        if done[0] >= kill_after:
            ready.write_text("ready", encoding="utf-8")
            time.sleep(120)  # 等父进程 kill -9

    os.replace = replace  # type: ignore[assignment]
    apply_plan(nav, plan, job_id, checkpoint=noop)
    ready.write_text("finished", encoding="utf-8")


# --------------------------------------------------------------------------- (c)


def step_c(nav: Path, work: Path, dataset: str) -> None:
    from rdp.infra.db.connection import session_scope
    from rdp.jobs.navwrite.changes import ChangeOutcome, read_change_record
    from rdp.jobs.navwrite.journal import journal_directory, list_journals
    from rdp.jobs.navwrite.marker import is_navigation_write_blocked
    from rdp.jobs.navwrite.recovery import JournalFate, recover_navigation_writes

    print(f"\n==== (c) 断电演练：对 {dataset} 的 6 个文件执行改写计划，第 k 步后 SIGKILL，再跑恢复")
    plan = build_plan(nav, dataset)
    paths_list = [s.path for s in plan.steps]
    print(f"  计划 {len(plan.steps)} 步，涉及编号 {list(plan.dataset_ids)}：")
    for index, path in enumerate(paths_list):
        print(f"    步 {index + 1}: {path}")
    if len(plan.steps) != 6:
        print(f"  注意：步骤数是 {len(plan.steps)} 而不是 6（该数据集的按格式入口个数不是 1）；仍按最后一步={len(plan.steps)} 演练")
    plan_file = work / "tmp" / "plan-c.json"
    plan_file.write_text(plan.model_dump_json(), encoding="utf-8")
    paths, engine, deps = make_environment(work, nav)
    try:
        before_hash = {p: sha((nav / p).read_bytes()) for p in paths_list}
        before_tree = tree_state(nav)
        last = len(plan.steps)
        for offset, k in enumerate(sorted({1, 3, 5, last})):
            if k > last:
                continue
            job_id = 101 + offset
            print(f"\n  -- k={k}（作业编号 {job_id}）")
            with deadline(STEP_TIMEOUT_S, f"k={k}"):
                run_child_and_kill(work, plan_file, nav, k, job_id)
                changed = sum(sha((nav / p).read_bytes()) != before_hash[p] for p in paths_list)
                check(changed == k, "kill 后恰有 k 个文件已变成后像", f"变了 {changed} 个，k={k}")
                journals = [j for j in list_journals(paths) if j.job_id == job_id]
                check(len(journals) == 1 and journals[0].complete, "kill 后写入日志在且完整")
                report = recover_navigation_writes(deps, checkpoint=noop)
                mine = [r for r in report.journals if r.job_id == job_id]
                check(len(mine) == 1 and mine[0].fate is JournalFate.ROLLED_BACK,
                      "恢复结论是 rolled_back", f"{[(r.job_id, r.fate.value, r.restored_count) for r in report.journals]}")
                check(all(sha((nav / p).read_bytes()) == before_hash[p] for p in paths_list), "6 个文件 sha256 全部等于前像")
                check(tree_state(nav) == before_tree, "整个副本树（文件哈希、链接目标、目录）等于演练前")
                leftovers = leftover_temp_files(nav)
                check(not leftovers, "没有临时文件残留", str(leftovers[:3]))
                check(not journal_directory(paths, job_id).exists(), "写入日志目录已清理")
                record = read_change_record(paths, job_id)
                check(record.outcome is ChangeOutcome.ROLLED_BACK_BY_RECOVERY, "变更记录 outcome=rolled_back_by_recovery", record.outcome.value)
                with session_scope(engine, read_only=True) as session:
                    check(not is_navigation_write_blocked(session), "没有设恢复失败标记")
    finally:
        engine.dispose()


# --------------------------------------------------------------------------- (d)


def step_d(nav: Path, work: Path, dataset: str) -> None:
    from rdp.infra.db.connection import session_scope
    from rdp.jobs.navwrite.journal import journal_directory
    from rdp.jobs.navwrite.marker import read_recovery_block
    from rdp.jobs.navwrite.recovery import JournalFate, recover_navigation_writes
    from rdp.jobs.navwrite.wiring import build_navigation_callbacks

    print("\n==== (d) 恢复失败：中途 kill，再把一个文件改成既非前像也非后像，跑恢复")
    plan = build_plan(nav, dataset)
    plan_file = work / "tmp" / "plan-d.json"
    plan_file.write_text(plan.model_dump_json(), encoding="utf-8")
    paths, engine, deps = make_environment(work, nav)
    job_id, kill_after = 900, min(3, len(plan.steps))
    try:
        paths_list = [s.path for s in plan.steps]
        before_hash = {p: sha((nav / p).read_bytes()) for p in paths_list}
        with deadline(STEP_TIMEOUT_S, "(d)"):
            run_child_and_kill(work, plan_file, nav, kill_after, job_id)
            victim = paths_list[kill_after - 2 if kill_after >= 2 else 0]  # 已写成后像的一步
            (nav / victim).write_bytes(b'{"tampered_by_drill": true}\n')
            print(f"    手工改坏: {victim}")
            report = recover_navigation_writes(deps, checkpoint=noop)
            mine = [r for r in report.journals if r.job_id == job_id]
            check(len(mine) == 1 and mine[0].fate is JournalFate.MISMATCH, "恢复结论是 mismatch", str([(r.job_id, r.fate.value) for r in report.journals]))
            check(report.blocked, "RecoveryReport.blocked 为真")
            listed = [m.path for r in mine for m in r.mismatches]
            check(victim in listed, "对不上的项里列出了被改坏的文件", str(listed))
            others = [p for p in paths_list if p != victim]
            check(all(sha((nav / p).read_bytes()) == before_hash[p] for p in others), "其余文件都已回到前像")
            check(journal_directory(paths, job_id).exists(), "写入日志保留供管理员核对")
            with session_scope(engine, read_only=True) as session:
                block = read_recovery_block(session)
            check(block is not None and job_id in block.job_ids, "恢复失败标记已设置并含该作业", str(block.job_ids if block else None))
            check(block is not None and any(i.path == victim for i in block.items), "标记里列出了该项")
            blocked_callback = build_navigation_callbacks(engine, paths, nav, deps.clock)[1]
            check(blocked_callback() is True, "navigation_blocked 回调为真（新的写作业被挡住）")
            for item in (block.items if block else ()):
                print(f"    对不上的项: 作业 {item.job_id} 步 {item.step_index} {item.path}\n      前像={item.expected_before} 后像={item.expected_after} 现状={item.actual}")
    finally:
        engine.dispose()
    print("\n  >>> 状态保留，供浏览器确认放行（不要在脚本里确认）：")
    print(f"      状态目录 : {paths.root}")
    print(f"      数据库   : {paths.database}")
    print(f"      副本导航层: {nav}")
    print(f"      写入日志 : {journal_directory(paths, job_id)}")


# --------------------------------------------------------------------------- main


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--child":
        child_main(sys.argv[2:])
        return 0
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--dataset", default="agibot_world_2026")
    args = parser.parse_args()
    work = Path(os.path.realpath(args.work_dir))
    nav = work / "nav"
    assert_safe_paths(work, nav)
    install_guard(work)
    if not nav.is_dir():
        print(f"副本不存在：{nav}")
        return 2
    for name, function in (
        ("a", lambda: step_a(nav)),
        ("b", lambda: step_b(nav, work)),
        ("c", lambda: step_c(nav, work, args.dataset)),
        ("d", lambda: step_d(nav, work, args.dataset)),
    ):
        try:
            with deadline(600, f"步骤 {name}"):
                function()
        except BaseException as error:  # 一步出错不挡后面的步骤
            if isinstance(error, KeyboardInterrupt):
                raise
            import traceback

            traceback.print_exc()
            FAILURES.append(f"步骤 {name} 异常：{type(error).__name__}: {error}")
    print("\n==== 汇总")
    if FAILURES:
        print(f"  {len(FAILURES)} 项检查失败或异常：")
        for item in FAILURES:
            print(f"    - {item}")
        return 1
    print("  (c)(d) 的全部检查通过；(a)(b) 只如实打印，请对照预期自行判断。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
