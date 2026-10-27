上一轮（prompt-B4）被执行线中途停止，机器之后也重启过。工作区保留着你停下时的改动，没有动过（快照 `refs/rdp/m0-09/B4-paused`）；上一个确认全绿的点是 `refs/rdp/m0-09/B-cp3`。现在 `make check` 停在 lint/格式（ruff、`raise DefectError()` 处的报告和若干待格式化的测试），说明停在半途。

先用 `git diff refs/rdp/m0-09/B-cp3` 看清自己已经改了什么，再接着完成 prompt-B4 的全部要求（用绝对路径重读 /home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/assets/09-job-scheduling-resources/prompt-B4.md 和 prompt-B.md）。半途写的东西按 $tdd 核对：没看到红的测试，确认它确实能失败。

边界、停下条件、检查点规则和最终回复五块都同 prompt-B4。
