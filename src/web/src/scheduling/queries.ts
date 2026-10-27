// 调度轮询与演示提交（09）；沿用第8张账号感知传输、身份缓存清理及取消生命周期。
import type { UseMutationResult, UseQueryResult } from "@tanstack/react-query";
import type { Job } from "../api/jobs";
import type { GpuInput, NavigationInput, Scheduling } from "../api/scheduling";

/**
 * 轮询只读调度状态，在同一页面同时显示资源和每日计划。
 * @returns Scheduling 的查询状态；请求失败保留 error，不合成空闲卡或零运行数。
 * @throws Error 账号 Provider 缺失；网络和服务端错误由查询结果返回供 DiagnosticCard 渲染。
 * @sideEffects 用 useAccountClient 调 getScheduling，queryKey 为 scheduling；身份改变清缓存、卸载取消请求，401 统一回登录。
 * @timeSemantics 复用 JOB_POLL_INTERVAL_MS 每秒轮询，JOB_STALE_TIME_MS/JOB_GC_TIME_MS=0、retry=false；同页只维护一份查询。
 */
export function useScheduling(): UseQueryResult<Scheduling> {
  throw new Error("未实现");
}

/**
 * 提交 GPU 示例并进入新作业详情。
 * @returns 输入 GpuInput、输出 Job 的 Mutation；提交期间禁用重复按钮，错误保留表单。
 * @throws Error 依赖 Provider 缺失；请求失败进入 mutation.error。
 * @sideEffects 调 submitGpuJob，成功失效 jobs/scheduling 查询并导航 /jobs/$jobId；卸载或换号后迟到成功不导航。
 * @timeSemantics 单次请求 10 秒，不自动重试、不等待作业结束；组件卸载 abort。
 */
export function useSubmitGpuJob(): UseMutationResult<Job, Error, GpuInput> {
  throw new Error("未实现");
}

/**
 * 提交写锁示例并跟随其冲突或完成结果。
 * @returns 输入 NavigationInput 的 Mutation，成功值为新 Job；不在浏览器核对期望值。
 * @throws Error 依赖 Provider 缺失；提交错误交 mutation.error，不吞 409/422。
 * @sideEffects 调 submitNavigationJob；提交成功刷新 jobs/scheduling 并导航新详情，取消传输不声称事务回滚。
 * @timeSemantics 请求上限 JOB_REQUEST_TIMEOUT_MS，无自动重试，换号/离页忽略迟到导航。
 */
export function useSubmitNavigationJob(): UseMutationResult<Job, Error, NavigationInput> {
  throw new Error("未实现");
}
