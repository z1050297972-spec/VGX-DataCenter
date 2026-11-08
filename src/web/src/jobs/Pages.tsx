import "./jobs.css";
// 作业页面契约（08）：Ant Design 与统一 DiagnosticCard；不直接 fetch、不计算后端结果。
import { DownloadDetail } from "./DownloadDetail";
import { IngestDownload } from "../downloads/Ingest";
import { useState, type ReactElement } from "react";
import {
  Alert,
  Breadcrumb,
  Button,
  Card,
  Col,
  Flex,
  Row,
  Select,
  Table,
  Tag,
  Typography,
  Progress,
} from "antd";
import { getRouteApi, Link } from "@tanstack/react-router";
import type { Job, JobSearch } from "../api/jobs";
import { toFailureView } from "../api/problems";
import { DiagnosticCard, JobDiagnosticCard } from "../DiagnosticCard";
import { useJobs, useJob, useJobLog, useCancelJob, useResubmitJob } from "./queries";
import type { JobTiming } from "./progress";
import { jobStatusLabel, useJobTiming, isJobTerminal } from "./progress";

const jobsRoute = getRouteApi("/jobs");

/**
 * 显示所有提交人的作业列表及可分享状态筛选。
 * @returns 列表、状态筛选和游标翻页，保留已有示例作业的历史记录；九种显示状态遵守 jobStatusLabel，另列等待 GPU/等待导航层写锁，不增加作业状态。
 * @throws 无；无效筛选显示“作业筛选参数不合法”，请求错误由 DiagnosticCard 显示。
 * @sideEffects 经真实 /jobs Router 的 useSearch/useNavigate 读取和更新 typed search；筛选改变清 cursor，无效值不发列表请求。
 * @timeSemantics 合法列表每 JOB_POLL_INTERVAL_MS 轮询，离页取消，无自动重试；UTC 时刻仅显示时转浏览器本地。
 */
export function JobsPage(): ReactElement {
  const search = jobsRoute.useSearch();
  return (
    <section className="jobs-page">
      <header className="jobs-header">
        <Breadcrumb items={[{ title: "作业" }, { title: "列表" }]} />
        <Flex className="jobs-header-row" align="center" justify="space-between" wrap gap="middle">
          <Typography.Title level={2} className="jobs-title">
            作业列表
          </Typography.Title>
        </Flex>
      </header>
      <Card>
        <div className="jobs-list-content">
          <JobFilters key={JSON.stringify(search)} search={search} />
          {search.invalidJobSearch ? (
            <Alert type="error" title="作业筛选参数不合法" />
          ) : (
            <JobListContent search={search} />
          )}
        </div>
      </Card>
    </section>
  );
}

/**
 * 显示一个作业的状态、进度、摘要、诊断和控制按钮。
 * @returns /jobs/$jobId 的详情；增加等待原因及领到的 GPU 卡号（终态保留历史），未领卡明确显示未分配；仅账号编号为 null 时按系统身份显示；有编号的同名账号保持账号删除标记；展示“阶段 2/4 · 名称”、已知总数进度条（百分比四舍五入为整数）或未知总数已处理量、独立计数、已用时间、速度/剩余、日志最后几十行和 DiagnosticCard；取消/中断无结果仍保留进度。
 * @throws 无；服务端404、409 与其他错误用统一诊断；非法编号由路由显示404，不在页面拼接服务器失败信息。
 * @sideEffects 调 useJob/useJobLog；queued/running 可取消，cancelling 禁用取消，终态可重提；任意账号均可操作；显示重新提交自链接和历史名字删除标记，不输出工具 HTML。
 * @timeSemantics 进行中每秒轮询，终态取最后日志后停止；速度最近 10 秒、样本不足不显示，未知总数不显示百分比/剩余；已用时以服务器 elapsed_s 加本地单调增量，终态使用冻结摘要。
 */
