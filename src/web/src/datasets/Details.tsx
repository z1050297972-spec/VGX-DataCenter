// 数据集详情共享部件（11、16、M1-04）；索引时间和现场 JSON 时间不混为一份快照。
import { lazy, Suspense, useState, type ReactElement } from "react";
import { Alert, Button, Col, Flex, Row, Typography } from "antd";
import { rescanDataset, sizeDataset, type DatasetDetail } from "../api/datasets";
import { useAccountClient } from "../accounts/runtime";
import { useJobAction } from "../jobs/_actions";
import { DiagnosticCard, DiagnosticEntries } from "../DiagnosticCard";
import { toFailureView } from "../api/problems";
import { NavigationDocumentViewer } from "./Documents";
import { SubtasksViewer } from "./Subtasks";
import { DatasetSizeSummary } from "./Sizes";
import { RepointEditor } from "./Repoint";
import { FileViewerEntry } from "./FileViewerEntry";
import { DataOriginEditor } from "./DataOrigin";
import { DatasetInformation } from "./Information";
import { DatasetLinks, DatasetSources } from "./Entries";
import { CreateLinkEntry } from "./CreationEntries";
import { useDatasetDetail } from "./queries";
import { formatDateTime } from "../time";

// 编辑器按需分块，保持主入口体积预算。
const FieldEditor = lazy(async () => ({
  default: (await import("./FieldEditing")).DatasetFieldEditor,
}));

interface DetailProps {
  /** 当前相对入口路径。 */ entryPath: string;
  /** 跨视图时给出完整入口，布局负责更新 URL。 */ onJump: (entry: DatasetDetail["entry"]) => void;
  /** 返回列表，不清除筛选。 */ onClose: () => void;
}
/**
 * 显示当前入口详情及全部关联入口的位置。
 * @param props - 入口路径、跳转和返回回调。
 * @returns 基本信息、大小与独立请求诊断。
 * @throws 无；查询失败以 DiagnosticCard 呈现。
 * @sideEffects useDatasetDetail 读取当前入口；跳转调用 onJump，不直接打开文件路径。
 * @timeSemantics 统计、索引、观察时间分别显示，UTC 仅显示时转本地。
 */
export function DatasetDetails(props: DetailProps): ReactElement {
  const query = useDatasetDetail(props.entryPath);
  return (
    <section aria-label="数据集详情">
      <Flex justify="space-between" align="center" gap="middle" wrap>
        <Flex align="center" gap="small" wrap>
          <Button type="text" onClick={props.onClose}>
            返回列表
          </Button>
          {query.data && (
            <Typography.Title level={3} className="browser-detail-title">
              {query.data.entry.name}
            </Typography.Title>
          )}
        </Flex>
        {query.data && (
          <Flex gap="small" wrap>
            <CreateLinkEntry datasetId={query.data.entry.dataset_id} />
            <RepointEditor detail={query.data} />
          </Flex>
        )}
      </Flex>
      {query.isPending && <p role="status">正在加载详情</p>}
      {query.error && <DiagnosticCard failure={toFailureView(query.error)} />}
      {query.data && <DetailContent detail={query.data} onJump={props.onJump} />}
    </section>
  );
}

