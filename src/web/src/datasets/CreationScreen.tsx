// 两个创建路由的流程装配；参数只留内存，确认永远引用保存的同一份预览。
import { useCallback, useState, type ReactElement } from "react";
import { Alert, Breadcrumb, Button, Typography } from "antd";
import { useNavigate } from "@tanstack/react-router";
import { useDatasetBrowser } from "./queries";
import { CreateDatasetForm, CreateLinkForm, FormatEntryPicker } from "./CreationForms";
import { CreationReview, CreationQueueWarning, CreationConflict } from "./CreationReview";
import { DiagnosticCard, JobDiagnosticCard } from "../DiagnosticCard";
import { useCreationFlow, type CreationSearch, type CreationFlow } from "./creationState";
import type {
  CreationPreview,
  DatasetPreviewInput,
  LinkPreviewInput,
  FormatSelection,
} from "../api/datasetCreation";
import type { DatasetList } from "../api/datasets";
import type { Job } from "../api/jobs";
import "./creation.css";

/** 创建页面的受控路由上下文。 */
export interface CreationScreenProps {
  /** 当前操作固定为建链或新增数据集。 */
  operation: CreationPreview["operation"];
  /** 经真实 Router 校验的文本编号。 */
  search: CreationSearch;
}
/**
 * 装配表单、预览、队列确认和恢复失败门禁。
 * @param props - 当前操作与类型化 URL 定位。
 * @returns 创建流程页面，错误保留为统一诊断。
 * @throws 无；网络错误由诊断组件显示。
 * @sideEffects Query读取候选和预览，确认成功留在原页显示作业卡片，URL保存模式与预览编号。
 * @timeSemantics 轮询、超时和取消沿用 useCreationFlow；表单参数不写持久存储。
 */
export function CreationScreen(props: CreationScreenProps): ReactElement {
  const navigate = useNavigate();
  const [link, setLink] = useState<LinkPreviewInput>({
    dataset_id: props.search.dataset_id ?? "",
    link: { name: "", target_path: "", fallback_format: null },
    format_entries: [],
  });
  const [dataset, setDataset] = useState<DatasetPreviewInput>({
    collection: initialCollection(props.search.mode),
    dataset_name: "",
    data_origin: "",
    link: { name: "", target_path: "", fallback_format: null },
    format_entries: [],
  });
  const [offset, setOffset] = useState(0);
  const browser = useDatasetBrowser({ offset, limit: 100 });
  const onPreviewed = useCallback(
    (preview: CreationPreview) => {
      void navigate({
        to: props.operation === "create_link" ? "/datasets/links/new" : "/datasets/new",
        search: {
          dataset_id: preview.operation === "create_link" ? preview.dataset_id : undefined,
          preview_job_id: preview.preview_job_id,
          mode: props.search.mode,
        },
        replace: true,
      });
    },
    [navigate, props.operation, props.search.mode],
  );
  const flow = useCreationFlow({
    operation: props.operation,
    previewJobId: props.search.preview_job_id,
    onPreviewed,
  });
  const busy = flow.blocked || flow.stage === "previewing" || flow.stage === "submitting";
  const baseLink =
    flow.preview && "dataset_id" in flow.preview.parameters ? flow.preview.parameters : link;
  const baseDataset =
    flow.preview && "dataset_name" in flow.preview.parameters ? flow.preview.parameters : dataset;
  function clearPreview(): void {
    flow.edit();
    void navigate({
      to: props.operation === "create_link" ? "/datasets/links/new" : "/datasets/new",
      search: {
        mode: props.search.mode,
        dataset_id: props.operation === "create_link" ? baseLink.dataset_id : undefined,
      },
      replace: true,
    });
  }
  function changeFormats(values: FormatSelection[]): void {
    if (props.operation === "create_link") setLink({ ...baseLink, format_entries: values });
    else setDataset({ ...baseDataset, format_entries: values });
    clearPreview();
  }
  return (
    <section className="creation-page">
      <header className="app-page-header creation-header">
        <Breadcrumb
          items={[
            { title: "数据集" },
            { title: props.operation === "create_link" ? "建链" : "新增" },
          ]}
        />
        <Typography.Title level={2} className="app-page-title">
          {creationTitle(props.operation, props.search.mode)}
        </Typography.Title>
      </header>
      <FlowFeedback flow={flow} onEdit={clearPreview} />
      <CreationBody
        flow={flow}
        operation={props.operation}
        link={link}
        collectionMode={props.search.mode === "collection"}
        dataset={dataset}
        list={browser.list.data}
        offset={offset}
        busy={busy}
        onLink={(value) => {
          setLink(value);
          clearPreview();
        }}
        onDataset={(value) => {
          setDataset(value);
          clearPreview();
        }}
        onPage={setOffset}
        onFormats={changeFormats}
        onEdit={() => {
          setLink(baseLink);
          setDataset(baseDataset);
          clearPreview();
        }}
      />
      <QueueConfirmation flow={flow} busy={busy} onEdit={clearPreview} />
      <Button
        aria-label="返回数据集"
        onClick={() => {
          void navigate({ to: "/datasets", search: {} });
        }}
      >
        返回数据集
      </Button>
    </section>
  );
}

