// M1.5-02 规范副本字段编辑入口；会话与表单投影分别管理生命周期和渲染。
import { useState, type ReactElement } from "react";
import { Alert, Button, Select } from "antd";
import { useCurrentAccount } from "../accounts/runtime";
import type { EditableDocument } from "../api/fieldEditing";
import { DiagnosticCard } from "../DiagnosticCard";
import { toFailureView } from "../api/problems";
import { FieldReview } from "./FieldReview";
import { FieldInputs } from "./FieldInputs";
import { useFieldEditing, type FieldEditingState } from "./fieldEditingState";
import "./fieldEditing.css";

interface Props {
  /** 永久编号；切换数据集或账号时重新挂载以隔离草稿。 */ datasetId: string;
}
const DOCUMENTS: EditableDocument[] = ["数据集信息.json", "子任务.json", "原始路径.json"];

/**
 * 在详情中打开导航字段的分页编辑流程。
 * @param props - 数据集的永久编号，不从格式入口构造规范路径。
 * @returns 编辑开关和表单；关闭丢弃草稿，避免误用旧预览。
 * @throws 无；请求故障由统一诊断展示。
 * @sideEffects 打开才读取编辑页；预览与确认各POST一次，确认成功进入作业详情。
 * @timeSemantics 不轮询表单；预览及恢复标记沿用每秒轮询，离页取消请求。
 */
export function DatasetFieldEditor(props: Props): ReactElement {
  const [open, setOpen] = useState(false);
  const account = useCurrentAccount();
  return (
    <section className="field-editor" aria-label="导航层字段编辑">
      <Button
        aria-label={open ? "取消字段编辑" : "编辑导航层字段"}
        onClick={() => {
          setOpen(!open);
        }}
      >
        {open ? "取消编辑" : "编辑导航层字段"}
      </Button>
      <p>大小、链接状态、在线状态、一致性、索引时间和位置字段：自动计算。数据盘文件：原文件。</p>
      {open && (
        <FieldForm
          key={JSON.stringify([account.data?.account_id, props.datasetId])}
          datasetId={props.datasetId}
        />
      )}
    </section>
  );
}

function FieldForm({ datasetId }: Props): ReactElement {
  const state = useFieldEditing(datasetId);
  const count = Object.keys(state.changes).length;
  return (
    <>
      <RecoveryStatus state={state} />
      <label>
        编辑文件
        <Select<EditableDocument>
          virtual={false}
          aria-label="选择编辑文件"
          value={state.document}
          disabled={state.busy}
          options={DOCUMENTS.map((value) => ({ value, label: value }))}
          getPopupContainer={(trigger: HTMLElement): HTMLElement =>
            trigger.parentElement ?? trigger
          }
          onChange={state.selectDocument}
        />
      </label>
      {state.page.isPending && <p role="status">正在读取编辑项…</p>}
      <Failures errors={[state.page.error, state.preview.error, state.confirm.error]} />
      {state.stale && <Alert type="error" title="文件已变化，请取消编辑后重新加载" />}
      {state.page.data && <FieldInputs state={state} data={state.page.data} />}
      <p>已修改 {count} 项；场景单选、任务多选，保存词表编码。</p>
      <Button
        aria-label="预览字段改动"
        loading={state.preview.isPending}
        disabled={!state.allowed || state.busy || state.stale || count === 0}
        onClick={state.submitPreview}
      >
        预览改动
      </Button>
      <Review state={state} />
    </>
  );
}
function Review({ state }: { state: FieldEditingState }): ReactElement {
  if (!state.preview.data) return <></>;
  return (
    <FieldReview
      key={state.preview.data.job_id}
      jobId={state.preview.data.job_id}
      allowed={state.allowed && !state.confirm.isError && !state.stale}
      pending={state.confirm.isPending}
      onConfirm={state.submitWrite}
    />
  );
}
function RecoveryStatus({ state }: { state: FieldEditingState }): ReactElement {
  if (state.allowed) return <></>;
  const message = state.block.isError
    ? "无法核对导航层恢复状态，暂不能提交"
    : state.block.data?.blocked
      ? "导航层恢复失败，写操作被挡住"
      : "正在核对导航层恢复状态";
  return (
    <>
      <Alert type="warning" title={message} />
      <Failures errors={[state.block.error]} />
    </>
  );
}
function Failures({ errors }: { errors: (Error | null)[] }): ReactElement {
  return (
    <>
      {errors.map((error, index) =>
        error ? <DiagnosticCard key={index} failure={toFailureView(error)} /> : null,
      )}
    </>
  );
}
