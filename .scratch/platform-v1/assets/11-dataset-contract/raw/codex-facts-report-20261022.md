采集日期：2026-10-22。全程只读，脚本从标准输入执行，结果仅输出到标准输出；未创建、修改或删除文件。以下耗时均为本次观测值。

**1. 全量扫描耗时**

附录 A 的 `nav_inventory.py` 连续运行两次，均成功完成。第一次是否为冷缓存：**看不出**；未清理缓存。

| 运行 | 墙钟时间 | 退出码 |
|---|---:|---:|
| 第一次 | 8.708279 s | 0 |
| 第二次 | 8.515105 s | 0 |

产生上述数字的命令如下。原脚本完整提取后通过标准输入传给 `python3 -I - /mnt/datasets`，输出丢弃到 `/dev/null`；计时包括子进程启动和限制命令的开销。

```bash
python3 -I - <<'PY'
from pathlib import Path
import subprocess, time

text = Path('docs/research/导航层盘点.md').read_text()
appendix = text.split('## 附录 A：', 1)[1]
script = appendix.split('```python\n', 1)[1].split('\n```', 1)[0]

for run in (1, 2):
    start = time.monotonic()
    p = subprocess.run(
        ['timeout', '1800', 'ionice', '-c3', 'nice', '-n19',
         'python3', '-I', '-', '/mnt/datasets'],
        input=script, text=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    elapsed = time.monotonic() - start
    print({
        'run': run,
        'seconds': round(elapsed, 6),
        'returncode': p.returncode,
        'status': '超时（>1800 s）' if p.returncode == 124 else '完成',
        'stderr': p.stderr,
    }, flush=True)
PY
```

**2. 每个数据集现算大小的耗时**

实际读到 **35 个数据集、36 个 root**。要求的四类命令耗时合计 **613.220344 s**；加上按块占用补测后为 **636.641050 s**，全部成功，无超时；只有 `agibot_world_2026` 与 JSON 大小快照相差超过 1%。

本机 `du --help` 原文确认：

```text
-b, --bytes                equivalent to '--apparent-size --block-size=1'
```

因此，要求的 `du -sb --apparent-size` 和 `du -sb` **都统计表观大小**。两条均已执行，并补测 `du -s -B1` 获取按块占用字节数。

下表使用以下命令编号，`root` 为对应行的完整路径：

```bash
# A：表观大小
timeout 1800 ionice -c3 nice -n19 du -sb --apparent-size -- "$root"

# B：同样是表观大小
timeout 1800 ionice -c3 nice -n19 du -sb -- "$root"

# C：补测按块占用，以字节输出
timeout 1800 ionice -c3 nice -n19 du -s -B1 -- "$root"

# F：条目数，包含根目录、普通文件、目录和软链接
timeout 1800 ionice -c3 nice -n19 bash -o pipefail -c \
  'find "$1" -xdev \( -type f -o -type d -o -type l \) | wc -l' \
  bash "$root"

# P：未完成下载标记；按 NUL 分隔统计，保留 find 返回的前五条
timeout 1800 ionice -c3 nice -n19 \
  find "$root" -xdev \( -name '*.aria2' -o -name '*.incomplete' \) -print0
```

所有 root 的 A、B 字节数完全相同，合并显示。单项时间保留三位小数；时间列依次为 **A / B / C / F / P**，单位秒。