export function JobDetailPage(): ReactElement {
  const { jobId } = getRouteApi("/jobs/$jobId").useParams();
  const query = useJob(jobId);
  const timing = useJobTiming(query.data);
  if (query.isError) return <DiagnosticCard failure={toFailureView(query.error)} />;
  if (!query.data) return <Typography.Text>正在读取作业…</Typography.Text>;
  const job = query.data;
  return (
    <section className="jobs-page">
      <header className="jobs-header">
        <Breadcrumb items={[{ title: "作业" }, { title: "详情" }]} />
        <Flex align="center" wrap gap="small">
          <Typography.Title level={2} className="jobs-title">
            {job.display_name} #{job.job_id}
          </Typography.Title>
          <Tag>{jobStatusLabel(job)}</Tag>
        </Flex>
      </header>
      <Card title="概要">
        {job.wait_reason && <div>{waitLabel(job)}</div>}
        <div className="jobs-summary">
          <Row gutter={[16, 8]}>
            <Col xs={24} sm={8}>
              <div>提交人：{submitterLabel(job)}</div>
            </Col>
            <Col xs={24} sm={8}>
              <div>GPU：{job.gpu_index ?? "未分配"}</div>
            </Col>
            {job.progress && (
              <Col xs={24} sm={8}>
                <div>
                  阶段 {job.progress.stage_index}/{job.progress.stage_count} ·{" "}
                  {job.progress.stage_name}
                </div>
              </Col>
            )}
          </Row>
          <JobProgressView job={job} timing={timing} />
        </div>
        {job.resubmitted_from && (
          <Link to="/jobs/$jobId" params={{ jobId: job.resubmitted_from }}>
            重新提交自 #{job.resubmitted_from}
          </Link>
        )}
        <JobActions key={job.job_id} job={job} />
      </Card>
      {job.type_name === "download" && (
        <>
          <DownloadDetail job={job} />
          <IngestDownload job={job} />
        </>
      )}
      <Card title="作业日志">
        <JobLogPanel job={job} />
      </Card>
      <Card title="诊断" className="jobs-diagnostics">
        <JobDiagnosticCard job={job} />
      </Card>
    </section>
  );
}

// 保持已有组件导出路径；应用外壳直接引用独立模块，以便作业页按路由拆包。
export { WorkerStatusBanner } from "./WorkerStatusBanner";

function JobFilters({ search }: { search: JobSearch }): ReactElement {
  const [state, setState] = useState<JobSearch["state"]>(search.state);
  const navigate = jobsRoute.useNavigate();
  return (
    <Flex gap="small" wrap>
      <Select
        aria-label="作业状态"
        value={state}
        allowClear
        className="jobs-filter"
        onChange={setState}
        options={[
          { value: "queued", label: "排队中" },
          { value: "running", label: "运行中" },
          { value: "cancelling", label: "正在取消" },
          { value: "completed", label: "已完成" },
          { value: "cancelled", label: "已取消" },
          { value: "interrupted", label: "已中断" },
        ]}
      />
      <Button
        onClick={() => {
          void navigate({ search: { state, limit: search.limit } });
        }}
      >
        筛选
      </Button>
    </Flex>
  );
}
function JobListContent({ search }: { search: JobSearch }): ReactElement {
  const query = useJobs(search);
  const navigate = jobsRoute.useNavigate();
  if (query.isError) return <DiagnosticCard failure={toFailureView(query.error)} />;
  return (
    <>
      <Table<Job>
        scroll={{ x: "max-content" }}
        rowKey="job_id"
        pagination={false}
        loading={query.isPending}
        dataSource={query.data?.items}
        columns={[
          {
            title: "编号",
            dataIndex: "job_id",
            render: (_value: unknown, job) => (
              <Link to="/jobs/$jobId" params={{ jobId: job.job_id }}>
                #{job.job_id}
              </Link>
            ),
          },
          { title: "类型", dataIndex: "display_name" },
          { title: "状态", render: (_value: unknown, job) => jobStatusLabel(job) },
          { title: "等待原因", render: (_value: unknown, job) => waitLabel(job) },
          {
            title: "提交人",
            render: (_value: unknown, job) => submitterLabel(job),
          },
        ]}
      />
      {query.data?.next_cursor && (
        <Button
          onClick={() => {
            void navigate({ search: { ...search, cursor: query.data.next_cursor ?? undefined } });
          }}
        >
          下一页
        </Button>
      )}
    </>
  );
}

