// 数据集详情共享部件（11、16、M1-04）；索引时间和现场 JSON 时间不混为一份快照。
import { useState, type ReactElement } from "react";
import { Alert, Button, Card, Typography } from "antd";
import { rescanDataset, sizeDataset, type DatasetDetail } from "../api/datasets";
import { useAccountClient } from "../accounts/runtime";
import { useJobAction } from "../jobs/_actions";
import { DiagnosticCard, DiagnosticEntries } from "../DiagnosticCard";
import { toFailureView } from "../api/problems";
import { NavigationDocumentViewer } from "./Documents";
import { SubtasksViewer } from "./Subtasks";
import { DatasetSizeSummary } from "./Sizes";
import { DatasetInformation } from "./Information";
import { DatasetLinks, DatasetSources } from "./Entries";
import { useDatasetDetail } from "./queries";
import { formatDateTime } from "../time";

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
      <Button onClick={props.onClose}>返回列表</Button>
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
      <Typography.Title level={3}>{detail.entry.name}</Typography.Title>
      <p>{detail.entry.dataset_id ?? "身份未知"}</p>
      <p>{detail.entry.entry_path}</p>
      <p>索引时间：{formatDateTime(detail.indexed_at)}</p>
      <p>本次读取：{formatDateTime(detail.observed_at)}</p>
      <Card title="跨视图跳转">
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
      </Card>
      <DatasetSizeSummary size={detail.dataset_size} />
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
      {sizing.error && <DiagnosticCard failure={toFailureView(sizing.error)} />}
      {rescan.error && <DiagnosticCard failure={toFailureView(rescan.error)} />}
      <DatasetLinks links={detail.links} />
      <DatasetSources sources={detail.sources} />
      <DatasetInformation document={detail.canonical_information} />
      <DiagnosticEntries diagnostics={detail.diagnostics} />
      <NavigationDocumentViewer document={detail.information} />
      <NavigationDocumentViewer document={detail.original_paths} />
      <SubtasksViewer
        entryPath={detail.subtasks_entry_path}
        onStale={() => {
          setSubtaskStale(true);
        }}
      />
    </>
  );
}
