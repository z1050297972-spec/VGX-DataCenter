// 作业完成后的数据集缓存刷新，覆盖详情、列表、两棵树、面板与来源筛选。
import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { Job } from "../api/jobs";
import { isJobTerminal } from "../jobs/progress";

/**
 * 在作业页观察到导航写入终态时刷新所有数据集视图。
 * @param job - 已读取的作业；未取得时为 undefined。
 * @returns 无。
 * @throws 无；刷新失败由对应查询的诊断处理。
 * @sideEffects 每次挂载对同一终态作业仅失效一次 datasets 和作业列表缓存。
 * @timeSemantics 复用作业页每秒轮询，不另开定时器；取消或中断也刷新以展示最终事实。
 */
export function useDatasetWriteRefresh(job: Job | undefined): void {
  const cache = useQueryClient();
  const refreshed = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (
      !job ||
      job.type_name !== "nav_write_apply" ||
      !isJobTerminal(job) ||
      refreshed.current === job.job_id
    )
      return;
    refreshed.current = job.job_id;
    void cache.invalidateQueries({ queryKey: ["datasets"] });
    void cache.invalidateQueries({ queryKey: ["jobs", "list"] });
  }, [job, cache]);
}