function JobLogPanel({ job }: { job: Job }): ReactElement {
  const query = useJobLog(job);
  if (query.isError) return <DiagnosticCard failure={toFailureView(query.error)} />;
  if (!query.data) return <Typography.Text>正在读取日志…</Typography.Text>;
  const tail = query.data.tail;
  if (tail.status === "cleared") return <Typography.Text>作业日志已清除</Typography.Text>;
  if (tail.status === "not_started") return <Typography.Text>作业未开始</Typography.Text>;
  return (
    <section>
      {tail.truncated && <Typography.Text>仅显示日志末尾</Typography.Text>}
      <pre role="log" aria-label="作业日志" className="jobs-log">
        {tail.lines.join("\n")}
      </pre>
    </section>
  );
}

function JobActions({ job }: { job: Job }): ReactElement {
  const cancel = useCancelJob(job.job_id);
  const resubmit = useResubmitJob(job.job_id);
  return (
    <div>
      {isJobTerminal(job) ? (
        <Button
          aria-label="重新提交"
          loading={resubmit.isPending}
          disabled={resubmit.isPending}
          onClick={() => {
            resubmit.mutate();
          }}
        >
          重新提交
        </Button>
      ) : (
        <Button
          aria-label="取消作业"
          loading={cancel.isPending}
          disabled={cancel.isPending || job.state === "cancelling"}
          onClick={() => {
            cancel.mutate();
          }}
        >
          取消作业
        </Button>
      )}
      {cancel.isError && <DiagnosticCard failure={toFailureView(cancel.error)} />}
      {resubmit.isError && <DiagnosticCard failure={toFailureView(resubmit.error)} />}
    </div>
  );
}

function JobProgressView({ job, timing }: { job: Job; timing: JobTiming }): ReactElement {
  const progress = job.progress;
  return (
    <div className="jobs-summary">
      {progress &&
        (progress.total === null ? (
          <div>
            已处理 {progress.done} {progress.unit}
          </div>
        ) : (
          <Progress
            aria-label="作业进度"
            percent={progress.total === 0 ? 0 : Math.round((100 * progress.done) / progress.total)}
          />
        ))}
      {progress?.parts.map((part) => (
        <ProgressPartView key={part.name} part={part} />
      ))}
      <Flex gap="large" wrap>
        {progress && (
          <div>
            条目 {progress.total_items} · 失败 {progress.failed_items} · 警告{" "}
            {progress.warning_count}
          </div>
        )}
        {timing.elapsedSeconds !== null && (
          <div>已用时间 {timing.elapsedSeconds.toFixed(1)} 秒</div>
        )}
        {timing.unitsPerSecond !== null && (
          <div>
            速度 {timing.unitsPerSecond.toFixed(1)} {progress?.unit}/秒
          </div>
        )}
        {timing.remainingSeconds !== null && (
          <div>剩余时间 {timing.remainingSeconds.toFixed(1)} 秒</div>
        )}
      </Flex>
    </div>
  );
}

// 分项使用接口生成类型；未知总数保留计数文字，不推算百分比。
function ProgressPartView({
  part,
}: {
  part: NonNullable<Job["progress"]>["parts"][number];
}): ReactElement {
  return (
    <div>
      <Flex justify="space-between" gap="small" wrap>
        <Typography.Text>{part.name}</Typography.Text>
        <Typography.Text>
          {part.done}/{part.total ?? "未知"} {part.unit}
        </Typography.Text>
      </Flex>
      <Progress
        aria-label={`${part.name}进度`}
        percent={part.total ? Math.round((100 * part.done) / part.total) : 0}
        showInfo={part.total !== null}
      />
    </div>
  );
}

// 等待是资源展示原因，独立于后端作业状态与结局。
function waitLabel(job: Job): string {
  return job.wait_reason === "gpu"
    ? "等待 GPU"
    : job.wait_reason === "navigation_lock"
      ? "等待导航层写锁"
      : "";
}

// 固定系统身份由空编号判断；同名账号仍显示账号身份及删除标记。
function submitterLabel(job: Job): string {
  const actor = job.submitted_by;
  if (actor.account_id === null) return "系统";
  return (
    actor.name +
    (actor.name === "系统" ? `（账号 #${actor.account_id}）` : "") +
    (actor.deleted ? "（已删除）" : "")
  );
}
