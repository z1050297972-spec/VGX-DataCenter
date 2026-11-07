// M1.5-10 详情就地编辑会话与底部操作；不提供独立编辑器或文档选择。
import { useEffect, type ReactElement, type ReactNode } from "react";
import { Alert, Button, Flex } from "antd";
import { DiagnosticCard, JobDiagnosticCard } from "../DiagnosticCard";
import { toFailureView } from "../api/problems";
import { FieldReview } from "./FieldReview";
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
 * 为整页提供数据集信息草稿，写入成功后结束会话。
 * @param props - 数据集身份、详情渲染函数和完成回调。
 * @returns 详情内容及写入作业状态。
 * @throws 无；请求错误由详情底部操作区显示。
 * @sideEffects 读取数据集信息编辑页；提交后轮询作业并刷新详情。
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
 * 汇总整页改动并提供一次预览、确认与取消。
 * @param props - 会话与取消回调。
 * @param props.state - 数据集信息的草稿和提交门禁。
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
        state.preview.error,
        state.confirm.error,
        state.block.error,
        vocabulary.error,
      ].map((error, i) =>
        error ? <DiagnosticCard key={i} failure={toFailureView(error)} /> : null,
      )}
      {state.stale && <Alert type="error" title="文件已变化，请取消编辑后重新加载" />}
      <p>已修改 {count} 项；场景和任务可多选。</p>
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

function RecoveryStatus({ state }: { state: FieldEditingState }): ReactElement {
  if (state.allowed) return <></>;
  const message = state.block.isError
    ? "无法核对导航层恢复状态，暂不能提交"
    : state.block.data?.blocked
      ? "导航层恢复失败，写操作被挡住"
      : "正在核对导航层恢复状态";
  return <Alert type="warning" title={message} />;
}
