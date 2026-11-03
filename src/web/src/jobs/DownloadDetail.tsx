// 下载详情只轮询 worker 已发布的快照，不能把已提交请求当作已生效参数。
import { useEffect, useRef, useState, type ReactElement } from "react";
import { Button, Card, InputNumber, Typography } from "antd";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useAccountClient } from "../accounts/runtime";
import { adjustDownload, getDownloadStatus, type DownloadStatus } from "../api/downloadAdjustments";
import { toFailureView } from "../api/problems";
import { DiagnosticCard } from "../DiagnosticCard";
import { JOB_POLL_INTERVAL_MS } from "../api/jobs";
import type { Job } from "../api/jobs";
import { isJobTerminal } from "./progress";

/**
 * 显示下载运行快照，并允许运行中提交并发和限速调整。
 * @param props - 下载详情的属性。
 * @param props.job - 作业详情；编号不转换为 JavaScript 数字。
 * @returns 速度、文件计数、实际生效值及调整表单。
 * @throws Error 缺少应用客户端提供器。
 * @sideEffects 读取快照；提交只写调参通道，不操作下载进程。
 * @timeSemantics 运行中每秒轮询；请求上限 10 秒；提交不代表已生效。
 */
export function DownloadDetail({ job }: { job: Job }): ReactElement {
  const client = useAccountClient();
  const status = useQuery({
    queryKey: ["jobs", "download-status", job.job_id],
    queryFn: ({ signal }) => getDownloadStatus(client, job.job_id, signal),
    enabled: job.started_at !== null,
    refetchInterval: isJobTerminal(job) ? false : JOB_POLL_INTERVAL_MS,
    retry: false,
  });
  if (status.isError) return <DiagnosticCard failure={toFailureView(status.error)} />;
  if (!status.data) return <Typography.Text>下载状态尚未就绪</Typography.Text>;
  const data = status.data;
  return (
    <Card title="下载详情">
      <div>当前速度：{data.speed_bytes_per_s} B/s</div>
      <div>
        文件：{data.completed_files} / {data.total_files}；失败 {data.failed_files}；跳过{" "}
        {data.skipped_files}
      </div>
      <div>
        实际并发：{data.effective.max_concurrent_downloads}；实际限速：
        {data.effective.max_overall_download_limit_bytes_per_s} B/s
      </div>
      {/* 这五项运行中不可调整，使用作业保存的参数；动态项始终显示 worker 确认值。 */}
      <div>
        每服务器连接数：{parameterNumber(job.parameters.max_connection_per_server)}；每文件分段数：
        {parameterNumber(job.parameters.split)}；最小分段大小：
        {parameterNumber(job.parameters.min_split_size_bytes)} B；重试次数：
        {parameterNumber(job.parameters.max_tries)}；重试间隔：
        {parameterNumber(job.parameters.retry_wait_s)} 秒
      </div>
      <div>{adjustmentLabel(job, data)}</div>
      {job.state === "running" && <AdjustmentForm jobId={job.job_id} data={data} />}
    </Card>
  );
}

// 历史作业可能缺失参数，不把无效值伪装成默认值。
function parameterNumber(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) ? String(value) : "未知";
}

// 只有 worker 确认版本才能称为生效，终态未确认时引导查看已归档的作业诊断。
function adjustmentLabel(job: Job, data: DownloadStatus): string {
  if (data.requested_version === data.applied_version) return "已生效";
  return isJobTerminal(job) ? "调参未生效，作业已结束；原因见下方作业诊断。" : "等待生效";
}

// 写请求的取消控制器属于表单本次挂载；成功只更新状态快照，不假定 worker 已应用。
function AdjustmentForm({ jobId, data }: { jobId: string; data: DownloadStatus }): ReactElement {
  const client = useAccountClient();
  const cache = useQueryClient();
  const [concurrency, setConcurrency] = useState<number | null>(null);
  const [limit, setLimit] = useState<number | null>(null);
  const active = useRef<AbortController | null>(null);
  useEffect(
    () => () => {
      active.current?.abort();
    },
    [],
  );
  const change = useMutation({
    mutationFn: async () => {
      const controller = new AbortController();
      active.current = controller;
      try {
        return await adjustDownload(
          client,
          jobId,
          {
            max_concurrent_downloads: concurrency,
            max_overall_download_limit_bytes_per_s: limit,
          },
          controller.signal,
        );
      } finally {
        active.current = null;
      }
    },
    onSuccess: (result) => {
      cache.setQueryData(["jobs", "download-status", jobId], result);
    },
    retry: false,
  });
  const disabled =
    change.isPending ||
    (concurrency === null && limit === null) ||
    (limit !== null && limit > 0 && limit < 1024);
  return (
    <div>
      <label>
        同时下几个文件
        <InputNumber
          aria-label="同时下几个文件"
          min={1}
          max={16}
          precision={0}
          value={concurrency ?? data.requested.max_concurrent_downloads}
          onChange={setConcurrency}
        />
      </label>
      <label>
        总限速（B/s）
        <InputNumber
          aria-label="总限速（B/s）"
          min={0}
          max={10737418240}
          precision={0}
          value={limit ?? data.requested.max_overall_download_limit_bytes_per_s}
          onChange={setLimit}
        />
      </label>
      <Button
        aria-label="调整下载参数"
        loading={change.isPending}
        disabled={disabled}
        onClick={() => {
          change.mutate();
        }}
      >
        调整下载参数
      </Button>
      {change.isError && <DiagnosticCard failure={toFailureView(change.error)} />}
    </div>
  );
}
