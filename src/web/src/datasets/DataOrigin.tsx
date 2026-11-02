import "./dataOrigin.css";
// M1-10 来源标注部件：展示当前来源和标注印记，预览及写入仍由 worker 的统一流水线执行。
import { useState, type ReactElement } from "react";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Flex, Select, Typography } from "antd";
import { useAccountClient, useCurrentAccount } from "../accounts/runtime";
import {
  previewDataOrigin,
  getNavigationPreview,
  applyNavigationPreview,
  type DataOriginInput,
  type NavigationPreview,
} from "../api/dataOrigin";
import type { DatasetDetail } from "../api/datasets";
import { JOB_GC_TIME_MS, JOB_STALE_TIME_MS, type Job } from "../api/jobs";
import { useJob } from "../jobs/queries";
import { useJobAction } from "../jobs/_actions";
import { jobStatusLabel } from "../jobs/progress";
import { useRecoveryBlock } from "../navigation/queries";
import { DiagnosticCard, JobDiagnosticCard } from "../DiagnosticCard";
import { toFailureView } from "../api/problems";
import { formatDateTime } from "../time";

/** 来源值沿用生成类型；数组仅定义表单展示顺序，不翻译成另一套提交编码。 */
const ORIGINS: DataOriginInput["data_origin"][] = [
  "真机采集",
  "UMI 采集",
  "ego 采集",
  "仿真生成",
  "开源下载",
  "未知",
];

interface DataOriginProps {
  /** 已索引数据集的永久编号；不从入口目录名推测。 */ datasetId: string;
  /** 详情接口读取的规范入口来源与印记；null 或缺失表示当前不可用。 */ provenance: DatasetDetail["provenance"];
}
/**
 * 在任一视图的详情页标注同一数据集的数据来源。
 * @param props - 永久数据集编号。
 * @returns 当前来源与标注印记、默认选择及相同值提示、恢复阻挡提示和预览；身份或来源刷新时清除旧流程。
 * @throws 无；请求故障统一用 DiagnosticCard 呈现。
 * @sideEffects 复用恢复标记查询，预览与确认各 POST 一次，确认成功进入作业页；不直接访问文件。
 * @timeSemantics 恢复标记与预览作业沿用每秒轮询；请求不重试、离页取消。
 */
export function DataOriginEditor(props: DataOriginProps): ReactElement {
  const account = useCurrentAccount();
  return (
    <OriginForm
      key={JSON.stringify([account.data?.account_id, props.datasetId, props.provenance])}
      datasetId={props.datasetId}
      provenance={props.provenance}
    />
  );
}

function OriginForm({ datasetId, provenance }: DataOriginProps): ReactElement {
  const client = useAccountClient();
  const preview = useJobAction<DataOriginInput>(
    (payload, signal) => previewDataOrigin({ client, payload, signal }),
    false,
  );
  const confirm = useJobAction<string>(
    (payload, signal) => applyNavigationPreview({ client, payload, signal }),
    true,
  );
  const busy = preview.isPending || confirm.isPending;
  const currentOrigin = provenance?.data_origin ?? "未知";
  const [origin, setOrigin] = useState<DataOriginInput["data_origin"]>(currentOrigin);
  const sameOrigin = origin === currentOrigin;
  const block = useRecoveryBlock();
  const allowed = !block.isError && block.data?.blocked === false;
  return (
    <section aria-label="数据来源标注" className="origin-section">
      <Typography.Title level={4}>数据来源</Typography.Title>
      <CurrentOrigin provenance={provenance} />
      <RecoveryStatus block={block} />
      <Flex gap="small" align="center" wrap>
        <Select<DataOriginInput["data_origin"]>
          // 下拉框随抽屉一起定位和裁剪，避免入场期间挂在 body 上的浮层撑宽整页。
          getPopupContainer={(trigger: HTMLElement): HTMLElement =>
            trigger.parentElement ?? trigger
          }
          virtual={false}
          aria-label="选择数据来源"
          placeholder="选择数据来源"
          value={origin}
          disabled={busy}
          onChange={(value) => {
            setOrigin(value);
            preview.reset();
            confirm.reset();
          }}
          options={ORIGINS.map((value) => ({ value, label: value }))}
          className="origin-select"
        />
        <Button
          aria-label="预览数据来源"
          loading={preview.isPending}
          disabled={!allowed || sameOrigin || busy}
          onClick={() => {
            if (allowed && !sameOrigin) {
              confirm.reset();
              preview.mutate({ dataset_id: datasetId, data_origin: origin });
            }
          }}
        >
          预览改动
        </Button>
      </Flex>
      {sameOrigin && (
        <p role="status" aria-label="数据来源相同值提示">
          和当前一样
        </p>
      )}
      <RequestFailure error={preview.error} />
      <RequestFailure error={confirm.error} />
      {preview.data && (
        <OriginPreview
          key={preview.data.job_id}
          jobId={preview.data.job_id}
          allowed={allowed}
          confirming={confirm.isPending}
          confirmationFailed={confirm.isError}
          onConfirm={(identifier) => {
            if (allowed && !confirm.isError) confirm.mutate(identifier);
          }}
        />
      )}
    </section>
  );
}

