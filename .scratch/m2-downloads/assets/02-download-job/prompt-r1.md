评审的变异抽查（只抽关键行为）发现三处没有测试覆盖，逐条补测试，实现代码原则上不动（测试暴露出实现错误时才修），别处不动：
1. 问题：token 发往非镜像主机没有测试拦住。把 job.py 里首轮 `add_file` 前"最终 URL 是镜像主机才带 token"那一行改成总是带 `self.token`，同时去掉 adapters.py `add_file` 里的非镜像拒绝，测试仍全部通过。期望：补测试，在预解析得到 CDN 地址（非 hf-mirror.com）时，替身 RPC 收到的 token 是 None（或请求头里没有 Authorization）；得到镜像地址时带 token。首轮加入和签名过期重解析两条路径都要覆盖（可以参数化成一个测试）。
2. 问题：`resolve_download_url` 的跳数上限没有测试拦住（把 `range(MAX_REDIRECT_HOPS + 1)` 改成 `range(100)` 仍通过）。期望：补测试，替身连续返回超过 `MAX_REDIRECT_HOPS` 次合法 3xx 时失败。
3. 问题：模型目标"已存在时不覆盖"的测试拦不住 `renameat2` 的 `RENAME_NOREPLACE` 标志被改成 0（大概是测试用了非空目标目录，普通 rename 也会失败）。期望：补一个目标是**空目录**的用例，必须失败且目标目录原样保留。

修完后 `make check` 一次，全绿就交。

边界：只改 `tests/`（必要时 `src/`）；不 `git add`、不提交；不碰 `/mnt` 和两个旧项目；不安装、不访问外网；临时文件交付前删掉。

最终回复：逐条写处理结果；`make check` 最后一次运行的命令和末尾输出，原样贴出。
