// M1-09 预览展示：只投影保存的报告，不计算替换规则；宽内容在本地容器滚动。
import type { ReactElement } from "react";
import { useQuery } from "@tanstack/react-query";
import { Alert, Table, Typography } from "antd";
import { useAccountClient, useCurrentAccount } from "../accounts/runtime";
import { getJob, JOB_GC_TIME_MS, JOB_POLL_INTERVAL_MS, JOB_STALE_TIME_MS } from "../api/jobs";
import { getNavigationPreview, type NavigationPreview } from "../api/dataOrigin";
import { isJobTerminal, jobStatusLabel } from "../jobs/progress";
import { DiagnosticCard, JobDiagnosticCard } from "../DiagnosticCard";
import { toFailureView } from "../api/problems";
import { formatDateTime } from "../time";
import "./writes.css";

/**
 * 查询 worker 预览作业及其成功报告。
 * @param previewId - 预览作业文本编号，undefined 时不发请求。
 * @returns 作业和报告两个独立查询，失败不伪装成空预览。
 * @throws Error 缺少账号或 Query Provider。
 * @sideEffects 通过统一客户端读取作业与已保存预览；不写导航。
 * @timeSemantics 作业每秒轮询至终态，报告成功后读取一次；离页取消、缓存立即释放、无重试。
 */
export function useNavigationPreview(previewId: string | undefined) {
  const client = useAccountClient();
  const account = useCurrentAccount();
  const options = {
    retry: false,
    staleTime: JOB_STALE_TIME_MS,
    gcTime: JOB_GC_TIME_MS,
    refetchOnWindowFocus: false,
  } as const;
  const job = useQuery({
    ...options,
    queryKey: ["navigation-write", account.data?.account_id, "job", previewId],
    queryFn: ({ signal }) => getJob({ client, payload: undefined, jobId: previewId ?? "", signal }),
    enabled: !!previewId,
    refetchInterval: (query) =>
      query.state.data && isJobTerminal(query.state.data) ? false : JOB_POLL_INTERVAL_MS,
  });
  const successful =
    job.data?.state === "completed" &&
    (job.data.summary?.outcome === "succeeded" ||
      job.data.summary?.outcome === "succeeded_with_warnings");
  const report = useQuery({
    ...options,
    queryKey: ["navigation-write", account.data?.account_id, "report", previewId],
    queryFn: ({ signal }) => getNavigationPreview({ client, payload: previewId ?? "", signal }),
    enabled: !!previewId && successful,
  });
  return { job, report };
}

/**
 * 展示 worker 预览状态和失败诊断。
 * @param props - 同一个预览编号对应的查询结果。
 * @returns 当前状态、异步冲突或读取失败，不出现确认按钮。
 * @throws 无。
 * @sideEffects 无；请求由调用者的 hook 管理。
 * @timeSemantics 状态来自最近一次作业快照。
 */
export function PreviewStatus(props: ReturnType<typeof useNavigationPreview>): ReactElement {
  return (
    <>
      {props.job.data && <p role="status">预览作业：{jobStatusLabel(props.job.data)}</p>}
      {props.job.data && <JobDiagnosticCard job={props.job.data} />}
      {props.job.error && <DiagnosticCard failure={toFailureView(props.job.error)} />}
      {props.report.error && <DiagnosticCard failure={toFailureView(props.report.error)} />}
    </>
  );
}

/** 预览投影参数，不能携带客户端生成的计划。 */
interface DifferencesProps {
  /** worker 已成功保存的同一份报告。 */ preview: NavigationPreview;
}
/**
 * 展示分字段计数、全部正文替换及原本缺失的路径。
 * @param props - 服务端生成的完整报告。
 * @returns 有分页的差异表与独立缺失提示，不使用 HTML 注入。
 * @throws 无。
 * @sideEffects 只改变表格当前页，不提交请求。
 * @timeSemantics 预览时刻统一用 formatDateTime 显示本地时间。
 */
export function NavigationDifferences(props: DifferencesProps): ReactElement {
  const preview = props.preview;
  const counts = preview.report.field_counts;
  const changes = preview.report.repoint_changes ?? preview.report.listed_changes;
  const missing = preview.report.notices.filter((notice) => notice.code === "old_path_missing");
  return (
    <section className="navigation-write" aria-label="导航写入预览差异">
      <Typography.Title level={4}>预览差异</Typography.Title>
      <p>
        预览时间：<time dateTime={preview.created_at}>{formatDateTime(preview.created_at)}</time>
      </p>
      <p>
        文件 {preview.report.file_count} 个；链接 {preview.report.link_count} 条
      </p>
      <Table
        size="small"
        rowKey={(row) => `${row.file}:${row.field}`}
        scroll={{ x: 640 }}
        dataSource={counts}
        pagination={{ pageSize: 20 }}
        columns={[
          { title: "文件", dataIndex: "file" },
          { title: "字段", dataIndex: "field" },
          { title: "替换数量", dataIndex: "count" },
        ]}
      />
      <Table
        size="small"
        rowKey="key"
        scroll={{ x: 800 }}
        dataSource={changes.map((row, index) => ({ ...row, key: String(index) }))}
        pagination={{ pageSize: 20 }}
        columns={[
          { title: "文件", dataIndex: "file" },
          { title: "位置", dataIndex: "json_path" },
          { title: "修改前", dataIndex: "before" },
          { title: "修改后", dataIndex: "after" },
        ]}
      />
      {preview.changes.length > 0 && (
        <Table
          size="small"
          rowKey="key"
          scroll={{ x: 800 }}
          dataSource={preview.changes.map((row, index) => ({ ...row, key: String(index) }))}
          pagination={{ pageSize: 20 }}
          columns={[
            { title: "步骤路径", dataIndex: "file" },
            { title: "操作", dataIndex: "json_path" },
            { title: "前像", dataIndex: "before" },
            { title: "后像", dataIndex: "after" },
          ]}
        />
      )}
      {missing.length > 0 && (
        <section aria-label="旧位置原本不存在">
          <Alert type="warning" title="旧位置原本就不存在，仍将替换" />
          {missing.map((notice, index) => (
            <div className="navigation-write-scroll" key={index}>
              {notice.objects.map(([key, value]) => (
                <p key={key}>
                  {key}：{value}
                </p>
              ))}
            </div>
          ))}
        </section>
      )}
      {preview.report.notices
        .filter((notice) => notice.code !== "old_path_missing")
        .map((notice, index) => (
          <Alert key={index} type="info" title={notice.message} />
        ))}
      {preview.report.checks.map((check) => (
        <p key={check.name}>
          {check.name}：
          {check.scope === "full"
            ? "全量检查"
            : check.scope === "sampled"
              ? "抽样检查"
              : "执行后检查"}
          ；{check.detail}
        </p>
      ))}
    </section>
  );
}
