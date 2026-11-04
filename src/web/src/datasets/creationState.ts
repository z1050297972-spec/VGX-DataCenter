// M1-08 表单流程状态；不复制 HTTP 字段或在浏览器内决定计划步骤。
import type {
  ConfirmCreationInput,
  CreationOptions,
  CreationPreview,
  DatasetPreviewInput,
  LinkPreviewInput,
  QueuedNavigationJob,
} from "../api/datasetCreation";
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useAccountClient, useCurrentAccount } from "../accounts/runtime";
import { isJobTerminal as terminal } from "../jobs/progress";
import { useJobAction } from "../jobs/_actions";
import { useRecoveryBlock } from "../navigation/queries";
import { getJob, JOB_POLL_INTERVAL_MS, JOB_GC_TIME_MS, JOB_STALE_TIME_MS } from "../api/jobs";
import {
  getCreationOptions,
  getCreationPreview,
  submitLinkPreview,
  submitDatasetPreview,
  confirmCreation,
  type FormatSelection,
} from "../api/datasetCreation";
import { toFailureView } from "../api/problems";
import type { Job } from "../api/jobs";
import type { RequestFailureView } from "../api/problems";

/** 可分享定位只保存编号，目标路径和未提交表单只在内存中。 */
export interface CreationSearch {
  /** 可选现有数据集永久编号，只用于建链表单预选；不是任意导航路径。 */
  dataset_id?: string;
  /** 可选成功预览编号文本；刷新后读取保存结果，禁止 Number 转换。 */
  preview_job_id?: CreationPreview["preview_job_id"];
  /** Router 输入非法时显示可修正提示，不回显坏输入或发请求。 */
  invalidCreationSearch?: true;
}

/**
 * 校验真实 Router 解码后的创建页面查询参数。
 * @param _input - Router search 原值，数字样式可能已经是 number，不能转为文本蒙混通过。
 * @returns 规范文本编号与预选项；非法值只返回 invalidCreationSearch=true。
 * @throws 无；坏 URL 留在表单提示，不使根路由崩溃。
 * @sideEffects 无；不解析 URLSearchParams、不写浏览器存储。
 * @timeSemantics 同步纯转换，不发请求。
 */
export function validateCreationSearch(_input: Record<string, unknown>): CreationSearch {
  const dataset = _input.dataset_id;
  const preview = _input.preview_job_id;
  if (
    (dataset !== undefined &&
      (typeof dataset !== "string" || dataset.length > 256 || !/^[^/\\\s\x00]+$/.test(dataset))) ||
    (preview !== undefined && !decimalId(preview))
  )
    return { invalidCreationSearch: true };
  return {
    dataset_id: typeof dataset === "string" ? dataset : undefined,
    preview_job_id: typeof preview === "string" ? preview : undefined,
  };
}

/** 页面局部阶段；服务端响应仍使用生成类型。 */
export type CreationStage = "editing" | "previewing" | "reviewing" | "submitting" | "submitted";

/** 两个页面复用的流程结果，不把失败伪装成空预览。 */
export interface CreationFlow {
  /** 当前阶段，editing 可填参数，reviewing 才能确认，pending 阶段禁用重复提交。 */
  stage: CreationStage;
  /** 格式/来源登记候选；尚未取到为 undefined，表单不可提交。 */
  options: CreationOptions | undefined;
  /** 成功并与当前表单参数一致的预览；修改任一参数立刻清空，强制重新预览。 */
  preview: CreationPreview | undefined;
  /** 当前预览作业；终态后停止轮询，不将已有结果复用于新参数。 */
  previewJob: Job | undefined;
  /** 排队提醒，空表示当前快照没有同数据集排队写作业。 */
  queuedJobs: QueuedNavigationJob[];
  /** 服务端预览返回的入口候选；首次预览前为空。 */
  formatEntryOptions: FormatSelection[];
  /** 恢复失败、状态未确认或读取失败时禁止提交。 */
  blocked: boolean;
  /** 禁止提交的原因；正常可提交时为 undefined。 */
  blockedReason: string | undefined;
  /** 当前统一诊断；冲突保留对象、实际、期望、后果与下一步。 */
  failure: RequestFailureView | undefined;
  /** 提交任一种预览，参数类型由当前页面区分。 */
  previewParameters: (parameters: LinkPreviewInput | DatasetPreviewInput) => void;
  /** 确认当前预览；仅传预览编号和用户已确认的排队编号。 */
  confirm: (parameters: ConfirmCreationInput) => void;
  /** 修改表单或冲突后退回编辑阶段，丢弃旧预览确认资格。 */
  edit: () => void;
}

