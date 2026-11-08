// 入库预览由 worker 生成；修改任何选项后必须重新预览才能确认。
import { useEffect, useRef, useState, type ReactElement } from "react";
import { Alert, Button, Card, Checkbox, Input, Space, Typography } from "antd";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useAccountClient } from "../accounts/runtime";
import {
  confirmIngest,
  getIngestPreview,
  submitIngestPreview,
  type IngestOptions,
  type IngestPreview as DownloadPreview,
} from "../api/downloadIngest";
import {
  confirmIngest as confirmConversion,
  getIngestPreview as getConversionPreview,
  submitIngestPreview as submitConversionPreview,
  type IngestPreview as ConversionPreview,
} from "../api/conversionIngest";
import { getJob, JOB_POLL_INTERVAL_MS, type Job } from "../api/jobs";
import { toFailureView } from "../api/problems";
import { DiagnosticCard, DiagnosticEntries, JobDiagnosticCard } from "../DiagnosticCard";
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

type IngestPreview = DownloadPreview | ConversionPreview;
type IngestJob = Pick<Job, "job_id" | "parameters">;

/**
 * 从转换详情或暂存列表开始检查并入库。
 * @param props - 转换身份。
 * @param props.jobId - 规范十进制转换编号。
 * @param props.disabled - 当前有作业占用时禁止重复开始，已经展开的检查继续显示。
 * @returns 检查按钮与worker预览表单。
 * @throws Error 缺少应用提供器。
 * @sideEffects 用户展开后自动提交一次检查；确认仍需明确操作。
 * @timeSemantics 检查运行中每秒轮询，卸载取消请求。
 */
export function IngestConversion({
  jobId,
  disabled = false,
}: {
  jobId: string;
  disabled?: boolean;
}): ReactElement {
  const [open, setOpen] = useState(false);
  return (
    <section>
      <Button
        disabled={disabled}
        onClick={() => {
          setOpen(true);
        }}
      >
        检查并入库
      </Button>
      {open && <IngestForm job={{ job_id: jobId, parameters: {} }} conversion />}
    </section>
  );
}

// 查询只在收到成功终态后读取预览，错误交统一组件处理。
function useIngestResult(previewId: string, generation: number, conversion: boolean) {
  const client = useAccountClient();
  const status = useQuery({
    queryKey: ["jobs", "ingest-preview", previewId, generation],
    queryFn: ({ signal }) => getJob({ client, jobId: previewId, payload: undefined, signal }),
    enabled: !!previewId,
    refetchInterval: (query) =>
      query.state.data && isJobTerminal(query.state.data) ? false : JOB_POLL_INTERVAL_MS,
    retry: false,
  });
  const result = useQuery<IngestPreview>({
    queryKey: ["downloads", "ingest-preview", previewId, generation],
    queryFn: ({ signal }) =>
      (conversion ? getConversionPreview : getIngestPreview)(client, previewId, signal),
    enabled:
      !!previewId &&
      (status.data?.summary?.outcome === "succeeded" ||
        (conversion && status.data?.summary?.outcome === "succeeded_with_warnings")),
    retry: false,
  });
  return { status, result };
}

// POST 的 AbortController 跟随组件生命周期；提交失败不自动重试。
function IngestForm({
  job,
  conversion = false,
}: {
  job: IngestJob;
  conversion?: boolean;
}): ReactElement {
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
        return await (conversion ? submitConversionPreview : submitIngestPreview)(
          client,
          job.job_id,
          options,
          active.current.signal,
        );
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
  const started = useRef(false);
  const startPreview = create.mutate;
  useEffect(() => {
    if (conversion && !started.current) {
      started.current = true;
      startPreview({});
    }
  }, [conversion, startPreview]);
  const { status, result } = useIngestResult(previewId, generation, conversion);
  const confirm = useMutation({
    mutationFn: async () => {
      active.current = new AbortController();
      try {
        return await (conversion ? confirmConversion : confirmIngest)(
          client,
          previewId,
          active.current.signal,
        );
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
        {conversion
          ? "位置填写同一可写存储根内的相对路径。"
          : `存储根：${String(job.parameters.storage_root)}；位置填写该根内的相对路径。`}
      </Typography.Text>
      <IngestEditor
        key={editorKey}
        initial={initialOptions(job, result.data, create.variables, conversion)}
        data={result.data}
        busy={busy}
        conversion={conversion}
        onPreview={(options) => {
          create.mutate(options);
        }}
        onConfirm={() => {
          confirm.mutate();
        }}
      />
      {waiting && <Typography.Text>正在生成入库预览…</Typography.Text>}
      {result.data && (
        <Card>
          <IngestContent data={result.data} />
        </Card>
      )}
      <FailedPreview job={status.data} conversion={conversion} />
      {[create, status, result, confirm].map((query, index) =>
        query.isError ? <DiagnosticCard key={index} failure={toFailureView(query.error)} /> : null,
      )}
    </Space>
  );
}

// 作业失败和检查不通过都展示统一诊断，报告仍保留在作业进度里。
function FailedPreview({
  job,
  conversion,
}: {
  job: Job | undefined;
  conversion: boolean;
}): ReactElement | null {
  if (!job || !failedPreview(job, conversion)) return null;
  return (
    <>
      <Alert type="error" title="入库预览未成功" />
      <JobDiagnosticCard job={job} />
      {job.progress?.ingest_check && (
        <DiagnosticEntries
          diagnostics={job.progress.ingest_check.report.layers.flatMap(
            (layer) => layer.diagnostics,
          )}
        />
      )}
    </>
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
function failedPreview(job: Job | undefined, conversion: boolean): boolean {
  return (
    !!job &&
    isJobTerminal(job) &&
    job.summary?.outcome !== "succeeded" &&
    !(conversion && job.summary?.outcome === "succeeded_with_warnings")
  );
}

// 用新预览作为组件 key 重新初始化编辑器，避免 effect 复制远端状态造成级联渲染。
function initialOptions(
  job: IngestJob,
  data: IngestPreview | undefined,
  submitted: IngestOptions | undefined,
  conversion: boolean,
): IngestOptions {
  if (data) {
    const { dataset_name, target_subdir, format_entries } = data.parameters;
    return { dataset_name, target_subdir, format_entries };
  }
  if (submitted) return submitted;
  if (conversion) return { dataset_name: null, target_subdir: null, format_entries: null };
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
  conversion,
}: {
  initial: IngestOptions;
  data: IngestPreview | undefined;
  busy: boolean;
  conversion: boolean;
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
            change({ ...options, dataset_name: event.target.value || null });
          }}
        />
      </label>
      <label>
        存放位置
        <Input
          aria-label="入库存放位置"
          placeholder={
            conversion ? "默认：转换/数据集名" : "默认：下载/命名空间/仓库@commit 前 12 位"
          }
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
          disabled={busy || (!conversion && !options.dataset_name)}
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
      {"check" in data && (
        <Alert
          type={data.check.result === "有警告" ? "warning" : "success"}
          title={data.check.result}
        />
      )}
      {"check" in data && (
        <DiagnosticEntries diagnostics={data.check.layers.flatMap((layer) => layer.diagnostics)} />
      )}
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
