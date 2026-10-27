上一轮（prompt-B-r1）执行到一半被执行线一侧的会话中断，没有写出最终回复。工作区保留着你停下时的改动（快照 `refs/rdp/m0-09/B-r1-cut`；打回前的全绿点是 `refs/rdp/m0-09/B-done`）。

先 `git diff refs/rdp/m0-09/B-done` 看清已经改了什么，再用绝对路径重读 /home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/assets/09-job-scheduling-resources/prompt-B-r1.md，把 8 条全部做完。中断前写的缺陷测试如果没确认过红，用把实现临时改回的办法确认它能失败。

边界、停下条件和最终回复五块都同 prompt-B-r1；最终回复覆盖整轮（含中断前的部分）。