| dataset_id | 数据集名 | root | 条目数 F | A＝B 字节数 | C 按块字节数 | A / B / C / F / P 耗时（s） |
|---|---|---|---:|---:|---:|---|
| dataset-01 | aloha_mobile_cabinet | `/mnt/dataset1/aloha/aloha_mobile_cabinet` | 26 | 1741647811 | 1741733888 | 0.103 / 0.102 / 0.103 / 0.103 / 0.103 |
| dataset-02 | aloha_mobile_chair | `/mnt/dataset1/aloha/aloha_mobile_chair` | 26 | 2164407987 | 2164498432 | 0.103 / 0.103 / 0.103 / 0.103 / 0.103 |
| dataset-03 | aloha_mobile_elevator | `/mnt/dataset1/aloha/aloha_mobile_elevator` | 23 | 583518420 | 583581696 | 0.102 / 0.102 / 0.103 / 0.103 / 0.103 |
| dataset-04 | aloha_mobile_rigid_multi_pick | `/mnt/dataset1/aloha/aloha_mobile_rigid_multi_pick` | 260 | 4483225755 | 4483780608 | 0.103 / 0.102 / 0.103 / 0.102 / 0.102 |
| dataset-05 | aloha_mobile_shrimp | `/mnt/dataset1/aloha/aloha_mobile_shrimp` | 28 | 1318204594 | 1318285312 | 0.103 / 0.103 / 0.103 / 0.103 / 0.103 |
| dataset-06 | aloha_mobile_wash_pan | `/mnt/dataset1/aloha/aloha_mobile_wash_pan` | 24 | 1136190479 | 1136267264 | 0.103 / 0.103 / 0.102 / 0.102 / 0.102 |
| dataset-07 | aloha_mobile_wipe_wine | `/mnt/dataset1/aloha/aloha_mobile_wipe_wine` | 24 | 1298533975 | 1298616320 | 0.103 / 0.102 / 0.103 / 0.103 / 0.103 |
| dataset-08 | aloha_static_towel | `/mnt/dataset1/aloha/aloha_static_towel` | 28 | 591690184 | 591785984 | 0.103 / 0.103 / 0.103 / 0.103 / 0.103 |
| dataset-09 | cmu_stretch | `/mnt/dataset1/cmu_stretch` | 17 | 40425176 | 40476672 | 0.103 / 0.103 / 0.103 / 0.103 / 0.103 |
| dataset-10 | cobotmagic_table_rearrange | `/mnt/dataset1/cobotmagic_table_rearrange` | 21 | 297631774 | 297705472 | 0.102 / 0.102 / 0.103 / 0.103 / 0.103 |
| dataset-11 | droid_100 | `/mnt/dataset1/droid_100` | 23 | 464033001 | 464105472 | 0.102 / 0.103 / 0.103 / 0.103 / 0.103 |
| dataset-12 | high_quality_folding | `/mnt/dataset1/high_quality_folding` | 572 | 90174586200 | 90176348160 | 0.102 / 0.103 / 0.103 / 0.103 / 0.103 |
| dataset-13 | jaco_play | `/mnt/dataset1/jaco_play` | 20 | 428865184 | 428933120 | 0.103 / 0.103 / 0.103 / 0.103 / 0.103 |
| dataset-14 | libero_10 | `/mnt/dataset1/libero_v3/libero_10` | 23 | 631143389 | 631214080 | 0.103 / 0.103 / 0.103 / 0.103 / 0.103 |
| dataset-15 | libero_90 | `/mnt/dataset1/libero_v3/libero_90` | 54 | 2590036232 | 2590158848 | 0.103 / 0.103 / 0.103 / 0.103 / 0.103 |
| dataset-16 | libero_goal | `/mnt/dataset1/libero_v3/libero_goal` | 18 | 333831480 | 333893632 | 0.103 / 0.103 / 0.103 / 0.103 / 0.103 |
| dataset-17 | libero_object | `/mnt/dataset1/libero_v3/libero_object` | 22 | 536960443 | 537026560 | 0.103 / 0.103 / 0.103 / 0.103 / 0.103 |
| dataset-18 | libero_spatial | `/mnt/dataset1/libero_v3/libero_spatial` | 19 | 365710957 | 365768704 | 0.103 / 0.102 / 0.103 / 0.102 / 0.103 |
| dataset-19 | mobile_so100_clean_trash | `/mnt/dataset1/mobile_so100_clean_trash` | 15 | 113623206 | 113672192 | 0.103 / 0.103 / 0.103 / 0.103 / 0.103 |
| dataset-20 | nyu_door_opening | `/mnt/dataset1/nyu_door_opening` | 17 | 396500626 | 396550144 | 0.103 / 0.103 / 0.103 / 0.103 / 0.103 |
| dataset-21 | robocasa_gr1_tabletop | `/mnt/dataset1/robocase/robocasa_gr1_tabletop` | 27 | 2595979824 | 2596073472 | 0.103 / 0.103 / 0.103 / 0.103 / 0.102 |
| dataset-22 | robocasa_target_human_unified | `/mnt/dataset1/robocase/robocasa_target_human_unified` | 1012 | 188394469098 | 188396634112 | 0.103 / 0.103 / 0.103 / 0.103 / 0.102 |
| dataset-23 | robotwin_unified | `/mnt/dataset1/robotwin_unified` | 483 | 79475158565 | 79476269056 | 0.103 / 0.103 / 0.103 / 0.103 / 0.103 |
| dataset-24 | tidybot_lerobot | `/mnt/dataset1/tidybot_lerobot` | 18 | 104453442 | 104513536 | 0.103 / 0.103 / 0.103 / 0.103 / 0.103 |
| dataset-25 | umi_bimanual_dish_washing | `/mnt/dataset1/umi_bimanual_dish_washing` | 27 | 1569839681 | 1569918976 | 0.103 / 0.103 / 0.103 / 0.103 / 0.102 |
| dataset-26 | unitreeh1_fold_clothes | `/mnt/dataset1/unitreeh1_fold_clothes` | 21 | 965910125 | 965976064 | 0.102 / 0.102 / 0.103 / 0.103 / 0.103 |
| dataset-27 | utokyo_pr2_fridge | `/mnt/dataset1/utokyo_pr2/utokyo_pr2_fridge` | 17 | 30666659 | 30715904 | 0.103 / 0.103 / 0.103 / 0.103 / 0.103 |
| dataset-28 | utokyo_pr2_tabletop | `/mnt/dataset1/utokyo_pr2/utokyo_pr2_tabletop` | 17 | 42448516 | 42500096 | 0.103 / 0.103 / 0.103 / 0.103 / 0.103 |
| dataset-29 | R1_lite_table_withdrawing_lerobot | `/mnt/dataset2/R1_lite_table_withdrawing_lerobot` | 93 | 16319210440 | 16319537152 | 0.103 / 0.103 / 0.103 / 0.103 / 0.103 |
| dataset-30 | agibot_world_2026 | `/mnt/dataset1/agibot_world_2026` | 1437 | 13216127618578 | 13209940496384 | 0.103 / 0.103 / 0.102 / 0.103 / 0.103 |
| dataset-31 | agibot_world_alpha | `/mnt/dataset2/agibot_world_alpha` | 7533756 | 8983166078898 | 8986840514560 | 481.122 / 105.582 / 19.818 / 1.605 / 2.807 |
| dataset-32 | EgoProStandard | `/mnt/dataset1/EgoProStandard` | 10254 | 3600611153073 | 3600644558848 | 0.203 / 0.103 / 0.103 / 0.103 / 0.103 |
| dataset-32 | EgoProStandard | `/mnt/dataset2/EgoProStandard` | 14218 | 5798552648860 | 5798613913600 | 0.303 / 0.102 / 0.103 / 0.103 / 0.103 |
| dataset-33 | EgoProDemo | `/mnt/dataset2/EgoProDemo` | 14852 | 119642823842 | 119688495104 | 4.005 / 0.103 / 0.103 / 0.103 / 0.103 |
| dataset-34 | galaxea_open_world | `/mnt/dataset2/galaxea_open_world` | 20265 | 2862337850078 | 2862386540544 | 3.605 / 0.103 / 0.103 / 0.103 / 0.103 |
| dataset-35 | R1_lite_table_withdrawing_mcap | `/mnt/dataset2/R1_lite_table_withdrawing_mcap` | 404 | 130810718336 | 130812092416 | 0.103 / 0.103 / 0.103 / 0.103 / 0.103 |