function DetailContent({
  detail,
  onJump,
}: {
  detail: DatasetDetail;
  onJump: DetailProps["onJump"];
}): ReactElement {
  const [subtaskStale, setSubtaskStale] = useState(false);
  const client = useAccountClient();
  const rescan = useJobAction(
    (datasetId: string, signal) => rescanDataset({ client, payload: datasetId, signal }),
    true,
  );
  const sizing = useJobAction(
    (datasetId: string, signal) => sizeDataset({ client, payload: datasetId, signal }),
    true,
  );
  return (
    <>
      {(detail.index_stale || subtaskStale) && (
        <Alert
          type="warning"
          title="索引过期"
          description="导航文件已变化，链接状态和大小可能过期。"
          action={
            <Button
              disabled={!detail.entry.dataset_id || rescan.isPending}
              onClick={() => {
                if (detail.entry.dataset_id) rescan.mutate(detail.entry.dataset_id);
              }}
            >
              重新扫描
            </Button>
          }
        />
      )}
      <div className="browser-detail-section">
        <Row gutter={[16, 8]} className="browser-detail-summary">
          <Col xs={24} md={12}>
            <p className="browser-detail-mono">{detail.entry.dataset_id ?? "身份未知"}</p>
          </Col>
          <Col xs={24} md={12}>
            <p className="browser-detail-mono">{detail.entry.entry_path}</p>
          </Col>
          <Col xs={24} md={12}>
            <p>索引时间：{formatDateTime(detail.indexed_at)}</p>
          </Col>
          <Col xs={24} md={12}>
            <p>本次读取：{formatDateTime(detail.observed_at)}</p>
          </Col>
        </Row>
      </div>
      <section className="browser-detail-section">
        <Typography.Title level={5}>跨视图跳转</Typography.Title>
        {detail.entries
          .filter((entry) => entry.entry_path !== detail.entry.entry_path)
          .map((entry) => (
            <Button
              key={entry.entry_path}
              aria-label={`跳转到 ${entry.entry_path}`}
              onClick={() => {
                onJump(entry);
              }}
            >
              {entry.entry_path}
            </Button>
          ))}
      </section>
      {detail.entry.dataset_id && (
        <div className="browser-detail-section">
          <DataOriginEditor datasetId={detail.entry.dataset_id} provenance={detail.provenance} />
        </div>
      )}
      <div className="browser-detail-section">
        <FieldEditEntry detail={detail} />
      </div>
      <div className="browser-detail-section">
        <DatasetSizeSummary
          size={detail.dataset_size}
          actions={
            <>
              <Button
                disabled={!detail.entry.dataset_id || rescan.isPending}
                loading={rescan.isPending}
                onClick={() => {
                  if (detail.entry.dataset_id) rescan.mutate(detail.entry.dataset_id);
                }}
              >
                重新检查
              </Button>
              <Button
                disabled={!detail.entry.dataset_id || sizing.isPending}
                loading={sizing.isPending}
                onClick={() => {
                  if (detail.entry.dataset_id) sizing.mutate(detail.entry.dataset_id);
                }}
              >
                统计大小
              </Button>
            </>
          }
        />
        {sizing.error && <DiagnosticCard failure={toFailureView(sizing.error)} />}
        {rescan.error && <DiagnosticCard failure={toFailureView(rescan.error)} />}
        <FileViewerEntry
          key={detail.entry.dataset_id}
          datasetId={detail.entry.dataset_id}
          linkNames={detail.links.map((link) => link.name)}
        />
      </div>
      <div className="browser-detail-section">
        <DatasetLinks links={detail.links} />
      </div>
      <div className="browser-detail-section">
        <DatasetSources sources={detail.sources} />
      </div>
      <div className="browser-detail-section">
        <DatasetInformation document={detail.canonical_information} />
      </div>
      <div className="browser-detail-section">
        <DiagnosticEntries diagnostics={detail.diagnostics} />
      </div>
      <div className="browser-detail-section">
        <NavigationDocumentViewer document={detail.information} />
      </div>
      <div className="browser-detail-section">
        <NavigationDocumentViewer document={detail.original_paths} />
      </div>
      <div className="browser-detail-section">
        <SubtasksViewer
          entryPath={detail.subtasks_entry_path}
          onStale={() => {
            setSubtaskStale(true);
          }}
        />
      </div>
    </>
  );
}

function FieldEditEntry({ detail }: { detail: DatasetDetail }): ReactElement {
  if (!detail.entry.dataset_id) return <></>;
  return (
    <Suspense fallback={<p>正在加载编辑器…</p>}>
      <FieldEditor
        key={JSON.stringify([detail.entry.dataset_id, detail.canonical_information?.sha256])}
        datasetId={detail.entry.dataset_id}
      />
    </Suspense>
  );
}
