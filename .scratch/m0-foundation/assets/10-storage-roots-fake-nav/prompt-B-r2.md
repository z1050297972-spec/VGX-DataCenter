打回第 2 轮。第 1 轮的 10 条执行线逐条核对都改到了，`make check` 复跑全绿（pytest 1793、Vitest 243），日志审计干净。但执行线在本机真实挂载表上重跑浏览器演示时，存储根页面整页失败：

```
错误 · 外部失败 · 存储检查 · 来源：平台
对象：storage_root=dataset1,dataset2
规则：storage.mount_table
实际：ValueError
```

原因（执行线已逐行复现）：本轮新加的挂载根（第 4 列）校验要求它是绝对路径，而本机真实 mountinfo 里 snapd 的 nsfs 挂载第 4 列是 `mnt:[4026532978]` 这种形式：

```
1362 292 0:5 mnt:[4026532978] /run/snapd/ns/docker.mnt rw - nsfs nsfs rw
4080 292 0:5 mnt:[4026532980] /run/snapd/ns/prompting-client.mnt rw - nsfs nsfs rw
```

一条无关挂载让整张表解析失败，两块在线的盘都显示不出来；报错文案"挂载点须为绝对路径"也说错了字段。这和第 1 轮第 1 条（`splitlines`）是同一类问题：解析对内核真实输出的形状过严。

**要求（先红后绿）**

1. 第 4 列按内核原样保存（解码转义后的文本），不要求是绝对路径；只有当它恰好是 `/` 时才代表整个文件系统，其他任何值（子目录、`mnt:[...]` 等）对登记的根一律是"挂错了盘"。`MountRecord.filesystem_root` 的类型如需从 `Path` 改成 `str`，按契约补充处理并在第 3 块写清。
2. 解析的拒绝条件只保留结构性错误（字段数、分隔符、设备号格式、挂载点非绝对、非法转义），并且报错文案指明是哪一列。
3. 用真实形状做回归：/home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/assets/10-storage-roots-fake-nav/mountinfo-sample.txt 是执行线从本机 `/proc/self/mountinfo` 复制、把用户名和桌面路径换掉的 58 行原文（含 nsfs、squashfs、fuse、tmpfs、vfat、ext4 等）。把它整理成测试数据（放进 `tests/fixtures/`），其中挂载点里的 `/mnt/...` 换成别的绝对路径（例如 `/srv/rdp-test/dataset1`），以满足验收 7 的静态检查；保留其余行原样。测试断言：整张表解析成功、条数正确、两块 ext4 数据盘按登记在线、nsfs 行的第 4 列原样保存。测试不读真实 `/proc`、不依赖本机。
4. 回头检查本轮其余解析/校验改动有没有同类"对内核真实输出过严"的地方（例如空的来源字段），在第 4 块写结论；只有确有内核会产生的形状才改。

其他不动。边界和交付同前几轮（只改 `src/`、`tests/`；不安装、不联网；不读 data_check/Data_Collection_System-main，不碰 `/mnt`；不 `git add`）。40 分钟内交付。

最终回复分五块：1 改动清单；2 `make check` 末尾原样输出及前后 `git status --porcelain --untracked-files=all`；3 契约补充和 docstring 改动；4 拿不准的地方（含第 4 条结论）；5 先红后绿。