测量按 `dataset_id` 顺序进行，每个 root 内依次执行 A、B、C、F、P。后执行的命令可能受前序扫描的缓存影响，未做缓存清理。

耗时汇总如下，使用下方采集脚本记录的六位小数计算：

| 范围 | 耗时（s） |
|---|---:|
| 全部 root：A | 492.425928 |
| 全部 root：B | 109.180114 |
| 全部 root：C，补测 | 23.420706 |
| 全部 root：F | 5.208147 |
| 全部 root：P | 6.406155 |
| 原要求四类命令 A＋B＋F＋P | 613.220344 |
| 含补测的五类命令合计 | 636.641050 |
| 整个采集脚本墙钟时间，含导航 JSON 读取及输出 | 636.651687 |

按每个 root 的命令耗时合计排序，最慢的五个如下；是否包含补测 C 不改变本次排序。

| dataset_id | root | A＋B＋F＋P（s） | 含 C 合计（s） |
|---|---|---:|---:|
| dataset-31 | `/mnt/dataset2/agibot_world_alpha` | 591.115384 | 610.933868 |
| dataset-33 | `/mnt/dataset2/EgoProDemo` | 4.314305 | 4.417115 |
| dataset-34 | `/mnt/dataset2/galaxea_open_world` | 3.913974 | 4.016834 |
| dataset-32 | `/mnt/dataset2/EgoProStandard` | 0.611256 | 0.714217 |
| dataset-32 | `/mnt/dataset1/EgoProStandard` | 0.511538 | 0.614286 |

