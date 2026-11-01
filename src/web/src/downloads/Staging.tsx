// 暂存目录仅通过 worker 快照展示；占用状态是观察，不作为删除许可。
import { useEffect, useRef, useState, type ReactElement } from "react";
import { Alert, Button, Modal, Table, Typography } from "antd";
import { getRouteApi, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useAccountClient, useCurrentAccount } from "../accounts/runtime";
import {
  getStagingSnapshot,
  submitStagingDelete,
  submitStagingScan,
  type DownloadStaging,
} from "../api/downloads";
import { getJob, JOB_POLL_INTERVAL_MS, type Job } from "../api/jobs";
import { toFailureView, type RequestFailureView } from "../api/problems";
import { DiagnosticCard, JobDiagnosticCard } from "../DiagnosticCard";
import { isJobTerminal } from "../jobs/progress";
import { formatDateTime } from "../time";

const route = getRouteApi("/downloads");

/**
 * 提交只读暂存扫描，并展示已生成的数据库快照。
 * @param props - 当前路由提供的扫描编号。
 * @param props.jobId - 扫描作业编号；没有扫描时为 undefined。
 * @returns 刷新操作、扫描状态和快照表格。
 * @throws Error 缺少页面客户端或路由提供器。
 * @sideEffects 向服务器提交扫描作业并读取作业与快照，不访问存储根。
 * @timeSemantics 只在主动刷新时提交；运行中每秒轮询，离页取消，状态只反映生成时刻。
 */
