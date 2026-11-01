// 入库预览由 worker 生成；修改任何选项后必须重新预览才能确认。
import { useEffect, useRef, useState, type ReactElement } from "react";
import { Alert, Button, Checkbox, Input, Space, Typography } from "antd";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useAccountClient } from "../accounts/runtime";
import {
  confirmIngest,
  getIngestPreview,
  submitIngestPreview,
  type IngestOptions,
  type IngestPreview,
} from "../api/downloadIngest";
import { getJob, JOB_POLL_INTERVAL_MS, type Job } from "../api/jobs";
import { toFailureView } from "../api/problems";
import { DiagnosticCard, JobDiagnosticCard } from "../DiagnosticCard";
import { isJobTerminal } from "../jobs/progress";

/**
 * 为成功的数据集下载显示手动入库入口。
 * @param props - 下载作业属性。
 * @param props.job - 服务端完整作业记录。
 * @returns 入库按钮与按需展开的表单；其他作业返回 null。
 * @throws Error 缺少应用上下文。
 * @sideEffects 展开后允许提交入库预览和确认作业。
 * @timeSemantics 仅成功终态显示，失败和模型下载不显示。
 */
export function IngestDownload({ job }: { job: Job }): ReactElement | null {
  const [open, setOpen] = useState(false);
  if (
    job.state !== "completed" ||
    job.summary?.outcome !== "succeeded" ||
    job.parameters.repo_type !== "dataset"
  )
    return null;
  return (
    <section>
      <Button
        aria-label="入库"
        onClick={() => {
          setOpen(true);
        }}
      >
        入库
      </Button>
      {open && <IngestForm job={job} />}
    </section>
  );
}

// 查询只在收到成功终态后读取预览，错误交统一组件处理。
function useIngestResult(previewId: string, generation: number) {
  const client = useAccountClient();
  const status = useQuery({
    queryKey: ["jobs", "ingest-preview", previewId, generation],
    queryFn: ({ signal }) => getJob({ client, jobId: previewId, payload: undefined, signal }),
    enabled: !!previewId,
    refetchInterval: (query) =>
      query.state.data && isJobTerminal(query.state.data) ? false : JOB_POLL_INTERVAL_MS,
    retry: false,
  });
  const result = useQuery({
    queryKey: ["downloads", "ingest-preview", previewId, generation],
    queryFn: ({ signal }) => getIngestPreview(client, previewId, signal),
    enabled: !!previewId && status.data?.summary?.outcome === "succeeded",
    retry: false,
  });
  return { status, result };
}

// POST 的 AbortController 跟随组件生命周期；提交失败不自动重试。
function IngestForm({ job }: { job: Job }): ReactElement {
  const client = useAccountClient();
  const navigate = useNavigate();
  const [previewId, setPreviewId] = useState("");
  const [generation, setGeneration] = useState(0);
  const active = useRef<AbortController | null>(null);
  useEffect(
    () => () => {
      active.current?.abort();
    },
    [],
  );
  const create = useMutation({
    mutationFn: async (options: IngestOptions) => {
      active.current = new AbortController();
      try {
        return await submitIngestPreview(client, job.job_id, options, active.current.signal);
      } finally {
        active.current = null;
      }
    },
    onMutate: () => {
      setPreviewId("");
    },
    onSuccess: (record) => {
      setGeneration((value) => value + 1);
      setPreviewId(record.job_id);
    },
    retry: false,
  });
  const { status, result } = useIngestResult(previewId, generation);
  const confirm = useMutation({
    mutationFn: async () => {
      active.current = new AbortController();
      try {
        return await confirmIngest(client, previewId, active.current.signal);
      } finally {
        active.current = null;
      }
    },
    onSuccess: async (record) => {
      await navigate({ to: "/jobs/$jobId", params: { jobId: record.job_id } });
    },
    retry: false,
  });
  const waiting = previewWaiting(previewId, status.data, status.isError, result.isError);
  const busy = create.isPending || confirm.isPending || waiting;
  const editorKey = `${String(generation)}/${result.data ? "ready" : "draft"}`;
  return (
    <Space orientation="vertical">
      <Typography.Title level={3}>入库预览</Typography.Title>
      <Typography.Text>
        存储根：{String(job.parameters.storage_root)}；位置填写该根内的相对路径。
      </Typography.Text>
      <IngestEditor
        key={editorKey}
        initial={initialOptions(job, result.data, create.variables)}
        data={result.data}
        busy={busy}
        onPreview={(options) => {
          create.mutate(options);
        }}
        onConfirm={() => {
          confirm.mutate();
        }}
      />
      {waiting && <Typography.Text>正在生成入库预览…</Typography.Text>}
      {result.data && <IngestContent data={result.data} />}
      {failedPreview(status.data) && status.data && (
        <>
          <Alert type="error" title="入库预览未成功" />
          <JobDiagnosticCard job={status.data} />
        </>
      )}
      {[create, status, result, confirm].map((query, index) =>
        query.isError ? <DiagnosticCard key={index} failure={toFailureView(query.error)} /> : null,
      )}
    </Space>
  );
}