未完成下载标记由命令 P 产生，匹配 `.aria2` 或 `.incomplete`，没有限定文件类型：

| dataset_id | root | 匹配数 |
|---|---|---:|
| dataset-30 | `/mnt/dataset1/agibot_world_2026` | 1 |
| dataset-33 | `/mnt/dataset2/EgoProDemo` | 8 |
| 其余所有 root | 见上表 | 各 0 |

`agibot_world_2026` 的返回路径：

```text
/mnt/dataset1/agibot_world_2026/ReinforcementLearning/Industry/task_6767/1648454_1698836.tar.gz.aria2
```

`EgoProDemo` 按 `find` 返回顺序的前五条：

```text
/mnt/dataset2/EgoProDemo/.cache/huggingface/download/EgoProStandard-body/lerobot/Portion Nuts into Small Resealable Bags/35a5a6ce-4ccb-45c1-846c-3bc1b256e897/videos/observation.images.right_wrist/chunk-000/7wRApOINIM-BFSSFbGUIdqNun_Q=.acd3bd124f18a42fe3f99760860dd386488e28e5f9d7b95089ed1a1a92919694.bdd7e483.incomplete
/mnt/dataset2/EgoProDemo/.cache/huggingface/download/EgoProStandard-body/lerobot/Portion Nuts into Small Resealable Bags/bb0454f1-86af-4908-a739-e32a414c5488/videos/observation.images.left_wrist/chunk-000/7wRApOINIM-BFSSFbGUIdqNun_Q=.a3a97db376690f987b1bf4cb7a1ede548c1fda0f8057ebd264cfa017fd5c5932.01309a48.incomplete
/mnt/dataset2/EgoProDemo/.cache/huggingface/download/EgoProStandard-body/lerobot/Portion Nuts into Small Resealable Bags/bb0454f1-86af-4908-a739-e32a414c5488/videos/observation.images.head_left/chunk-000/7wRApOINIM-BFSSFbGUIdqNun_Q=.0bbff61af1902f66ef934a912c28459ea96c17f680050131d0a8959e33b615dd.74f04b4b.incomplete
/mnt/dataset2/EgoProDemo/.cache/huggingface/download/EgoProStandard-body/lerobot/Portion Nuts into Small Resealable Bags/bb0454f1-86af-4908-a739-e32a414c5488/videos/observation.images.right_wrist/chunk-000/7wRApOINIM-BFSSFbGUIdqNun_Q=.4123a89e542fd35989d5f3b96831adffa0d2707e6510b2fbaba2d55b492745b9.39100ccd.incomplete
/mnt/dataset2/EgoProDemo/.cache/huggingface/download/EgoProStandard-body/lerobot/Post Notice Announcement_plum/089f873e-79ed-4edf-bd47-48192a0dbc5c/data/chunk-000/Rk5xtNxR079Ysk7EiCU6jR-aXfw=.cf1cc25f733e0856b4a406258e71088762a4a273edb401e8cd4b2481ae4b3566.06d60156.incomplete
```

