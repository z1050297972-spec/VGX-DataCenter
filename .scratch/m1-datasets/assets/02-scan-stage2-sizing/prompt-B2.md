第一段通过：执行线在沙箱外对真实导航层和两块数据盘做了全量扫描，150 条发现和你的预计逐条一致（`realscan-findings.txt`）。

真实扫描还查出一件事：两块数据盘按 `rw,relatime` 挂载，扫描读 `meta/info.json` 时内核更新了 atime，扫描期间两块盘的写入扇区数增加了。平台的代码本身没有写盘，但数据盘应当只读，所以本轮一并处理：
- 第二段读存储根上的文件和目录时，尽量带 `O_NOATIME`：普通文件用 `os.open(..., O_RDONLY|O_NOATIME)`，目录列表用 `os.open(dir, O_RDONLY|O_DIRECTORY|O_NOATIME)` 再 `os.scandir(fd)`。
- 内核只允许文件属主或有 CAP_FOWNER 的进程用 O_NOATIME，遇到 `EPERM` 就退回普通打开，不报错，也不刷日志。
- `stat`、`lstat`、`readlink` 本来就不更新 atime，不用改。
- 统计大小只用 `lstat` 或 `os.scandir` 的 `stat()`，目录也按上面的方式打开。
- 测试断言打开时带了 O_NOATIME，以及遇到 EPERM 时会退回；用替换的 open 函数测，不依赖真实文件系统的行为。
- 在模块注释里写明为什么这样做（真实扫描的发现）。

然后做**第二段：统计大小**（工单验收第 6 条）。用 $tdd 和 $enterprise-coding，先红后绿。
- 按链接目标统计表观字节数，没被链接的内容不计入；
- 最低 IO 优先级，选标准库 `os.setpriority` 还是 `ionice`，在模块注释里写理由；
- 不拿写锁；
- 同一次遍历里数出 `.aria2`、`.incomplete`，交给面板；
- 结果写进索引，带统计时间；
- 每晚定时提交，提交人是"系统"，复用第 01 张的触发框架；手动提交入口给第 03 张用；
- 作业类型键用 `dataset_sizing`（第 03 张已经按这个名字写了常量），参数形状要在第 4 块写明，以便合并时对齐。

最后 `make check` 全绿、0 skipped，连跑 3 次贴出汇总行。边界不变：只改 `src/`、`tests/`；不 `git add`、不提交；不读不写 `/mnt`；不联网、不安装；不碰真实部署。60 分钟内交付。最终回复五块，格式同上。
