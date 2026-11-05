# 第 4 项"数据大小"改为自动计算，按格式统计有效大小

Status: in-progress

分级：直做。统计口径负责人已当面定了（见下），不过骨架关卡。按"只做关键测试"。

## 依据

负责人（2026-11-04）编辑 dataset-33（EgoProDemo）时，把第 4 项改成了"119.643 GB"。平台从这段文字里读"记录字节数"，只认 `（N B；` 这种写法，改完就读不出来了，所以报出 RECORDED_SIZE_MISSING 警告。执行线给了三种办法，负责人选"第 4 项改成自动计算"，并回答了以下几点：
- 存放："只在页面显示实测值"。`数据集信息.json` 第 4 项原来的文字不动，不再解析。
- 口径："lerobot格式，只读data/*.parquet、videos/*.mp4、meta/的大小，mcap和压缩包读全部大小，不分很细"。

执行线按授权补定的细节（已在会话里告诉负责人）：
- 每条链接的格式取它对应的数据块（`原始路径.json` 的 `format`）。对不上数据块、没有格式、格式不认识的，都按全部大小算。
- LeRobot 只算三类文件：路径里有 `data` 目录、后缀是 `.parquet` 的普通文件；有 `videos` 目录、后缀是 `.mp4` 的；有 `meta` 目录的全部普通文件。目录层级不限。遍历时跳过名字以 `.` 开头的目录（例如 `.cache`），因为 HuggingFace 下载缓存里也有 meta/videos 结构。
- 页面只显示一个大小，不显示"总大小"；去掉"10-12 记录"一行。
- 升级后执行线马上手动统计一次全部数据集，不等定时统计。

参考值：EgoProDemo 全部大小 119,642,823,842 B，其中 `.cache` 603,779,578 B（8 个 `.incomplete` 都在里面）。

## 范围

1. **统计口径**（`jobs/datasets/_size_walk.py`、`sizing.py`、`_sizing_types.py` 等）：按上面的规则，每条链接按格式统计。硬链接去重、不跟随内部软链接、低 IO 优先级、O_NOATIME、离线时保留旧值，这些现有规则都不变。`.aria2`、`.incomplete` 的计数和样例照旧统计、照旧显示。同一个目标、不同格式的缓存键要分开。
2. **不再读第 4 项文字**：`reading.extract_recorded_size` 和 RECORDED_SIZE_MISSING 不再产生（枚举保留，用来显示旧记录）。`recorded_size_bytes` 在索引和接口里的处理方式由 Codex 选：一律写 None，或者删掉列和字段（删列要加迁移）。在最终回复里说明选了哪种。列表 `_listing.py` 不再用记录值顶替，没统计过就是"未统计"。
3. **编辑器**：`数据集信息.json` 第 4 项（number=4、name=数据大小）不再出现在可编辑字段里，后端白名单也要拒绝它（422）。编辑器顶部"自动计算"的说明里加上"数据大小"。
4. **页面**：
   - `Sizes.tsx` 去掉"10-12 记录"一行；"统计大小"后面注明口径，例如"LeRobot 只计 parquet、mp4 和 meta"，一行就够。
   - 数据集信息（`Information.tsx`）里第 4 项不显示 JSON 原文，改为显示平台统计值和统计时间，没统计过就写"未统计"。
5. 使用手册里讲数据大小、第 4 项的章节同步改。

## 验收

1. **关键测试**：
   - 遍历：LeRobot 目标里有 `data/a.parquet`、`videos/x/b.mp4`、`meta/info.json`、`README.md`、`data/c.json`、`.cache/meta/m.json` 时，只算前三个；同一个目录按 mcap 算的话，全部计入（`.cache` 也算）；
   - 第 4 项写成"119.643 GB"的入口，扫描后一致性面板里没有 RECORDED_SIZE_MISSING；
   - 编辑第 4 项返回 422；编辑器里看不到第 4 项；
   - 详情页里没有"10-12 记录"，第 4 项显示的是统计值。
2. **真实演练**（执行线）：升级后手动统计一次全部数据集。dataset-33 的结果，要和执行线用 find 按同一规则算的字节数一致；任挑一个 MCAP 数据集，结果要等于 `du -sb --apparent-size`（硬链接口径一致）。dataset-33 的 RECORDED_SIZE_MISSING 消失。两块数据盘写入扇区数不变。
3. **检查链**：`make check` 全绿、0 skipped。

## Comments

- 2026-11-04 开票（执行线；负责人点名）。
- 2026-11-04 22:26 派工（Codex gpt-6-astra high，单元 rdp-codex-m15-07，日志 ~/.cache/rdp-dispatch/m15-07/）。基线沿用 main 573076a 的 make check 全绿（之后只有工单提交）。