与 JSON 第四项“数据大小”对比时，提取第一个 `（N B；`，按数据集合计各 root。差值定义为“当前值－JSON 值”，百分比以 JSON 值为分母。超过 1% 的结果只有：

| dataset_id／数据集 | 口径 | JSON 字节数 | 当前字节数 | 差值（B） | 差异 |
|---|---|---:|---:|---:|---:|
| dataset-30／agibot_world_2026 | A、B 表观大小 | 13872572434599 | 13216127618578 | -656444816021 | -4.731962% |
| dataset-30／agibot_world_2026 | C 按块占用，补充比较 | 13872572434599 | 13209940496384 | -662631938215 | -4.776561% |

本节全部原始数字、计时、汇总及差异来自以下采集命令。控制进程只读取系统盘上的导航 JSON；每条访问数据盘的子命令分别施加优先级和超时限制。

<details>
<summary>完整采集命令</summary>

```bash
python3 -I - <<'PY'
import json, pathlib, re, subprocess, time, shlex

start_all = time.monotonic()
datasets = []
for path in sorted(pathlib.Path('/mnt/datasets/按任务').glob('*/原始路径.json')):
    data = json.loads(path.read_text())
    info = json.loads(path.with_name('数据集信息.json').read_text())
    field = next(f for f in info['fields'] if f['number'] == 4)
    match = re.search(r'（([\d,]+) B；', field['value_markdown'])
    data['snapshot_bytes'] = int(match[1].replace(',', '')) if match else None
    datasets.append(data)
datasets.sort(key=lambda d: d['dataset_id'])
print(json.dumps({
    'datasets': len(datasets),
    'roots': sum(len(d['dataset_roots']) for d in datasets),
}, ensure_ascii=False), flush=True)
rows = []

def run(args):
    start = time.monotonic()
    p = subprocess.run(
        ['timeout', '1800', 'ionice', '-c3', 'nice', '-n19', *args],
        capture_output=True,
    )
    return {
        'seconds': round(time.monotonic()-start, 6),
        'rc': p.returncode,
        'status': '超时（>1800 s）' if p.returncode == 124
                  else ('ok' if p.returncode == 0 else 'error'),
        'out': p.stdout.decode(errors='replace'),
        'err': p.stderr.decode(errors='replace'),
    }

for data in datasets:
    for root in data['dataset_roots']:
        row = {
            'id': data['dataset_id'],
            'name': data['dataset_name'],
            'root': root,
            'snapshot_bytes': data['snapshot_bytes'],
        }
        for label, args in [
            ('A', ['du', '-sb', '--apparent-size', '--', root]),
            ('B', ['du', '-sb', '--', root]),
            ('C', ['du', '-s', '-B1', '--', root]),
            ('F', ['bash', '-o', 'pipefail', '-c',
                   'find "$1" -xdev \\( -type f -o -type d -o -type l \\) | wc -l',
                   'bash', root]),
            ('P', ['find', root, '-xdev', '(',
                   '-name', '*.aria2', '-o', '-name', '*.incomplete',
                   ')', '-print0']),
        ]:
            result = run(args)
            out = result.pop('out')
            if label == 'P':
                paths = out.split('\0')
                if paths and paths[-1] == '':
                    paths.pop()
                result['count'] = len(paths)
                result['first5'] = paths[:5]
            else:
                result['value'] = (
                    int(out.split()[0])
                    if result['rc'] == 0 and out.split() else None
                )
            row[label] = result
        row['total_seconds'] = round(
            sum(row[k]['seconds'] for k in ['A','B','C','F','P']), 6
        )
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)

totals = {
    k: round(sum(r[k]['seconds'] for r in rows), 6)
    for k in ['A','B','C','F','P']
}
print(json.dumps({
    'totals_seconds': totals,
    'sum_seconds': round(sum(totals.values()), 6),
    'wall_seconds': round(time.monotonic()-start_all, 6),
    'top5': sorted(
        [{'id': r['id'], 'root': r['root'], 'seconds': r['total_seconds']}
         for r in rows],
        key=lambda r: r['seconds'], reverse=True,
    )[:5],
}, ensure_ascii=False), flush=True)

for data in datasets:
    same = [r for r in rows if r['id'] == data['dataset_id']]
    snapshot = data['snapshot_bytes']
    for k in ['A','B','C']:
        if snapshot and all(r[k]['rc'] == 0 for r in same):
            measured = sum(r[k]['value'] for r in same)
            delta = measured - snapshot
            if abs(delta) / snapshot > 0.01:
                print(json.dumps({
                    'difference': k,
                    'id': data['dataset_id'],
                    'name': data['dataset_name'],
                    'snapshot_bytes': snapshot,
                    'measured_bytes': measured,
                    'delta_bytes': delta,
                    'delta_pct': 100*delta/snapshot,
                }, ensure_ascii=False), flush=True)
PY
```

