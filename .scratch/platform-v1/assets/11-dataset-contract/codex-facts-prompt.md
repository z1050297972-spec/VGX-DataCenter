你在做只读的环境事实采集，为决策票「数据集板块的数据契约」提供数字。全程只读。

硬性约束：
- 不往 /mnt 下写任何东西，不创建、不修改、不删除任何文件。不要读取 ~/桌面/data_check 和 ~/桌面/Data_Collection_System-main。
- 你在只读沙箱里，不能写文件。脚本一律用 `python3 -I - <<'PY' ... PY` 从标准输入跑，结果打印到标准输出。
- 碰数据盘的命令一律加 `ionice -c3 nice -n19`，并用 `timeout 1800` 包住单条命令。某条超时就记"超时（>1800 s）"，继续下一条。
- 每个数字都要附上产生它的命令。计时用 `/usr/bin/time -f '%e s'` 或 python 的 time.monotonic()。

背景：导航层在 /mnt/datasets（系统盘），`按任务/<数据集>/` 下有 35 个数据集目录，每个目录里有 `原始路径.json`（含 `dataset_roots[]`、`links[]`、`sources[]`）。真实数据在 /mnt/dataset1、/mnt/dataset2 两块机械盘上。盘点细节见本仓库 docs/research/导航层盘点.md，附录 A 有盘点脚本 nav_inventory.py。

要采集的四项：

1. 全量扫描耗时。把 docs/research/导航层盘点.md 附录 A 里的 nav_inventory.py 从文档中提取出来，经标准输入跑 `python3 -I - /mnt/datasets`，输出丢到 /dev/null 或只打印最后几行，连续跑两次，分别记墙钟时间。说明第一次是否可能是冷缓存（看不出就写看不出）。

2. 每个数据集现算大小的耗时。对 `按任务/*/原始路径.json` 里的每个 `dataset_roots[]` 条目（共约 37 个路径）：
   - `du -sb --apparent-size` 和 `du -sb`（默认，按块）各跑一次，记字节数和墙钟时间；
   - 用 `find <root> -xdev \( -type f -o -type d -o -type l \) | wc -l` 记文件和目录总数（同样计时）；
   - 统计 `find <root> -xdev -name '*.aria2' -o -name '*.incomplete'` 的个数和前 5 个路径。
   按数据集汇总成一张表：dataset_id、数据集名、root、条目数、du 字节数（两种）、各命令耗时。最后给出全部 root 的总耗时，以及耗时最长的 5 个。
   再把 du 字节数和 `按任务/<数据集>/数据集信息.json` 第 4 项"数据大小"里第一个 `（N B；` 的 N 对比，列出相差超过 1% 的数据集和差值。

3. LeRobot source 的 meta/info.json。遍历 `按任务/*/原始路径.json` 的 `sources[]`，取 `format == "lerobot"` 的条目（约 494 条），对每条的 `direct_path`：
   - `<direct_path>/meta/info.json` 是否存在；
   - 存在的话读出 `codebase_version`、`robot_type`、`fps`。
   按数据集汇总：source 条数、info.json 存在条数、robot_type 取值集合、fps 取值集合（去重，最多列 10 个）、codebase_version 集合。列出 info.json 不存在的 source（最多 20 条）。记整个遍历的耗时。

4. 挂载信息。贴出 `grep -E ' /mnt/dataset[12] ' /proc/self/mountinfo` 和 `findmnt -J -o TARGET,SOURCE,FSTYPE,UUID,OPTIONS /mnt/dataset1 /mnt/dataset2` 的原样输出；再贴 `stat -c '%d %i %n' /mnt /mnt/dataset1 /mnt/dataset2 /mnt/datasets` 的输出（用来说明挂载点和父目录的设备号不同）。

交付：一份 markdown 报告作为你的最终回复，按上面 1–4 分节，每节先给结论（一两句），再给表格和命令。不要给设计建议，只给事实。