/** hook 的显式输入，不保存目标到可分享 URL。 */
export interface CreationFlowInput {
  /** 当前创建类型，不能拿另一种预览直接确认。 */
  operation: CreationPreview["operation"];
  /** 类型化 Router 提供的预览编号，未预览为 undefined。 */
  previewJobId: CreationPreview["preview_job_id"] | undefined;
  /** 预览成功后写回类型化 search，允许刷新后重读预览。 */
  onPreviewed: (preview: CreationPreview) => void;
}

/**
 * 驱动两种表单从填参数、预览到确认入队的流程。
 * @param _input - 当前操作、文本预览定位及预览定位回调。
 * @returns CreationFlow；只允许成功预览进入 reviewing，参数变化后必须重新预览。
 * @throws Error 缺少账号客户端或 QueryClient Provider；请求失败保存在 failure。
 * @sideEffects 用 TanStack Query 和统一客户端读候选、提交预览、轮询 M0 作业、读取保存结果及确认；成功入队后显示卡片，作业终态刷新 datasets 缓存。
 * @timeSemantics 预览作业按 JOB_POLL_INTERVAL_MS 轮询且终态停止，使用 JOB_STALE_TIME_MS/JOB_GC_TIME_MS；离页取消读请求，所有 POST 不重试。
 */
export function useCreationFlow(_input: CreationFlowInput): CreationFlow {
  const client = useAccountClient();
  const account = useCurrentAccount();
  const recovery = useRecoveryBlock();
  const [activeId, setActiveId] = useState(_input.previewJobId);
  const [invalidated, setInvalidated] = useState(false);
  const notified = useRef<string | undefined>(undefined);
  const acknowledged = useRef<string[]>([]);
  const previewAction = useJobAction<LinkPreviewInput | DatasetPreviewInput>(
    (payload, signal) =>
      "dataset_id" in payload
        ? submitLinkPreview({ client, payload, signal })
        : submitDatasetPreview({ client, payload, signal }),
    false,
  );
  const applyAction = useJobAction<ConfirmCreationInput>(
    (payload, signal) => confirmCreation({ client, payload, signal }),
    { cardTitle: _input.operation === "create_link" ? "建链" : "新增数据集" },
  );
  const { options, job, result, successful } = usePreviewQueries(
    client,
    account.data?.account_id,
    activeId,
    invalidated,
  );
  const view = matchingPreview(result.data, activeId, _input.operation, successful && !invalidated);
  const valid = !!view;
  const onPreviewed = _input.onPreviewed;
  useEffect(() => {
    if (valid && result.data && notified.current !== result.data.preview_job_id) {
      notified.current = result.data.preview_job_id;
      onPreviewed(result.data);
    }
  }, [valid, result.data, onPreviewed]);
  const failure = failureOf([
    applyAction.error,
    previewAction.error,
    result.error,
    job.error,
    options.error,
    recovery.error,
  ]);
  const blockedReason = recoveryReason(recovery);
  const stage = applyAction.isSuccess
    ? "submitted"
    : creationStage(
        previewAction.isPending,
        applyAction.isPending,
        previewRunning(activeId, invalidated, job.data),
        valid,
      );
  return {
    stage,
    options: options.data,
    preview: view,
    previewJob: job.data,
    queuedJobs: queueJobs(failure, result.data?.dataset_id),
    failure,
    formatEntryOptions: entryOptions(result.data),
    blocked: !!blockedReason,
    blockedReason,
    previewParameters: (parameters) => {
      if (blockedReason || stage === "previewing" || stage === "submitting") return;
      setInvalidated(true);
      applyAction.reset();
      acknowledged.current = [];
      previewAction.mutate(parameters, {
        onSuccess: (record) => {
          setActiveId(record.job_id);
          setInvalidated(false);
        },
      });
    },
    confirm: (parameters) => {
      if (!valid || blockedReason || applyAction.isPending || applyAction.isSuccess) return;
      acknowledged.current = [
        ...new Set([...acknowledged.current, ...parameters.acknowledged_queue_job_ids]),
      ];
      applyAction.mutate({ ...parameters, acknowledged_queue_job_ids: acknowledged.current });
    },
    edit: () => {
      setInvalidated(true);
      previewAction.reset();
      applyAction.reset();
      acknowledged.current = [];
    },
  };
}