function FlowFeedback({ flow, onEdit }: { flow: CreationFlow; onEdit: () => void }): ReactElement {
  return (
    <>
      {flow.blockedReason && (
        <Alert
          type="error"
          title={flow.blockedReason}
          description="导航层恢复完成后才能提交，可从顶部提示进入恢复页。"
        />
      )}
      <FlowFailure flow={flow} onEdit={onEdit} />
      <PreviewFailure job={flow.previewJob} />
      {flow.stage === "previewing" && <p role="status">正在生成预览…</p>}
    </>
  );
}
function FlowFailure({
  flow,
  onEdit,
}: {
  flow: CreationFlow;
  onEdit: () => void;
}): ReactElement | null {
  if (!flow.failure) return null;
  if (
    flow.failure.kind === "problem" &&
    flow.failure.problem.status === 409 &&
    !flow.queuedJobs.length
  )
    return <CreationConflict failure={flow.failure} onPreviewAgain={onEdit} />;
  return <DiagnosticCard failure={flow.failure} />;
}
function PreviewFailure({ job }: { job: Job | undefined }): ReactElement | null {
  if (job?.state !== "completed" || job.summary?.outcome !== "failed") return null;
  return (
    <>
      <Alert type="error" title="预览未成功，请修改参数后重新预览" />
      <JobDiagnosticCard job={job} />
    </>
  );
}
interface BodyProps {
  flow: CreationFlow;
  operation: CreationPreview["operation"];
  link: LinkPreviewInput;
  collectionMode: boolean;
  dataset: DatasetPreviewInput;
  list: DatasetList | undefined;
  offset: number;
  busy: boolean;
  onLink: (value: LinkPreviewInput) => void;
  onDataset: (value: DatasetPreviewInput) => void;
  onPage: (offset: number) => void;
  onFormats: (values: FormatSelection[]) => void;
  onEdit: () => void;
}
function CreationBody(props: BodyProps): ReactElement {
  const { flow } = props;
  if (!flow.options) return <p role="status">正在读取创建选项…</p>;
  if (flow.preview)
    return (
      <PreviewBody
        flow={flow}
        busy={props.busy}
        onFormats={props.onFormats}
        onEdit={props.onEdit}
      />
    );
  if (props.operation === "create_link")
    return (
      <CreateLinkForm
        value={props.link}
        options={flow.options}
        entryOptions={flow.formatEntryOptions}
        datasets={
          props.list ?? { items: [], total: 0, offset: props.offset, limit: 100, indexed_at: null }
        }
        pending={props.busy}
        onChange={props.onLink}
        onPreview={flow.previewParameters}
        onDatasetPage={props.onPage}
      />
    );
  return (
    <CreateDatasetForm
      collectionMode={props.collectionMode}
      value={props.dataset}
      options={flow.options}
      entryOptions={flow.formatEntryOptions}
      pending={props.busy}
      onChange={props.onDataset}
      onPreview={flow.previewParameters}
    />
  );
}
function PreviewBody({
  flow,
  busy,
  onFormats,
  onEdit,
}: {
  flow: CreationFlow;
  busy: boolean;
  onFormats: (values: FormatSelection[]) => void;
  onEdit: () => void;
}): ReactElement | null {
  const preview = flow.preview;
  if (!preview || !flow.options) return null;
  return (
    <>
      <FormatEntryPicker
        options={flow.options.formats}
        choices={flow.formatEntryOptions}
        value={preview.parameters.format_entries}
        disabled={busy}
        onChange={onFormats}
      />
      <CreationReview
        preview={preview}
        pending={busy}
        submitted={flow.stage === "submitted"}
        onEdit={onEdit}
        onConfirm={() => {
          flow.confirm({ preview_job_id: preview.preview_job_id, acknowledged_queue_job_ids: [] });
        }}
      />
    </>
  );
}
function QueueConfirmation({
  flow,
  busy,
  onEdit,
}: {
  flow: CreationFlow;
  busy: boolean;
  onEdit: () => void;
}): ReactElement | null {
  if (!flow.queuedJobs.length || !flow.preview) return null;
  const preview = flow.preview;
  return (
    <CreationQueueWarning
      key={flow.queuedJobs.map((item) => item.job_id).join(",")}
      jobs={flow.queuedJobs}
      pending={busy}
      onCancel={onEdit}
      onAcknowledge={(ids) => {
        flow.confirm({ preview_job_id: preview.preview_job_id, acknowledged_queue_job_ids: ids });
      }}
    />
  );
}

// 模式只决定初始草稿；恢复时采用服务端预览保存的参数。
function initialCollection(mode: CreationSearch["mode"]): DatasetPreviewInput["collection"] {
  return mode === "collection"
    ? { status: "planned", method_id: null, purpose_id: null, robot_ids: [] }
    : null;
}
// 标题区分采集模式，底层作业仍沿用新增数据集。
function creationTitle(
  operation: CreationPreview["operation"],
  mode: CreationSearch["mode"],
): string {
  if (operation === "create_link") return "建链";
  return mode === "collection" ? "新建采集任务" : "新增数据集";
}
