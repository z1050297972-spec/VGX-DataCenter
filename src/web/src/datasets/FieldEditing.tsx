// M1.5-10 详情就地编辑会话与底部操作；不提供独立编辑器或文档选择。
import { useEffect, type ReactElement, type ReactNode } from "react";
import { Alert, Button, Flex, Typography } from "antd";
import { DiagnosticCard, JobDiagnosticCard } from "../DiagnosticCard";
import type { EditablePage } from "../api/fieldEditing";
import { toFailureView } from "../api/problems";
import { FieldReview } from "./FieldReview";
import { InlineField } from "./InlineField";
import { useFieldEditing, type FieldEditingState } from "./fieldEditingState";
import { useDatasetFilterOptions } from "./queries";
import { useJob } from "../jobs/queries";
import { navigationJobSucceeded } from "./fieldEditingPolicy";
import "./fieldEditing.css";

interface SessionProps {
  /** 永久数据集编号；父组件按账号和入口隔离挂载。 */ datasetId: string;
  /** 将同一会话投影到详情各处。 */ children: (state: FieldEditingState) => ReactNode;
  /** 作业成功后退出编辑并刷新详情。 */ onFinish: () => void;
}
/**
 * 为整页提供跨文档草稿，写入成功后结束会话。
 * @param props - 数据集身份、详情渲染函数和完成回调。
 * @returns 详情内容及写入作业状态。
 * @throws 无；请求错误由详情底部操作区显示。
 * @sideEffects 读取两份文档编辑页；提交后轮询作业并刷新详情。
 * @timeSemantics 取消卸载即丢弃草稿；仅成功终态退出，排队与失败保留会话。
 */
export function InlineEditSession(props: SessionProps): ReactElement {
  const state = useFieldEditing(props.datasetId);
  return (
    <>
      {props.children(state)}
      {state.confirm.data && (
        <WriteCompletion jobId={state.confirm.data.job_id} onFinish={props.onFinish} />
      )}
    </>
  );
}
function WriteCompletion({
  jobId,
  onFinish,
}: {
  jobId: string;
  onFinish: () => void;
}): ReactElement {
  const job = useJob(jobId);
  const succeeded = navigationJobSucceeded(job.data);
  useEffect(() => {
    if (succeeded) onFinish();
  }, [succeeded, onFinish]);
  return (
    <>
      {job.error && <DiagnosticCard failure={toFailureView(job.error)} />}
      {job.data && <JobDiagnosticCard job={job.data} />}
    </>
  );
}
/**
 * 在编辑模式下按数据块显示可编辑字段及分页。
 * @param props - 跨文档编辑会话。
 * @param props.state - 数据块页与局部草稿。
 * @returns 只含用途、核验结论和说明的分节，不显示位置字段。
 * @throws 无。
 * @sideEffects 翻页读取下一页，不提交写入。
 * @timeSemantics 翻页保留草稿，提交期间禁用分页。
 */
export function SourceFieldSection({ state }: { state: FieldEditingState }): ReactElement {
  const data = state.sources.data;
  const groups = sourceGroups(data);
  return (
    <section aria-label="数据块字段" className="browser-detail-section">
      <Typography.Title level={4}>数据块字段</Typography.Title>
      {state.sources.isPending && <p role="status">正在读取数据块字段…</p>}
      {data && (
        <>
          {[...groups].map(([key, fields]) => (
            <div role="group" aria-label={`数据块 ${String(Number(key) + 1)}`} key={key}>
              {fields.map((field) => (
                <InlineField
                  key={JSON.stringify(field.path)}
                  state={state}
                  data={data}
                  field={field}
                />
              ))}
            </div>
          ))}
          {!groups.size && <p>没有数据块字段</p>}
          <Flex gap="small">
            <Button
              disabled={state.busy || state.offset === 0}
              onClick={() => {
                state.selectOffset(Math.max(0, state.offset - data.limit));
              }}
            >
              上一页
            </Button>
            <Button
              disabled={state.busy || state.offset + data.limit >= data.total}
              onClick={() => {
                state.selectOffset(state.offset + data.limit);
              }}
            >
              下一页
            </Button>
          </Flex>
        </>
      )}
    </section>
  );
}
/**
 * 汇总整页改动并提供一次预览、确认与取消。
 * @param props - 会话与取消回调。
 * @param props.state - 两份文档的草稿和提交门禁。
 * @param props.onCancel - 退出编辑，丢弃草稿并刷新详情。
 * @returns 操作按钮、诊断与已保存的预览差异。
 * @throws 无。
 * @sideEffects 预览与确认沿用现有接口，取消不写导航。
 * @timeSemantics 确认后等待写入终态，期间不允许修改或重复提交。
 */
export function InlineEditActions({
  state,
  onCancel,
}: {
  state: FieldEditingState;
  onCancel: () => void;
}): ReactElement {
  const vocabulary = useDatasetFilterOptions();
  const count = Object.keys(state.changes).length;
  return (
    <div className="browser-detail-section">
      <RecoveryStatus state={state} />
      {[
        state.information.error,
        state.sources.error,
        state.preview.error,
        state.confirm.error,
        state.block.error,
        vocabulary.error,
      ].map((error, i) =>
        error ? <DiagnosticCard key={i} failure={toFailureView(error)} /> : null,
      )}
      {state.stale && <Alert type="error" title="文件已变化，请取消编辑后重新加载" />}
      <p>已修改 {count} 项；场景单选、任务多选。</p>
      <Flex gap="small">
        <Button
          type="primary"
          loading={state.preview.isPending}
          disabled={!state.allowed || state.busy || state.stale || count === 0}
          onClick={state.submitPreview}
        >
          预览改动
        </Button>
        <Button
          aria-label="取消"
          disabled={state.preview.isPending || state.confirm.isPending}
          onClick={onCancel}
        >
          取消
        </Button>
      </Flex>
      {state.preview.data && (
        <FieldReview
          key={state.preview.data.job_id}
          jobId={state.preview.data.job_id}
          allowed={
            state.allowed && !state.confirm.isError && !state.confirm.isSuccess && !state.stale
          }
          pending={state.confirm.isPending}
          onConfirm={state.submitWrite}
        />
      )}
    </div>
  );
}

// 同一数据块的三项共用一个分组；忽略原始路径文档中的顶层备注。
function sourceGroups(data: EditablePage | undefined): Map<string, EditablePage["fields"]> {
  const groups = new Map<string, EditablePage["fields"]>();
  for (const field of data?.fields ?? []) {
    if (field.path[0] !== "sources") continue;
    const key = String(field.path[1]);
    groups.set(key, [...(groups.get(key) ?? []), field]);
  }
  return groups;
}
function RecoveryStatus({ state }: { state: FieldEditingState }): ReactElement {
  if (state.allowed) return <></>;
  const message = state.block.isError
    ? "无法核对导航层恢复状态，暂不能提交"
    : state.block.data?.blocked
      ? "导航层恢复失败，写操作被挡住"
      : "正在核对导航层恢复状态";
  return <Alert type="warning" title={message} />;
}