// 完成状态不会继续占用表单，预览读取失败也允许用户重试。
function previewWaiting(
  id: string,
  job: Job | undefined,
  failed: boolean,
  resultFailed: boolean,
): boolean {
  return !!id && !failed && !resultFailed && (!job || !isJobTerminal(job));
}

// 终态结果完全采用服务端计数，不从诊断或本地猜测成功。
function failedPreview(job: Job | undefined): boolean {
  return !!job && isJobTerminal(job) && job.summary?.outcome !== "succeeded";
}

// 用新预览作为组件 key 重新初始化编辑器，避免 effect 复制远端状态造成级联渲染。
function initialOptions(
  job: Job,
  data: IngestPreview | undefined,
  submitted: IngestOptions | undefined,
): IngestOptions {
  if (data) return data.parameters;
  if (submitted) return submitted;
  const repo = typeof job.parameters.repo_id === "string" ? job.parameters.repo_id : "";
  return { dataset_name: repo.split("/").at(-1) ?? "", target_subdir: null, format_entries: null };
}

// 用户修改后仅收回确认资格，保留检查结果方便比较；再次预览会生成新的保存计划。
function IngestEditor({
  initial,
  data,
  busy,
  onPreview,
  onConfirm,
}: {
  initial: IngestOptions;
  data: IngestPreview | undefined;
  busy: boolean;
  onPreview: (options: IngestOptions) => void;
  onConfirm: () => void;
}): ReactElement {
  const [options, setOptions] = useState(initial);
  const [dirty, setDirty] = useState(false);
  function change(next: IngestOptions): void {
    setOptions(next);
    setDirty(true);
  }
  return (
    <>
      <label>
        数据集名
        <Input
          aria-label="入库数据集名"
          value={options.dataset_name ?? ""}
          disabled={busy}
          onChange={(event) => {
            change({ ...options, dataset_name: event.target.value });
          }}
        />
      </label>
      <label>
        存放位置
        <Input
          aria-label="入库存放位置"
          placeholder="默认：下载/命名空间/仓库@commit 前 12 位"
          value={options.target_subdir ?? ""}
          disabled={busy}
          onChange={(event) => {
            change({ ...options, target_subdir: event.target.value || null });
          }}
        />
      </label>
      {data && <FormatChoices data={data} options={options} busy={busy} onChange={change} />}
      <Space>
        <Button
          disabled={busy || !options.dataset_name}
          onClick={() => {
            onPreview(options);
          }}
        >
          预览入库
        </Button>
        <Button type="primary" disabled={!data || dirty || busy} onClick={onConfirm}>
          确认入库
        </Button>
      </Space>
    </>
  );
}

// 候选与默认勾选分别保存，取消全部勾选后仍能重新选回默认版本。
function FormatChoices({
  data,
  options,
  busy,
  onChange,
}: {
  data: IngestPreview;
  options: IngestOptions;
  busy: boolean;
  onChange: (options: IngestOptions) => void;
}): ReactElement {
  const selected = options.format_entries ?? [];
  const available = data.format_entry_options;
  return (
    <>
      {available.map((entry) => (
        <Checkbox
          key={`${entry.format}/${entry.version ?? ""}`}
          checked={selected.some(
            (item) => item.format === entry.format && item.version === entry.version,
          )}
          disabled={busy}
          onChange={(event) => {
            const entries = event.target.checked
              ? [...selected, entry]
              : selected.filter(
                  (item) => item.format !== entry.format || item.version !== entry.version,
                );
            onChange({ ...options, format_entries: entries });
          }}
        >
          按格式入口：{entry.format}/{entry.version}
        </Checkbox>
      ))}
    </>
  );
}

// 14 项沿用服务端的顺序，未知项保持空白，不在浏览器猜测数据属性。
function IngestContent({ data }: { data: IngestPreview }): ReactElement {
  return (
    <section>
      <Typography.Title level={4}>检查结果与数据集信息</Typography.Title>
      {data.checks.map((check) => (
        <div key={check}>{check}</div>
      ))}
      {data.notices.map((notice) => (
        <Alert key={notice} type="info" title={notice} />
      ))}
      {Object.entries(data.fields).map(([label, value]) => (
        <div key={label}>
          <Typography.Text strong>{label}：</Typography.Text>
          {value}
        </div>
      ))}
    </section>
  );
}