export function Staging({ jobId }: { jobId: string | undefined }): ReactElement {
  const client = useAccountClient();
  const navigate = route.useNavigate();
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<RequestFailureView | null>(null);
  const active = useRef<AbortController | null>(null);
  useEffect(
    () => () => {
      active.current?.abort();
    },
    [],
  );
  async function refresh(): Promise<void> {
    if (active.current) return;
    const controller = new AbortController();
    active.current = controller;
    setBusy(true);
    setFailure(null);
    try {
      const job = await submitStagingScan(client, controller.signal);
      if (!controller.signal.aborted)
        await navigate({ search: (previous) => ({ ...previous, staging_job_id: job.job_id }) });
    } catch (error) {
      if (!controller.signal.aborted) setFailure(toFailureView(error));
    } finally {
      active.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }
  return (
    <section>
      <Typography.Title level={3}>下载暂存区</Typography.Title>
      <Typography.Paragraph>
        快照仅反映扫描时的状态；删除前须重新确认占用情况。
      </Typography.Paragraph>
      <Button
        aria-label="刷新暂存列表"
        disabled={busy}
        loading={busy}
        onClick={() => {
          void refresh();
        }}
      >
        刷新暂存列表
      </Button>
      {failure && <DiagnosticCard failure={failure} />}
      {jobId ? <Snapshot jobId={jobId} /> : <Typography.Text>尚未生成暂存列表</Typography.Text>}
    </section>
  );
}

// 只在扫描作业成功后读取快照；任务失败由统一诊断显示，不能伪装成空列表。
function Snapshot({ jobId }: { jobId: string }): ReactElement {
  const client = useAccountClient();
  const job = useQuery({
    queryKey: ["jobs", "staging-scan", jobId],
    queryFn: ({ signal }) => getJob({ client, jobId, payload: undefined, signal }),
    refetchInterval: (query) =>
      query.state.data && isJobTerminal(query.state.data) ? false : JOB_POLL_INTERVAL_MS,
    retry: false,
  });
  const success = succeeded(job.data);
  const result = useQuery({
    queryKey: ["downloads", "staging", jobId],
    queryFn: ({ signal }) => getStagingSnapshot(client, jobId, signal),
    enabled: success,
    retry: false,
  });
  if (job.isError) return <DiagnosticCard failure={toFailureView(job.error)} />;
  if (result.isError) return <DiagnosticCard failure={toFailureView(result.error)} />;
  if (result.data) return <StagingTable data={result.data} />;
  if (job.data && isJobTerminal(job.data))
    return (
      <>
        <Alert type="error" title="暂存扫描未成功" />
        <JobDiagnosticCard job={job.data} />
      </>
    );
  return <Typography.Text>正在扫描暂存区…</Typography.Text>;
}

// 扫描只有成功终态才具备可读取的快照。
function succeeded(job: Job | undefined): boolean {
  const outcome = job?.summary?.outcome;
  return (
    job?.state === "completed" && (outcome === "succeeded" || outcome === "succeeded_with_warnings")
  );
}

type StagingRow = DownloadStaging["items"][number];

function StagingTable({ data }: { data: DownloadStaging }): ReactElement {
  const identity = useCurrentAccount();
  const client = useAccountClient();
  const [selected, setSelected] = useState<StagingRow | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<RequestFailureView | null>(null);
  const [submitted, setSubmitted] = useState<string | null>(null);
  const active = useRef<AbortController | null>(null);
  useEffect(
    () => () => {
      active.current?.abort();
    },
    [],
  );
  async function confirm(): Promise<void> {
    if (!selected || active.current) return;
    const controller = new AbortController();
    active.current = controller;
    setBusy(true);
    setFailure(null);
    try {
      const job = await submitStagingDelete(
        client,
        {
          storage_root: selected.storage_root,
          repo_type: selected.repo_type,
          repo_id: selected.repo_id,
          commit_prefix: selected.commit_prefix,
        },
        controller.signal,
      );
      if (!controller.signal.aborted) {
        setSubmitted(job.job_id);
        setSelected(null);
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        setFailure(toFailureView(error));
        setSelected(null);
      }
    } finally {
      active.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }
  return (
    <div>
      <div>生成时间：{formatDateTime(data.created_at)}</div>
      {failure && <DiagnosticCard failure={failure} />}
      {submitted && (
        <Alert
          type="info"
          title="已提交清理作业，目录是否删除以作业结果为准。"
          description={
            <Link to="/jobs/$jobId" params={{ jobId: submitted }}>
              查看清理作业 #{submitted}
            </Link>
          }
        />
      )}
      <Table<StagingRow>
        rowKey={(row) =>
          JSON.stringify([row.storage_root, row.repo_type, row.repo_id, row.commit_prefix])
        }
        pagination={false}
        scroll={{ x: "max-content" }}
        dataSource={data.items}
        columns={[
          { title: "存储根", dataIndex: "storage_root" },
          {
            title: "类型",
            dataIndex: "repo_type",
            render: (kind: string) => (kind === "dataset" ? "数据集" : "模型"),
          },
          { title: "仓库", dataIndex: "repo_id" },
          { title: "commit", dataIndex: "commit_prefix" },
          { title: "大小（B）", dataIndex: "size_bytes" },
          {
            title: "修改时间",
            dataIndex: "modified_at",
            render: (value: string) => formatDateTime(value),
          },
          { title: "占用", render: (_, row) => (row.in_use ? "使用中" : "未使用") },
          {
            title: "操作",
            render: (_, row) =>
              identity.data?.role === "administrator" ? (
                <Button
                  aria-label={`删除 ${row.repo_id}`}
                  disabled={row.in_use || busy || submitted !== null}
                  danger
                  onClick={() => {
                    setSelected(row);
                  }}
                >
                  删除
                </Button>
              ) : null,
          },
        ]}
      />
      <Modal
        open={selected !== null}
        title="确认删除暂存目录？"
        onCancel={() => {
          if (!busy) setSelected(null);
        }}
        footer={[
          <Button
            key="cancel"
            aria-label="取消删除"
            disabled={busy}
            onClick={() => {
              setSelected(null);
            }}
          >
            取消
          </Button>,
          <Button
            key="confirm"
            aria-label="确认删除"
            danger
            type="primary"
            loading={busy}
            disabled={busy}
            onClick={() => {
              void confirm();
            }}
          >
            确认删除
          </Button>,
        ]}
      >
        <p>将提交清理作业；只删除暂存目录，无法撤销。后端会再次检查占用。</p>
        {selected && (
          <p>
            {selected.storage_root} / {selected.repo_id} @ {selected.commit_prefix}
          </p>
        )}
      </Modal>
    </div>
  );
}
