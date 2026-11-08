// 转换关系只展示索引投影；人工记录按 record_id 删除，写入复用已有预览、确认和作业卡片。
import { useState, type ReactElement } from "react";
import { Link } from "@tanstack/react-router";
import { Alert, Button, Flex, Input, Modal, Select, Typography } from "antd";
import { useQuery } from "@tanstack/react-query";
import { useAccountClient, useCurrentAccount } from "../accounts/runtime";
import {
  DATASET_GC_TIME_MS,
  DATASET_PAGE_SIZE,
  DATASET_STALE_TIME_MS,
  listDatasets,
  type DatasetDetail,
} from "../api/datasets";
import { previewLineage, type LineageParameters } from "../api/lineage";
import { applyNavigationPreview } from "../api/dataOrigin";
import { toFailureView } from "../api/problems";
import { DiagnosticCard } from "../DiagnosticCard";
import { useJobAction } from "../jobs/_actions";
import { useRecoveryBlock } from "../navigation/queries";
import { recoveryReason } from "../navwrites/recoveryGate";
import { FieldReview } from "./FieldReview";

/** 人工登记最多 8 个输入、说明最多 500 字符，见 M3-05 契约。 */
const MAX_INPUTS = 8;
const MAX_NOTE_LENGTH = 500;

interface Props {
  /** 当前详情中的永久编号；未知身份不能登记。 */ datasetId: string | null;
  /** 服务端按记录展开的上下游关系，不在前端猜测转换来源。 */ lineage: DatasetDetail["lineage"];
}

/**
 * 展示数据集上下游及人工记录登记、删除入口。
 * @param props - 当前数据集编号和索引关系。
 * @returns 关系名称链接、说明和独立的预览确认对话框。
 * @throws 无；操作失败由统一诊断呈现。
 * @sideEffects 关系链接更新数据中心定位；打开对话框后读取恢复状态并按需请求候选和预览。
 * @timeSemantics 关系随详情缓存刷新；关闭对话框销毁草稿，写入终态由公共作业卡片刷新详情。
 */
export function DatasetLineage(props: Props): ReactElement {
  const [action, setAction] = useState<"add" | number | null>(null);
  // 同一条记录的多个输入展开显示，但删除作用于整条记录，只提供一个删除按钮。
  const records = [...new Set(props.lineage.upstream.map((item) => item.record_id))];
  return (
    <section aria-label="转换关系" className="browser-detail-section">
      <Flex justify="space-between" align="center">
        <Typography.Title level={5}>转换关系</Typography.Title>
        <Button
          disabled={!props.datasetId}
          onClick={() => {
            setAction("add");
          }}
        >
          登记转换来源
        </Button>
      </Flex>
      <Typography.Title level={5}>上游</Typography.Title>
      {records.length === 0 && <Typography.Paragraph>暂无转换来源</Typography.Paragraph>}
      {records.map((recordId) => {
        const inputs = props.lineage.upstream.filter((item) => item.record_id === recordId);
        const first = inputs[0];
        return (
          <div key={recordId}>
            {inputs.map((item, index) => (
              <Typography.Paragraph key={`${item.dataset_id}-${String(index)}`}>
                由 <RelatedDataset item={item} /> 转换
              </Typography.Paragraph>
            ))}
            {first?.note && <Typography.Paragraph>{first.note}</Typography.Paragraph>}
            {first?.removable && (
              <Button
                danger
                disabled={!props.datasetId}
                aria-label={`删除转换记录 ${String(recordId)}`}
                onClick={() => {
                  setAction(recordId);
                }}
              >
                删除
              </Button>
            )}
          </div>
        );
      })}
      <Typography.Title level={5}>下游</Typography.Title>
      {props.lineage.downstream.length === 0 && (
        <Typography.Paragraph>暂无转换产物</Typography.Paragraph>
      )}
      {props.lineage.downstream.map((item, index) => (
        <div key={`${item.dataset_id}-${String(item.record_id)}-${String(index)}`}>
          <Typography.Paragraph>
            转换出 <RelatedDataset item={item} />
          </Typography.Paragraph>
          {item.note && <Typography.Paragraph>{item.note}</Typography.Paragraph>}
        </div>
      ))}
      <Modal
        open={action !== null}
        title={actionTitle(action)}
        footer={null}
        destroyOnHidden
        onCancel={() => {
          setAction(null);
        }}
      >
        {action !== null && props.datasetId && (
          <LineageForm key={action} datasetId={props.datasetId} action={action} />
        )}
      </Modal>
    </section>
  );
}

function RelatedDataset({
  item,
}: {
  item: DatasetDetail["lineage"]["downstream"][number];
}): ReactElement {
  return item.entry_path ? (
    <Link to="/datasets" search={{ selected: item.entry_path, tree_view: "task" }}>
      {item.name ?? item.dataset_id}
    </Link>
  ) : (
    <Typography.Text>{item.name ?? item.dataset_id}（索引中不存在）</Typography.Text>
  );
}