</details>

**3. LeRobot source 的 `meta/info.json`**

共遍历 **494 条** LeRobot source，**491 条存在** `meta/info.json`，**3 条不存在**，均属于 `agibot_world_alpha`；整个遍历耗时 **0.876540 s**，没有其他读取或 JSON 解析错误。`EgoProDemo` 的 `robot_type` 为 JSON `null`，FPS 有 **25 个**不同取值。

数据集名称与第二节的 `dataset_id` 对应。`∅` 表示未取得值；字符串 `"unknown"`、JSON `null` 均保留原义。FPS 单位为帧／秒。

| dataset_id | LeRobot source 数 | info.json 存在数 | robot_type 集合 | fps 集合，最多十个 | codebase_version 集合 |
|---|---:|---:|---|---|---|
| dataset-01 | 1 | 1 | `aloha` | 50 | `v3.0` |
| dataset-02 | 1 | 1 | `aloha` | 50 | `v3.0` |
| dataset-03 | 1 | 1 | `aloha` | 50 | `v3.0` |
| dataset-04 | 1 | 1 | `aloha` | 50 | `v3.0` |
| dataset-05 | 1 | 1 | `aloha` | 50 | `v3.0` |
| dataset-06 | 1 | 1 | `aloha` | 50 | `v3.0` |
| dataset-07 | 1 | 1 | `aloha` | 50 | `v3.0` |
| dataset-08 | 1 | 1 | `aloha` | 50 | `v3.0` |
| dataset-09 | 1 | 1 | `stretch` | 5 | `v3.0` |
| dataset-10 | 1 | 1 | `aloha` | 10 | `v3.0` |
| dataset-11 | 1 | 1 | `franka` | 15 | `v3.0` |
| dataset-12 | 1 | 1 | `openarms_follower` | 30 | `v3.0` |
| dataset-13 | 1 | 1 | `"unknown"` | 10 | `v3.0` |
| dataset-14 | 1 | 1 | `franka` | 20 | `v3.0` |
| dataset-15 | 1 | 1 | `franka` | 20 | `v3.0` |
| dataset-16 | 1 | 1 | `franka` | 20 | `v3.0` |
| dataset-17 | 1 | 1 | `franka` | 20 | `v3.0` |
| dataset-18 | 1 | 1 | `franka` | 20 | `v3.0` |
| dataset-19 | 1 | 1 | `mobile_so100` | 30 | `v3.0` |
| dataset-20 | 1 | 1 | `"unknown"` | 3 | `v3.0` |
| dataset-21 | 1 | 1 | `robomimic` | 20 | `v3.0` |
| dataset-22 | 1 | 1 | `robocasa` | 20 | `v3.0` |
| dataset-23 | 1 | 1 | `aloha` | 30 | `v3.0` |
| dataset-24 | 1 | 1 | `"unknown"` | 10 | `v3.0` |
| dataset-25 | 1 | 1 | `generic_robot` | 30 | `v3.0` |
| dataset-26 | 1 | 1 | `"unknown"` | 50 | `v3.0` |
| dataset-27 | 1 | 1 | `"unknown"` | 5 | `v3.0` |
| dataset-28 | 1 | 1 | `"unknown"` | 5 | `v3.0` |
| dataset-29 | 1 | 1 | `galaxea_r1lite` | 30 | `v3.0` |
| dataset-30 | 2 | 2 | `g2a` | 30 | `v2.1`, `v3.0` |
| dataset-31 | 3 | 0 | ∅ | ∅ | ∅ |
| dataset-32 | 0 | 0 | ∅ | ∅ | ∅ |
| dataset-33 | 233 | 233 | `null` | 24.999, 25.0, 25.001, 25.003, 25.004, 29.999, 30.0, 30.001, 30.002, 30.003；共 25 种 | `v3.0` |
| dataset-34 | 227 | 227 | `r1lite`, `r1pro` | 15 | `v3.0` |
| dataset-35 | 0 | 0 | ∅ | ∅ | ∅ |
| **合计** | **494** | **491** | — | — | — |

