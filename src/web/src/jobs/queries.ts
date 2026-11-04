// 作业 Query 契约（08）；缓存按身份清理，所有请求由 useAccountClient 的统一传输发出。
import { useQuery, type UseMutationResult, type UseQueryResult } from "@tanstack/react-query";
import { useJobAction } from "./_actions";
import { useDatasetWriteRefresh } from "../datasets/useDatasetWriteRefresh";
import { useAccountClient, useCurrentAccount } from "../accounts/runtime";
import {
  cancelJob,
  resubmitJob,
  getJob,
  getJobLog,
  getWorkerStatus,
  listJobs,
  JOB_POLL_INTERVAL_MS,
  JOB_STALE_TIME_MS,
  JOB_GC_TIME_MS,
} from "../api/jobs";
import { isJobTerminal } from "./progress";
import type { Job, JobList, JobLog, JobSearch, WorkerStatus } from "../api/jobs";

/**
 * 按 URL 筛选轮询一页作业。
 * @param _search - 已校验的 Router search，筛选与游标都参与 Query key。
 * @returns JobList 查询状态；空列表正常，无效 search 由页面禁止调用。
 * @throws Error 缺少账号 Provider；请求故障保存在 error 供 DiagnosticCard 显示。
 * @sideEffects 通过 listJobs 查询，不全量翻页；401 统一取消并清理当前账号缓存。
 * @timeSemantics 每 JOB_POLL_INTERVAL_MS 轮询，staleTime/gcTime=0、retry=false，离页取消。
 */
export function useJobs(_search: JobSearch): UseQueryResult<JobList> {
  const client = useAccountClient();
  return useQuery({
    queryKey: ["jobs", "list", _search],
    queryFn: ({ signal }) => listJobs({ client, payload: _search, signal }),
    refetchInterval: JOB_POLL_INTERVAL_MS,
    staleTime: JOB_STALE_TIME_MS,
    gcTime: JOB_GC_TIME_MS,
    retry: false,
  });
}

/**
 * 轮询单个作业直到终态。
 * @param _jobId - 规范正整数编号文本，作为 Query key，不转换成 Number。
 * @returns Job 查询状态；cancelling 仍轮询，终态保留最后记录。
 * @throws Error Provider 缺失；服务器错误由 error 返回。
 * @sideEffects getJob 请求；页面另用 useJobTiming 维护有界十秒样本；导航写入、重新检查和统计大小作业终态使 datasets 缓存失效，刷新详情、列表、树及筛选计数，并刷新作业列表。
 * @timeSemantics 每秒一次，终态 refetchInterval=false，聚焦只在进行中刷新，无自动重试。
 */
export function useJob(_jobId: string): UseQueryResult<Job> {
  const client = useAccountClient();
  const query = useQuery({
    queryKey: ["jobs", "detail", _jobId],
    queryFn: ({ signal }) => getJob({ client, jobId: _jobId, payload: undefined, signal }),
    retry: false,
    staleTime: JOB_STALE_TIME_MS,
    gcTime: JOB_GC_TIME_MS,
    refetchInterval: (query) =>
      query.state.data && isJobTerminal(query.state.data) ? false : JOB_POLL_INTERVAL_MS,
    refetchOnWindowFocus: (query) => !query.state.data || !isJobTerminal(query.state.data),
  });
  // 第 08、10 张共用同一终态刷新入口；失败或中断也可能已经提交导航变更。
  useDatasetWriteRefresh(query.data);
  return query;
}

/**
 * 跟随详情状态读取最后几十行日志。
 * @param _job - 当前详情 Job；日志路径仅供服务端使用，不作为请求路径。
 * @returns JobLog 查询状态，cleared 与 not_started 各有明确页面提示。
 * @throws Error Provider 缺失；文件/API 失败进入 error。
 * @sideEffects 调 getJobLog，进入终态再读一次最终尾部后停止，卸载取消并忽略迟到响应。
 * @timeSemantics 进行中每秒，终态最后请求完成后停止；单次 10 秒上限，不重试。
 */
export function useJobLog(_job: Job): UseQueryResult<JobLog> {
  const client = useAccountClient();
  const terminal = isJobTerminal(_job);
  return useQuery({
    queryKey: ["jobs", "log", _job.job_id, terminal ? _job.state : "active"],
    queryFn: ({ signal }) => getJobLog({ client, jobId: _job.job_id, payload: undefined, signal }),
    refetchInterval: terminal ? false : JOB_POLL_INTERVAL_MS,
    refetchOnWindowFocus: !terminal,
    retry: false,
    staleTime: JOB_STALE_TIME_MS,
    gcTime: JOB_GC_TIME_MS,
  });
}

/**
 * 在登录布局维护所有账号可见的 worker 状态。
 * @returns WorkerStatus 查询状态，错误单独呈现，不当作在线或离线。
 * @throws Error 缺少账号 Provider；请求错误保留在 error。
 * @sideEffects getWorkerStatus 共享一个 Query，任何登录页面顶部用它；未登录或强制改密时不请求。
 * @timeSemantics 每秒轮询、无重试，身份切换/卸载清缓存和取消；作业终态不停止此查询。
 */
export function useWorkerStatus(): UseQueryResult<WorkerStatus> {
  const client = useAccountClient();
  const account = useCurrentAccount();
  return useQuery({
    queryKey: ["worker", "status"],
    queryFn: ({ signal }) => getWorkerStatus({ client, payload: undefined, signal }),
    enabled: !!account.data && !account.data.must_change_password,
    refetchInterval: JOB_POLL_INTERVAL_MS,
    retry: false,
    staleTime: JOB_STALE_TIME_MS,
    gcTime: JOB_GC_TIME_MS,
  });
}

/**
 * 发出当前作业取消请求。
 * @param _jobId - 当前作业编号文本；普通成员可取消其他账号作业。
 * @returns 无参数 Mutation，结果 Job；409 保留诊断并失效详情以读到竞争后的状态。
 * @throws Error Provider 缺失；其他请求失败由 mutation.error 呈现。
 * @sideEffects 调 cancelJob；成功刷新列表/详情，不乐观设置终态，不自动重复取消。
 * @timeSemantics 10 秒上限；cancelling 继续每秒查询，卸载取消传输。
 */
export function useCancelJob(_jobId: string): UseMutationResult<Job, Error, void> {
  const client = useAccountClient();
  return useJobAction(
    (_payload, signal) => cancelJob({ client, jobId: _jobId, payload: undefined, signal }),
    false,
  );
}

/**
 * 为终态作业重新提交新记录。
 * @param _jobId - 原作业规范编号；前端按钮只在终态出现，服务端仍独立校验。
 * @returns 无参数 Mutation，新 Job 的 resubmitted_from 指向原编号。
 * @throws Error Provider 缺失；409、422 等错误由 mutation.error 呈现。
 * @sideEffects 调 resubmitJob，成功刷新列表并导航新详情；失败不修改原记录。
 * @timeSemantics 10 秒上限、无重试，离页终止传输并忽略迟到导航。
 */
export function useResubmitJob(_jobId: string): UseMutationResult<Job, Error, void> {
  const client = useAccountClient();
  return useJobAction(
    (_payload, signal) => resubmitJob({ client, jobId: _jobId, payload: undefined, signal }),
    true,
  );
}