function LineageForm({
  datasetId,
  action,
}: {
  datasetId: string;
  action: "add" | number;
}): ReactElement {
  const client = useAccountClient();
  const recovery = useRecoveryBlock();
  const reason = recoveryReason(recovery, "提交");
  const [inputs, setInputs] = useState<string[]>([]);
  const [note, setNote] = useState("");
  const preview = useJobAction<LineageParameters>(
    (payload, signal) => previewLineage({ client, payload, signal }),
    false,
  );
  const confirm = useJobAction<string>(
    (payload, signal) => applyNavigationPreview({ client, payload, signal }),
    { cardTitle: actionTitle(action) },
  );
  const busy = preview.isPending || confirm.isPending;
  const locked = busy || confirm.isSuccess;
  const blocked = !!reason || locked;
  const emptyInputs = action === "add" && inputs.length === 0;
  const allowed = !blocked && !confirm.isError;
  function edit(): void {
    preview.reset();
    confirm.reset();
  }
  return (
    <Flex vertical gap="middle">
      {reason && <Alert type="warning" title={reason} />}
      {[recovery.error, preview.error, confirm.error].map((error, index) =>
        error ? <DiagnosticCard key={index} failure={toFailureView(error)} /> : null,
      )}
      {action === "add" ? (
        <>
          <LineageInputs
            datasetId={datasetId}
            value={inputs}
            disabled={locked}
            onChange={(value) => {
              edit();
              setInputs(value);
            }}
          />
          <label>
            说明（可选）
            <Input.TextArea
              aria-label="转换说明"
              value={note}
              maxLength={MAX_NOTE_LENGTH}
              disabled={locked}
              showCount
              onChange={(event) => {
                edit();
                setNote(event.target.value);
              }}
            />
          </label>
        </>
      ) : (
        <Typography.Paragraph>
          删除记录 {action} 会移除该记录的全部转换来源。请先核对预览，再确认写入。
        </Typography.Paragraph>
      )}
      <Button
        disabled={blocked || emptyInputs}
        loading={preview.isPending}
        onClick={() => {
          if (blocked || emptyInputs) return;
          confirm.reset();
          preview.mutate(
            action === "add"
              ? {
                  dataset_id: datasetId,
                  action: "add",
                  input_dataset_ids: inputs,
                  note: note.trim() || null,
                }
              : {
                  dataset_id: datasetId,
                  action: "remove",
                  record_id: action,
                  input_dataset_ids: [],
                },
          );
        }}
      >
        生成转换关系预览
      </Button>
      {preview.data && (
        <FieldReview
          key={preview.data.job_id}
          jobId={preview.data.job_id}
          allowed={allowed}
          pending={confirm.isPending}
          onConfirm={(identifier) => {
            if (allowed) confirm.mutate(identifier);
          }}
        />
      )}
    </Flex>
  );
}

function LineageInputs(props: {
  datasetId: string;
  value: string[];
  disabled: boolean;
  onChange: (value: string[]) => void;
}): ReactElement {
  const client = useAccountClient();
  const account = useCurrentAccount();
  const [offset, setOffset] = useState(0);
  const candidates = useQuery({
    queryKey: ["datasets", account.data?.account_id, "lineage-inputs", offset],
    queryFn: ({ signal }) =>
      listDatasets({ client, payload: { offset, limit: DATASET_PAGE_SIZE }, signal }),
    retry: false,
    staleTime: DATASET_STALE_TIME_MS,
    gcTime: DATASET_GC_TIME_MS,
    refetchOnWindowFocus: false,
  });
  const unavailable = props.disabled || candidates.isPending || candidates.isError;
  const options = (candidates.data?.items ?? []).flatMap((item) =>
    item.dataset_id && item.dataset_id !== props.datasetId
      ? [{ value: item.dataset_id, label: `${item.name}（${item.dataset_id}）` }]
      : [],
  );
  return (
    <Flex vertical gap="small">
      {candidates.error && <DiagnosticCard failure={toFailureView(candidates.error)} />}
      <Typography.Text>来源数据集（1–{MAX_INPUTS} 个）</Typography.Text>
      <Select<string[]>
        mode="multiple"
        aria-label="来源数据集"
        virtual={false}
        disabled={unavailable}
        loading={candidates.isPending}
        value={props.value}
        maxCount={MAX_INPUTS}
        options={[
          // 翻页不能丢失已选项；未在本页的编号仍可移除，不全量加载索引。
          ...props.value
            .filter((value) => !options.some((item) => item.value === value))
            .map((value) => ({ value, label: value })),
          ...options,
        ]}
        onChange={props.onChange}
      />
      <Flex gap="small">
        <Button
          disabled={unavailable || offset === 0}
          onClick={() => {
            setOffset(Math.max(0, offset - DATASET_PAGE_SIZE));
          }}
        >
          上一页来源
        </Button>
        <Button
          disabled={unavailable || offset + DATASET_PAGE_SIZE >= candidates.data.total}
          onClick={() => {
            setOffset(offset + DATASET_PAGE_SIZE);
          }}
        >
          下一页来源
        </Button>
      </Flex>
    </Flex>
  );
}

// 登记与删除沿用同一流程，操作名称在对话框和作业卡片中保持一致。
function actionTitle(action: "add" | number | null): string {
  return action === "add" ? "登记转换来源" : "删除转换记录";
}
