// M1.5-02 作业页撤回入口；复用L16反向预览与通用写入，不根据浏览器草稿恢复文件。
import type { ReactElement } from "react";
import { Button, Alert } from "antd";
import { useAccountClient } from "../accounts/runtime";
import type { Job } from "../api/jobs";
import { previewFieldUndo } from "../api/fieldEditing";
import { applyNavigationPreview } from "../api/dataOrigin";
import { useJobAction } from "../jobs/_actions";
import { useRecoveryBlock } from "../navigation/queries";
import { DiagnosticCard } from "../DiagnosticCard";
import { toFailureView } from "../api/problems";
import { navigationJobSucceeded } from "./fieldEditingPolicy";
import { FieldReview } from "./FieldReview";
import "./fieldEditing.css";

interface Props {
  /** 已读取的作业，只有成功的nav_write_apply提供撤回入口。 */ job: Job;
}
/**
 * 为成功的导航写作业提供预览和明确确认的撤回流程。
 * @param props - 作业记录，不依赖本地保存的历史草稿。
 * @returns 撤回预览按钮、全量后像核对结果及反向写入确认。
 * @throws 无；冲突、缺变更记录和传输错误使用统一诊断。
 * @sideEffects 预览POST提交nav_revert_preview，确认POST提交nav_write_apply并进入作业页。
 * @timeSemantics 沿用每秒恢复状态和预览作业轮询；离页取消，POST不重试。
 */
export function FieldUndo(props: Props): ReactElement {
  if (props.job.type_name !== "nav_write_apply" || !navigationJobSucceeded(props.job)) return <></>;
  return <UndoForm key={props.job.job_id} job={props.job} />;
}

function UndoForm(props: Props): ReactElement {
  const client = useAccountClient();
  const preview = useJobAction<string>(
    (payload, signal) => previewFieldUndo({ client, payload, signal }),
    false,
  );
  const apply = useJobAction<string>(
    (payload, signal) => applyNavigationPreview({ client, payload, signal }),
    true,
  );
  const block = useRecoveryBlock();
  const allowed = !block.isError && block.data?.blocked === false;
  return (
    <section className="field-editor" aria-label="撤回导航改动">
      <p>
        撤回作业 #{props.job.job_id}：恢复该次作业修改前的全部导航文件；中途又有改动时会冲突失败。
      </p>
      {!allowed && <Alert type="warning" title="导航层恢复状态尚不允许写入" />}
      <Button
        aria-label="预览撤回导航改动"
        disabled={!allowed || preview.isPending || apply.isPending}
        loading={preview.isPending}
        onClick={() => {
          apply.reset();
          preview.mutate(props.job.job_id);
        }}
      >
        预览撤回
      </Button>
      <UndoErrors errors={[block.error, preview.error, apply.error]} />
      <UndoReview
        identifier={preview.data?.job_id}
        allowed={allowed && !apply.isError}
        pending={apply.isPending}
        onConfirm={(identifier) => {
          if (allowed && !apply.isError) apply.mutate(identifier);
        }}
      />
    </section>
  );
}

function UndoErrors({ errors }: { errors: (Error | null)[] }): ReactElement {
  return (
    <>
      {errors.map((error, index) =>
        error ? <DiagnosticCard key={index} failure={toFailureView(error)} /> : null,
      )}
    </>
  );
}
function UndoReview(props: {
  identifier: string | undefined;
  allowed: boolean;
  pending: boolean;
  onConfirm: (identifier: string) => void;
}): ReactElement {
  if (!props.identifier) return <></>;
  return (
    <FieldReview
      key={props.identifier}
      operation="revert_change"
      jobId={props.identifier}
      allowed={props.allowed}
      pending={props.pending}
      onConfirm={props.onConfirm}
    />
  );
}
