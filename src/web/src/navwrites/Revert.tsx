// M1-09 撤回入口与路由：统一按 nav_write_apply 识别实际写作业，不按操作中文名猜测。
import type { ReactElement } from "react";
import { getRouteApi, useNavigate } from "@tanstack/react-router";
import { Alert, Button, Typography } from "antd";
import { useAccountClient, useCurrentAccount } from "../accounts/runtime";
import { previewRevert } from "../api/navigationWrites";
import { useJobAction } from "../jobs/_actions";
import { NavigationConfirmation } from "./Confirmation";
import { NavigationDifferences, PreviewStatus, useNavigationPreview } from "./Preview";
import type { Job } from "../api/jobs";
import { useJob } from "../jobs/queries";
import { isJobTerminal } from "../jobs/progress";
import { useRecoveryBlock } from "../navigation/queries";
import { recoveryReason } from "./recoveryGate";
import { DiagnosticCard } from "../DiagnosticCard";
import { toFailureView } from "../api/problems";
import "./writes.css";

function terminalReason(job: Job): string | null {
  return isJobTerminal(job) ? null : "作业尚未结束，暂不能撤回";
}

/** 作业入口参数。 */
interface RevertEntryProps {
  /** 当前持久作业；所有建链、来源、编辑、改指向及撤回均使用同一个写入类型。 */ job: Job;
}
/**
 * 为每个实际写导航层作业提供撤回流程入口。
 * @param props - 已读取的作业记录。
 * @returns antd 按钮；非写作业不显示，恢复阻挡或未到终态时禁用并说明原因。
 * @throws 无。
 * @sideEffects 点击仅导航撤回页，不自动提交预览或写入。
 * @timeSemantics 恢复状态共用每秒查询；作业终态不证明有 COMMITTED 记录，最终由 worker 核对。
 */
export function RevertEntry(props: RevertEntryProps): ReactElement | null {
  const navigate = useNavigate();
  const recovery = useRecoveryBlock();
  if (props.job.type_name !== "nav_write_apply") return null;
  const reason = recoveryReason(recovery, "撤回") ?? terminalReason(props.job);
  return (
    <div className="navigation-write">
      {reason && <Alert aria-label="撤回限制" type="warning" title={reason} />}
      <Button
        aria-label="撤回导航写入"
        disabled={!!reason}
        onClick={() => {
          if (!reason)
            void navigate({ to: "/jobs/$jobId/revert", params: { jobId: props.job.job_id } });
        }}
      >
        撤回
      </Button>
    </div>
  );
}

/**
 * 打开指定写导航层作业的撤回页面。
 * @returns 目标作业编号及只读预览入口；不会因打开链接自动写入。
 * @throws 无；目标读取失败显示统一诊断。
 * @sideEffects 经 useJob 读取真实目标作业，写入只由后续明确确认触发。
 * @timeSemantics 复用作业轮询至终态及恢复状态每秒核对。
 */
export function RevertPage(): ReactElement {
  const { jobId } = getRouteApi("/jobs/$jobId/revert").useParams();
  const job = useJob(jobId);
  const account = useCurrentAccount();
  return (
    <section className="navigation-write">
      <Typography.Title level={2}>撤回作业 #{jobId}</Typography.Title>
      {job.error && <DiagnosticCard failure={toFailureView(job.error)} />}
      {job.data?.type_name === "nav_write_apply" && (
        <RevertForm key={JSON.stringify([account.data?.account_id, jobId])} job={job.data} />
      )}
      {job.data && job.data.type_name !== "nav_write_apply" && (
        <Alert type="error" title="该作业不是写导航层作业" />
      )}
    </section>
  );
}

function useRevertPreview(job: Job) {
  const client = useAccountClient();
  const submit = useJobAction<string>(
    (payload, signal) => previewRevert({ client, payload, signal }),
    false,
  );
  const query = useNavigationPreview(submit.data?.job_id);
  const preview = query.report.data;
  const matching =
    preview?.operation === "revert_change" &&
    preview.reverts_job_id === job.job_id &&
    preview.preview_job_id === submit.data?.job_id;
  const failed =
    query.job.data?.state === "completed" && query.job.data.summary?.outcome === "failed";
  return { submit, query, preview, matching, retry: failed || query.report.isError };
}
function RevertResults(props: {
  flow: ReturnType<typeof useRevertPreview>;
  allowed: boolean;
}): ReactElement {
  const { submit, query, preview, matching } = props.flow;
  return (
    <>
      {submit.error && <DiagnosticCard failure={toFailureView(submit.error)} />}
      <PreviewStatus {...query} />
      {preview && matching && (
        <>
          <NavigationDifferences preview={preview} />
          <NavigationConfirmation
            key={preview.preview_job_id}
            preview={preview}
            blocked={!props.allowed || submit.isPending}
          />
        </>
      )}
      {preview && !matching && <Alert type="error" title="预览与撤回目标不一致，请重新预览" />}
    </>
  );
}
function RevertForm({ job }: RevertEntryProps): ReactElement {
  const recovery = useRecoveryBlock();
  const reason = recoveryReason(recovery, "撤回") ?? terminalReason(job);
  const allowed = reason === null;
  const flow = useRevertPreview(job);
  const { submit } = flow;
  return (
    <>
      <p>撤回会核对永久变更记录；当前内容不等于原作业后像时，一行都不写。</p>
      {reason && <Alert aria-label="撤回限制" type="warning" title={reason} />}
      <Button
        aria-label={flow.retry ? "重新预览撤回" : "预览撤回"}
        disabled={!allowed || submit.isPending}
        loading={submit.isPending}
        onClick={() => {
          if (allowed) {
            submit.reset();
            submit.mutate(job.job_id);
          }
        }}
      >
        预览撤回
      </Button>
      <RevertResults flow={flow} allowed={allowed} />
    </>
  );
}
