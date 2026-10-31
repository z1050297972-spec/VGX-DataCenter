// 导航编辑流程的成功门禁；completed本身也可能失败，不作为确认许可。
import type { Job } from "../api/jobs";

/**
 * 判断作业是否成功结束，允许带警告的成功。
 * @param job - 最近一次服务端作业观察；undefined表示尚未读取。
 * @returns completed且结果为成功或带警告成功时为true。
 * @throws 无。
 * @sideEffects 无，纯判断。
 * @timeSemantics 只依赖该次响应，不根据本地经过时间猜测完成。
 */
export function navigationJobSucceeded(job: Job | undefined): boolean {
  return (
    job?.state === "completed" &&
    (job.summary?.outcome === "succeeded" || job.summary?.outcome === "succeeded_with_warnings")
  );
}
