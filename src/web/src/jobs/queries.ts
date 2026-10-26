// 作业 Query 契约（08）；缓存按身份清理，所有请求由 useAccountClient 的统一传输发出。
import type { UseMutationResult, UseQueryResult } from "@tanstack/react-query";
import type { CountInput, Job, JobList, JobLog, JobSearch, WorkerStatus } from "../api/jobs";

/**
 * 按 URL 筛选轮询一页作业。
 * @param _search - 已校验的 Router search，筛选与游标都参与 Query key。
 * @returns JobList 查询状态；空列表正常，无效 search 由页面禁止调用。
 * @throws Error 缺少账号 Provider；请求故障保存在 error 供 DiagnosticCard 显示。
 * @sideEffects 通过 listJobs 查询，不全量翻页；401 统一取消并清理当前账号缓存。
 * @timeSemantics 每 JOB_POLL_INTERVAL_MS 轮询，staleTime/gcTime=0、retry=false，离页取消。
 */
// eslint-disable-next-line @typescript-eslint/no-unused-vars -- 规则4要求函数体仅抛未实现异常，完整输入签名必须保留。
export function useJobs(_search: JobSearch): UseQueryResult<JobList> {
  throw new Error("未实现");
}

/**
 * 轮询单个作业直到终态。
 * @param _jobId - 规范正整数编号文本，作为 Query key，不转换成 Number。
 * @returns Job 查询状态；cancelling 仍轮询，终态保留最后记录。
 * @throws Error Provider 缺失；服务器错误由 error 返回。
 * @sideEffects getJob 请求；页面另用 useJobTiming 维护有界十秒样本，不在Query结果中隐藏另一份采样状态。
 * @timeSemantics 每秒一次，终态 refetchInterval=false，聚焦只在进行中刷新，无自动重试。
 */
// eslint-disable-next-line @typescript-eslint/no-unused-vars -- 规则4要求函数体仅抛未实现异常，完整输入签名必须保留。
export function useJob(_jobId: string): UseQueryResult<Job> {
  throw new Error("未实现");
}

/**
 * 跟随详情状态读取最后几十行日志。
 * @param _job - 当前详情 Job；日志路径仅供服务端使用，不作为请求路径。
 * @returns JobLog 查询状态，cleared 与 not_started 各有明确页面提示。
 * @throws Error Provider 缺失；文件/API 失败进入 error。
 * @sideEffects 调 getJobLog，进入终态再读一次最终尾部后停止，卸载取消并忽略迟到响应。
 * @timeSemantics 进行中每秒，终态最后请求完成后停止；单次 10 秒上限，不重试。
 */
// eslint-disable-next-line @typescript-eslint/no-unused-vars -- 规则4要求函数体仅抛未实现异常，完整输入签名必须保留。
export function useJobLog(_job: Job): UseQueryResult<JobLog> {
  throw new Error("未实现");
}

/**
 * 在登录布局维护所有账号可见的 worker 状态。
 * @returns WorkerStatus 查询状态，错误单独呈现，不当作在线或离线。
 * @throws Error 缺少账号 Provider；请求错误保留在 error。
 * @sideEffects getWorkerStatus 共享一个 Query，任何登录页面顶部用它；未登录或强制改密时不请求。
 * @timeSemantics 每秒轮询、无重试，身份切换/卸载清缓存和取消；作业终态不停止此查询。
 */
export function useWorkerStatus(): UseQueryResult<WorkerStatus> {
  throw new Error("未实现");
}

/**
 * 提交示例并在成功后进入新详情。
 * @returns Mutation，输入 CountInput，成功结果 Job。
 * @throws Error Provider 缺失；HTTP 失败放 mutation.error，不丢表单。
 * @sideEffects 调 submitCountJob，提交期间禁用重复按钮；成功失效列表缓存并导航新编号。
 * @timeSemantics 单次 10 秒，无重试；卸载取消，不声称取消请求使数据库回滚。
 */
export function useSubmitCountJob(): UseMutationResult<Job, Error, CountInput> {
  throw new Error("未实现");
}

/**
 * 发出当前作业取消请求。
 * @param _jobId - 当前作业编号文本；普通成员可取消其他账号作业。
 * @returns 无参数 Mutation，结果 Job；409 保留诊断并失效详情以读到竞争后的状态。
 * @throws Error Provider 缺失；其他请求失败由 mutation.error 呈现。
 * @sideEffects 调 cancelJob；成功刷新列表/详情，不乐观设置终态，不自动重复取消。
 * @timeSemantics 10 秒上限；cancelling 继续每秒查询，卸载取消传输。
 */
// eslint-disable-next-line @typescript-eslint/no-unused-vars -- 规则4要求函数体仅抛未实现异常，完整输入签名必须保留。
export function useCancelJob(_jobId: string): UseMutationResult<Job, Error, void> {
  throw new Error("未实现");
}

/**
 * 为终态作业重新提交新记录。
 * @param _jobId - 原作业规范编号；前端按钮只在终态出现，服务端仍独立校验。
 * @returns 无参数 Mutation，新 Job 的 resubmitted_from 指向原编号。
 * @throws Error Provider 缺失；409/422 等错误由 mutation.error 呈现。
 * @sideEffects 调 resubmitJob，成功刷新列表并导航新详情；失败不修改原记录。
 * @timeSemantics 10 秒上限、无重试，离页终止传输并忽略迟到导航。
 */
// eslint-disable-next-line @typescript-eslint/no-unused-vars -- 规则4要求函数体仅抛未实现异常，完整输入签名必须保留。
export function useResubmitJob(_jobId: string): UseMutationResult<Job, Error, void> {
  throw new Error("未实现");
}