function OriginPreview({
  jobId,
  allowed,
  confirming,
  confirmationFailed,
  onConfirm,
}: {
  jobId: string;
  allowed: boolean;
  confirming: boolean;
  confirmationFailed: boolean;
  onConfirm: (identifier: string) => void;
}): ReactElement {
  const client = useAccountClient();
  const account = useCurrentAccount();
  const job = useJob(jobId);
  const succeeded = previewSucceeded(job.data);
  const report = useQuery({
    queryKey: ["navigation", account.data?.account_id, "preview", jobId],
    queryFn: ({ signal }) => getNavigationPreview({ client, payload: jobId, signal }),
    enabled: succeeded,
    retry: false,
    staleTime: JOB_STALE_TIME_MS,
    gcTime: JOB_GC_TIME_MS,
    refetchOnWindowFocus: false,
  });
  return (
    <>
      {job.data && (
        <p role="status" aria-label="数据来源预览作业状态">
          {jobStatusLabel(job.data)}
        </p>
      )}
      {job.data && <JobDiagnosticCard job={job.data} />}
      <RequestFailure error={job.error} />
      <RequestFailure error={report.error} />
      {report.data && (
        <>
          <OriginDifferences preview={report.data} />
          <Button
            aria-label="确认修改数据来源"
            type="primary"
            loading={confirming}
            disabled={!allowed || confirming || confirmationFailed}
            onClick={() => {
              onConfirm(report.data.preview_job_id);
            }}
          >
            确认修改
          </Button>
        </>
      )}
    </>
  );
}

function OriginDifferences({ preview }: { preview: NavigationPreview }): ReactElement {
  return (
    <>
      <p>
        预览时间：<time dateTime={preview.created_at}>{formatDateTime(preview.created_at)}</time>
      </p>
      <div role="region" aria-label="数据来源预览差异" tabIndex={0} className="origin-scroll">
        <table className="origin-table">
          <thead>
            <tr>
              <th>改动文件</th>
              <th>修改前</th>
              <th>修改后</th>
            </tr>
          </thead>
          <tbody>
            {preview.report.listed_changes.map((change, index) => (
              <tr key={index}>
                <td>{change.file}</td>
                <td>{change.before}</td>
                <td>{change.after}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

// 把共享标记的未知、失败和已阻挡状态明确区分；未知不能被当作允许提交。
function recoveryReason(block: ReturnType<typeof useRecoveryBlock>): string | null {
  if (block.isError) return "无法核对导航层恢复状态，暂不能提交。";
  if (block.data?.blocked) return "导航层恢复失败，写操作被挡住；请管理员处理后再提交。";
  if (block.data?.blocked !== false) return "正在核对导航层恢复状态，暂不能提交。";
  return null;
}
function RecoveryStatus({ block }: { block: ReturnType<typeof useRecoveryBlock> }): ReactElement {
  const reason = recoveryReason(block);
  return (
    <>
      {reason && <Alert aria-label="数据来源写入限制" type="warning" title={reason} />}
      <RequestFailure error={block.error} />
    </>
  );
}
function RequestFailure({ error }: { error: Error | null }): ReactElement {
  return error ? <DiagnosticCard failure={toFailureView(error)} /> : <></>;
}
// completed 也可能是失败或部分成功；只有服务端确认预览成功后才能读取报告并确认。
function previewSucceeded(job: Job | undefined): boolean {
  return (
    job?.state === "completed" &&
    (job.summary?.outcome === "succeeded" || job.summary?.outcome === "succeeded_with_warnings")
  );
}

// 当前值来自规范入口的本次读取；坏文件不能冒充“从未标注”。
function CurrentOrigin({ provenance }: { provenance: DatasetDetail["provenance"] }): ReactElement {
  if (!provenance) return <p aria-label="当前数据来源">当前：未知（来源信息不可用）</p>;
  if (provenance.state === "absent")
    return <p aria-label="当前数据来源">当前：未知（还没有 来源.json）</p>;
  if (provenance.state === "invalid")
    return <p aria-label="当前数据来源">当前：未知（来源.json 无法读取）</p>;
  const stamp = provenance.data_origin_set_by;
  return (
    <>
      <p aria-label="当前数据来源">当前：{provenance.data_origin}</p>
      {stamp && (
        <p aria-label="数据来源标注信息">
          标注人：{stamp.account_name ?? "未知"}；标注时间：
          <time dateTime={stamp.at}>{formatDateTime(stamp.at)}</time>
        </p>
      )}
    </>
  );
}