不存在 `meta/info.json` 的全部 source 如下。检查路径为每行 `direct_path` 后追加 `/meta/info.json`。

| dataset_id | source_id | direct_path |
|---|---|---|
| dataset-31 | `src_0ce579c7bddf` | `/mnt/dataset2/agibot_world_alpha/lerobot_v2_output/agibotworld/agibotworld/pickup_items_in_the_supermarket__task_327` |
| dataset-31 | `src_2a2c94e25231` | `/mnt/dataset2/agibot_world_alpha/lerobot_v2_output/agibotworld/agibotworld/pickup_items_in_the_supermarket__task_327_v21` |
| dataset-31 | `src_489eb4dc26b6` | `/mnt/dataset2/agibot_world_alpha/lerobot_v2_output/agibotworld/agibotworld/pickup_items_in_the_supermarket__task_327_v21_old` |

产生本节全部数字与集合的命令如下。计时从导航 JSON 遍历前开始，到全部 source 检查及集合汇总结束；不含最后打印结果的时间。此项在第二节扫描完成后执行。

<details>
<summary>完整采集命令</summary>

```bash
timeout 1800 ionice -c3 nice -n19 python3 -I - <<'PY'
import json, pathlib, time

start = time.monotonic()
rows, missing, errors = [], [], []
for path in sorted(pathlib.Path('/mnt/datasets/按任务').glob('*/原始路径.json')):
    data = json.loads(path.read_text())
    sources = [s for s in data['sources'] if s['format'] == 'lerobot']
    row = {
        'id': data['dataset_id'],
        'name': data['dataset_name'],
        'sources': len(sources),
        'exists': 0,
    }
    values = {k: set() for k in ['robot_type','fps','codebase_version']}
    for source in sources:
        info_path = pathlib.Path(source['direct_path']) / 'meta/info.json'
        try:
            info_path.stat()
        except FileNotFoundError:
            missing.append({
                'id': data['dataset_id'],
                'source_id': source['source_id'],
                'direct_path': source['direct_path'],
            })
            continue
        except OSError as exc:
            errors.append({'path': str(info_path), 'error': str(exc)})
            continue
        row['exists'] += 1
        try:
            info = json.loads(info_path.read_text())
            for key in values:
                value = info[key] if key in info else '<字段缺失>'
                values[key].add(
                    json.dumps(value, ensure_ascii=False, sort_keys=True)
                )
        except (OSError, ValueError) as exc:
            errors.append({'path': str(info_path), 'error': str(exc)})
    for key, val in values.items():
        all_values = [json.loads(v) for v in sorted(val)]
        row[key] = all_values[:10] if key == 'fps' else all_values
        row[key + '_distinct'] = len(all_values)
    rows.append(row)

elapsed = time.monotonic() - start
for row in sorted(rows, key=lambda r: r['id']):
    print(json.dumps(row, ensure_ascii=False))
print(json.dumps({
    'source_total': sum(r['sources'] for r in rows),
    'exists_total': sum(r['exists'] for r in rows),
    'missing_count': len(missing),
    'missing_first20': missing[:20],
    'errors': errors,
    'seconds': round(elapsed, 6),
}, ensure_ascii=False))
PY
```

