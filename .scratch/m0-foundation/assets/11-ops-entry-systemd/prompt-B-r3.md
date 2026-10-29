评审打回第 3 轮（一条缺陷，也是最后一轮）。第 2 轮的修复对了：执行线已提交为 `2c76e60`，重跑验收 5 演练，Web 和 worker 收到 SIGTERM 都退出 0，开始、结束日志齐全。工作目录是干净的。

**缺陷（先红后绿）**：执行线做验收 7 升级演练时，同时启动 `rdp web` 和 `rdp worker`（`systemctl --user enable --now` 两个单元、开机自启都是这样同时起），Web 启动失败退出 1，web.log：

```
ERROR rdp.ops.cli 运维命令失败：[Errno 17] File exists: '<临时HOME>/.local/share/rdp/logs/示例：写锁'
```

原因：`src/rdp/infra/state.py` 的 `_create_directory`（约 160 行）先 `_directory_stat` 判断不存在、再 `path.mkdir(mode=...)`，两个进程同时初始化同一个状态目录时，后一个在 mkdir 处撞上 FileExistsError（检查与创建之间的竞争）。祖先目录的递归创建也有同样问题。

要求：
1. `_create_directory` 对"另一进程刚刚建好"的情况安全：mkdir 遇到 FileExistsError 时重新检查，确实是目录（不是软链接、不是普通文件）就当作已存在，按原契约处理（已有目录不 chmod、不计入本次新建；目标目录是软链接仍按原规则拒绝；被普通文件占用仍 NotADirectoryError）。`initialize_state` 的已获批契约含义不变，只补充并发安全说明（docstring 一句即可，第 3 块列出）。
2. 测试：至少一个确定性的单元测试（例如在 mkdir 前插入"另一方已创建"的效果：注入或替换使目录在检查后、mkdir 前出现），断言不抛错、结果正确；再加一个真实并发测试：多个线程或进程用同步屏障同时对同一个新状态目录调用 `initialize_state`，全部成功、目录权限 0700。所有等待有上限。
3. 先单独运行新测试看到红（FileExistsError），再改实现。
4. 顺带检查本票装配路径上 web/worker 同时启动时还有没有别的"先检查后创建"的竞争（例如日志文件、锁文件、数据库文件的创建），只列结论到第 4 块；确有会让进程启动失败的才改，并配测试。

其他不动。边界和交付同前几轮（只改 `src/`、`tests/`；不安装、不联网；不碰 `/mnt`、真实 systemd 与配置目录；不 `git add`、不提交）。40 分钟内交付；最后跑一次 `make check`（0 skipped）。最终回复五块：1 改动清单；2 `make check` 末尾原样输出及前后 `git status --porcelain --untracked-files=all`；3 契约补充/docstring 改动；4 拿不准的地方（含第 4 条结论）；5 先红后绿。