function decimalId(value: unknown): value is string {
  return (
    typeof value === "string" &&
    /^[1-9][0-9]{0,18}$/.test(value) &&
    BigInt(value) <= 9223372036854775807n
  );
}
function creationStage(
  previewing: boolean,
  submitting: boolean,
  running: boolean,
  valid: boolean,
): CreationStage {
  if (submitting) return "submitting";
  if (previewing || running) return "previewing";
  return valid ? "reviewing" : "editing";
}
function queueJobs(
  failure: RequestFailureView | undefined,
  datasetId: string | undefined,
): QueuedNavigationJob[] {
  if (failure?.kind !== "problem" || failure.problem.status !== 409) return [];
  const ids = failure.problem.diagnostics
    .filter((item) => item.rule === "NAV_CREATE_QUEUE_CONFIRMATION")
    .flatMap((item) =>
      item.objects
        .filter(
          (object) => /^queued_job_id_[1-9][0-9]*$/.test(object.key) && decimalId(object.value),
        )
        .map((object) => object.value),
    );
  return [...new Set(ids)].map((job_id) => ({ job_id, dataset_ids: datasetId ? [datasetId] : [] }));
}

function usePreviewQueries(
  client: ReturnType<typeof useAccountClient>,
  accountId: string | undefined,
  activeId: string | undefined,
  invalidated: boolean,
) {
  const options = useQuery({
    queryKey: ["creation", accountId, "options"],
    queryFn: ({ signal }) => getCreationOptions({ client, payload: undefined, signal }),
    retry: false,
    staleTime: JOB_STALE_TIME_MS,
    gcTime: JOB_GC_TIME_MS,
  });
  const job = useQuery({
    queryKey: ["creation", accountId, "job", activeId],
    queryFn: ({ signal }) => getJob({ client, jobId: activeId ?? "", payload: undefined, signal }),
    enabled: !!activeId,
    retry: false,
    staleTime: JOB_STALE_TIME_MS,
    gcTime: JOB_GC_TIME_MS,
    refetchInterval: (query) =>
      query.state.data && terminal(query.state.data) ? false : JOB_POLL_INTERVAL_MS,
    refetchOnWindowFocus: false,
  });
  const successful = isSuccessful(job.data);
  const result = useQuery({
    queryKey: ["creation", accountId, "preview", activeId],
    queryFn: ({ signal }) =>
      getCreationPreview({ client, previewJobId: activeId ?? "", payload: undefined, signal }),
    enabled: successful && !invalidated,
    retry: false,
    staleTime: JOB_STALE_TIME_MS,
    gcTime: JOB_GC_TIME_MS,
    refetchOnWindowFocus: false,
  });
  return { options, job, result, successful };
}
function isSuccessful(job: Job | undefined): boolean {
  return (
    job?.state === "completed" &&
    (job.summary?.outcome === "succeeded" || job.summary?.outcome === "succeeded_with_warnings")
  );
}
function matchingPreview(
  value: CreationPreview | undefined,
  id: string | undefined,
  operation: CreationPreview["operation"],
  valid: boolean,
): CreationPreview | undefined {
  if (!valid || !value || value.preview_job_id !== id || value.operation !== operation)
    return undefined;
  return value;
}
function previewRunning(
  id: string | undefined,
  invalidated: boolean,
  job: Job | undefined,
): boolean {
  return !!id && !invalidated && (!job || !terminal(job));
}
function recoveryReason(recovery: ReturnType<typeof useRecoveryBlock>): string | undefined {
  if (recovery.isPending) return "正在确认导航层恢复状态";
  if (recovery.isError) return "无法读取恢复状态，暂不能提交";
  return recovery.data.blocked ? "恢复失败：请管理员处理后再提交" : undefined;
}
function failureOf(errors: unknown[]): RequestFailureView | undefined {
  const error = errors.find((value) => value !== null && value !== undefined);
  return error ? toFailureView(error) : undefined;
}
function entryOptions(preview: CreationPreview | undefined): FormatSelection[] {
  return preview?.format_entry_options ?? [];
}