</details>

**4. 挂载信息**

当前沙箱的挂载命名空间中，两块数据盘分别是 `/dev/sda`、`/dev/sdb`，文件系统均为 `ext4`，挂载选项为只读。`/mnt/dataset1`、`/mnt/dataset2` 的设备号分别为 **2048、2064**，与父目录 `/mnt` 的 **66306** 不同；`/mnt/datasets` 与 `/mnt` 的设备号相同。

指定的 `mountinfo` 命令：

```bash
timeout 1800 ionice -c3 nice -n19 \
  grep -E ' /mnt/dataset[12] ' /proc/self/mountinfo
```

标准输出原样如下，退出码为 0：

```text
10385 10334 8:0 / /mnt/dataset1 ro,nosuid,nodev,relatime master:227 - ext4 /dev/sda rw
10386 10334 8:16 / /mnt/dataset2 ro,nosuid,nodev,relatime master:237 - ext4 /dev/sdb rw
```

其中挂载点选项为 `ro`，行尾超级块选项仍显示 `rw`；以上结论限定于当前沙箱看到的挂载。

指定的双路径 `findmnt` 命令：

```bash
timeout 1800 ionice -c3 nice -n19 \
  findmnt -J -o TARGET,SOURCE,FSTYPE,UUID,OPTIONS \
  /mnt/dataset1 /mnt/dataset2
```

**标准输出为空，标准错误为空，退出码为 1。** 本机 `findmnt --help` 将两个位置参数的形式列为：

```text
 findmnt [options] <device> <mountpoint>
```

分别查询挂载点的补充命令及原样输出如下：

```bash
timeout 1800 ionice -c3 nice -n19 \
  findmnt -J -o TARGET,SOURCE,FSTYPE,UUID,OPTIONS \
  --mountpoint /mnt/dataset1
```

```json
{
   "filesystems": [
      {
         "target": "/mnt/dataset1",
         "source": "/dev/sda",
         "fstype": "ext4",
         "uuid": "2d3a48d6-3785-47fe-8c8f-a20857fdc41a",
         "options": "ro,nosuid,nodev,relatime"
      }
   ]
}
```

```bash
timeout 1800 ionice -c3 nice -n19 \
  findmnt -J -o TARGET,SOURCE,FSTYPE,UUID,OPTIONS \
  --mountpoint /mnt/dataset2
```

```json
{
   "filesystems": [
      {
         "target": "/mnt/dataset2",
         "source": "/dev/sdb",
         "fstype": "ext4",
         "uuid": "35445b14-9e83-4f74-ac73-1551e3db6d63",
         "options": "ro,nosuid,nodev,relatime"
      }
   ]
}
```

设备号及 inode 命令：

```bash
timeout 1800 ionice -c3 nice -n19 \
  stat -c '%d %i %n' \
  /mnt /mnt/dataset1 /mnt/dataset2 /mnt/datasets
```

标准输出原样如下，退出码为 0：

```text
66306 28442625 /mnt
2048 2 /mnt/dataset1
2064 2 /mnt/dataset2
66306 28442628 /mnt/datasets
```