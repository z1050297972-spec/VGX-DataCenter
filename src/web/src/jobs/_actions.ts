// 作业提交、取消和重提共用的挂载生命周期；只通过注入的类型化请求发送。
import { useMutation, useQueryClient, type UseMutationResult } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { useCurrentAccount } from "../accounts/runtime";
import { useNavigate } from "@tanstack/react-router";
import { toFailureView } from "../api/problems";
import { JOB_GC_TIME_MS, type Job } from "../api/jobs";
/**
 * 在本次挂载范围执行一个作业写请求。
 * @param send - 类型化请求回调，接收载荷和取消信号。
 * @param redirect - 成功后是否进入新作业详情。
 * @returns 禁止重试并保留错误的Mutation。
 * @throws Error 重复提交、组件卸载或请求失败。
 * @sideEffects 成功失效jobs和scheduling缓存；卸载取消请求，忽略迟到导航。
 * @timeSemantics 请求预算由传输层控制，本层不增加等待或重试。
 */
export function useJobAction<T>(
  send: (payload: T, signal: AbortSignal) => Promise<Job>,
  redirect: boolean,
): UseMutationResult<Job, Error, T> {
  const identity = useCurrentAccount();
  const cache = useQueryClient();
  const navigate = useNavigate();
  const owner = useRef<{
    mounted: boolean;
    active: AbortController | null;
    generation: number;
    completed: number;
  }>({
    mounted: false,
    active: null,
    generation: 0,
    completed: -1,
  });
  useEffect(() => {
    const state = owner.current;
    state.mounted = true;
    state.generation++;
    return () => {
      state.mounted = false;
      state.active?.abort();
    };
  }, [identity.data?.account_id]);
  return useMutation({
    mutationFn: async (payload: T) => {
      if (owner.current.active) throw new Error("请求处理中");
      const generation = owner.current.generation;
      const controller = new AbortController();
      owner.current.active = controller;
      try {
        const record = await send(payload, controller.signal);
        if (
          !owner.current.mounted ||
          controller.signal.aborted ||
          generation !== owner.current.generation
        )
          throw new Error("请求已取消");
        owner.current.completed = generation;
        return record;
      } finally {
        if (owner.current.active === controller) owner.current.active = null;
      }
    },
    onSuccess: async (record) => {
      const generation = owner.current.completed;
      if (!isMounted(owner.current) || generation !== owner.current.generation) return;
      await cache.invalidateQueries({ queryKey: ["jobs"] });
      await cache.invalidateQueries({ queryKey: ["scheduling"] });
      if (redirect && isMounted(owner.current) && generation === owner.current.generation)
        await navigate({ to: "/jobs/$jobId", params: { jobId: record.job_id } });
    },
    onError: async (error) => {
      const failure = toFailureView(error);
      if (owner.current.mounted && failure.kind === "problem" && failure.problem.status === 409)
        await cache.invalidateQueries({ queryKey: ["jobs"] });
      await cache.invalidateQueries({ queryKey: ["scheduling"] });
    },
    retry: false,
    gcTime: JOB_GC_TIME_MS,
  });
}

// await期间组件可能卸载，成功回调再次读取当前归属。
function isMounted(state: { mounted: boolean }): boolean {
  return state.mounted;
}
