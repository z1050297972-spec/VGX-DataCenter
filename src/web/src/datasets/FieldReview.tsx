// M1.5-02 保存预览的审阅界面；复用作业轮询和报告，不在浏览器重算差异。
import type { ReactElement } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button, Typography } from "antd";
import { useAccountClient, useCurrentAccount } from "../accounts/runtime";
import { navigationJobSucceeded } from "./fieldEditingPolicy";
import { getNavigationPreview, type NavigationPreview } from "../api/dataOrigin";
import { JOB_GC_TIME_MS, JOB_STALE_TIME_MS } from "../api/jobs";
import { useJob } from "../jobs/queries";
import { DiagnosticCard, JobDiagnosticCard } from "../DiagnosticCard";
import { toFailureView } from "../api/problems";
import { formatDateTime } from "../time";
import { jobStatusLabel } from "../jobs/progress";

interface Props {
  /** 预览作业编号，十进制文本。 */ jobId: string;
  /** 恢复状态允许写且提交未失败时为true。 */ allowed: boolean;
  /** 确认在途状态，阻止双击。 */ pending: boolean;
  /** 仅提交用户已审阅的同一预览编号。 */ onConfirm: (identifier: string) => void;
}
/**
 * 显示预览作业状态和逐字段新旧值，再提供明确确认入口。
 * @param props - 预览编号、写入门禁、提交状态及确认回调。
 * @returns 有界可换行差异、检查范围、提示和确认按钮。
 * @throws 无；请求失败和作业诊断就地展示。
 * @sideEffects 预览作业完成前每秒轮询；成功后GET一次保存报告，按钮调用onConfirm。
 * @timeSemantics 报告保留预览UTC时刻，显示时使用浏览器时区；不重算计划。
 */
export function FieldReview(props: Props): ReactElement {
  const client = useAccountClient();
  const account = useCurrentAccount();
  const job = useJob(props.jobId);
  const report = useQuery({
    queryKey: ["navigation", account.data?.account_id, "preview", props.jobId],
    queryFn: ({ signal }) => getNavigationPreview({ client, payload: props.jobId, signal }),
    enabled: navigationJobSucceeded(job.data),
    retry: false,
    staleTime: JOB_STALE_TIME_MS,
    gcTime: JOB_GC_TIME_MS,
    refetchOnWindowFocus: false,
  });
  const preview = report.data;
  return (
    <>
      {job.data && (
        <>
          <p role="status">{jobStatusLabel(job.data)}</p>
          <JobDiagnosticCard job={job.data} />
        </>
      )}
      {job.error && <DiagnosticCard failure={toFailureView(job.error)} />}
      {report.error && <DiagnosticCard failure={toFailureView(report.error)} />}
      <ReportContent preview={preview} options={props} />
    </>
  );
}

function ReportContent({
  preview,
  options,
}: {
  preview: NavigationPreview | undefined;
  options: Props;
}): ReactElement {
  if (!preview || preview.operation !== "edit_dataset_fields") return <></>;
  const removingClassification =
    preview.parameters.kind === "scene" || preview.parameters.kind === "tasks";
  return (
    <>
      <p>
        预览时间：
        <time dateTime={preview.created_at}>{formatDateTime(preview.created_at)}</time>
      </p>
      <p>
        修改 {preview.report.file_count} 个文件 · 差异 {preview.report.listed_total} 项
      </p>
      <Typography.Paragraph>涉及的数据集：{preview.dataset_ids.join("、")}</Typography.Paragraph>
      <section aria-label="字段预览差异" className="field-differences">
        {preview.report.listed_changes.map((change, index) => (
          <article key={index}>
            <p>
              {change.file} · {change.json_path}
            </p>
            <dl>
              <dt>修改前</dt>
              <dd>{change.before}</dd>
              <dt>修改后</dt>
              <dd>{change.after}</dd>
            </dl>
            {removingClassification &&
              (change.json_path === "scene" || change.json_path === "tasks") &&
              change.after === "[]" && (
                <Typography.Paragraph>删除后变成未标注</Typography.Paragraph>
              )}
          </article>
        ))}
      </section>
      {preview.report.checks.map((check) => (
        <p key={check.name}>
          {check.name}（
          {check.scope === "full" ? "全量" : check.scope === "sampled" ? "抽样" : "执行后"}）：
          {check.detail}
        </p>
      ))}
      {preview.report.notices.map((notice, i) => (
        <p key={i}>{notice.message}</p>
      ))}
      {preview.report.listed_total > preview.report.listed_changes.length && (
        <p>差异仅展示前 {preview.report.listed_changes.length} 项，总数如上。</p>
      )}
      <Button
        type="primary"
        aria-label="确认字段写入"
        loading={options.pending}
        disabled={!options.allowed || options.pending || preview.report.file_count === 0}
        onClick={() => {
          options.onConfirm(preview.preview_job_id);
        }}
      >
        确认写入
      </Button>
    </>
  );
}
