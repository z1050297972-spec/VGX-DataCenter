你的契约变更申请批准方案 1：第 01 张的 `HttpTransport` / `UrllibTransport` 不动，首跳（镜像的 `resolve` 地址）仍走它；下载作业另加一个可注入的单跳传输，只用于已经通过 `validate_download_redirect` 的后续 HTTPS 地址，规则如下：
- 不跟随跳转、不走代理、不带 token；超时和响应体上限沿用第 01 张的常量（总时长 `HTTP_TOTAL_DEADLINE_S`），实现方式可以复用 `_http_child.py` 那套子进程隔离（别重复造轮子：抽一个共用的内部函数，但不改第 01 张已批准的公开签名和行为）。
- 预解析每一跳都用 `GET` 加 `Range: bytes=0-0`（只取 1 个字节，避免把大文件读进来），200 或 206 视为到达终点；3xx 取 `Location` 继续校验下一跳。首跳也一样用 `Range: bytes=0-0`。
- 这个单跳传输的主机限制由 `validate_download_redirect` 负责（拒绝 huggingface.co 及其子域等），传输本身只强制 HTTPS、拒绝带用户信息的地址。

其余照派工 B 的提示（/home/shawn/桌面/robot-data-platform/.scratch/m2-downloads/assets/02-download-job/prompt-B.md）继续：完成剩下的契约调整，然后按测试清单逐个函数先红后绿实现，直到不留骨架阶段的跳过、`make check` 全绿。停下条件、边界、最终回复的五块格式都和派工 B 一样。
