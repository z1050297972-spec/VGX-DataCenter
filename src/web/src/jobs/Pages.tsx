// 作业页面契约（08）：Ant Design 与统一 DiagnosticCard；不直接 fetch、不计算后端结果。
import { DownloadDetail } from "./DownloadDetail";
import { IngestDownload } from "../downloads/Ingest";
import { RevertEntry } from "../navwrites/Revert";
import { useState, type ReactElement } from "react";
import { Alert, Button, Select, Table, Typography, Progress, Form, Input } from "antd";
import { getRouteApi, Link } from "@tanstack/react-router";
import type { Job, JobSearch, CountInput } from "../api/jobs";
import { toFailureView } from "../api/problems";
import { DiagnosticCard, JobDiagnosticCard } from "../DiagnosticCard";
import {
  useJobs,
  useJob,
  useJobLog,
  useCancelJob,
  useResubmitJob,
  useSubmitCountJob,
} from "./queries";
import type { JobTiming } from "./progress";
import { jobStatusLabel, useJobTiming, isJobTerminal } from "./progress";

const jobsRoute = getRouteApi("/jobs");

/**
 * 显示所有提交人的作业列表及可分享状态筛选。
 * @returns 列表、状态筛选、游标翻页和两类示例提交入口；九种显示状态遵守 jobStatusLabel，另列等待 GPU/等待导航层写锁，不增加作业状态。
 * @throws 无；无效筛选显示“作业筛选参数不合法”，请求错误由 DiagnosticCard 显示。
 * @sideEffects 经真实 /jobs Router 的 useSearch/useNavigate 读取和更新 typed search；筛选改变清 cursor，无效值不发列表请求。
 * @timeSemantics 合法列表每 JOB_POLL_INTERVAL_MS 轮询，离页取消，无自动重试；UTC 时刻仅显示时转浏览器本地。
 */
export function JobsPage(): ReactElement {
  const search = jobsRoute.useSearch();
  return (
    <section>
      <Typography.Title level={2}>作业列表</Typography.Title>
      <Link to="/jobs/new">提交示例作业</Link>
      <Link to="/jobs/resources">提交资源示例</Link>
      <JobFilters key={JSON.stringify(search)} search={search} />
      {search.invalidJobSearch ? (
        <Alert type="error" title="作业筛选参数不合法" />
      ) : (
        <JobListContent search={search} />
      )}
    </section>
  );
}

/**
 * 显示一个作业的状态、进度、摘要、诊断和控制按钮。
 * @returns /jobs/$jobId 的详情；增加等待原因及领到的 GPU 卡号（终态保留历史），未领卡明确显示未分配；仅账号编号为 null 时按系统身份显示；有编号的同名账号保持账号删除标记；展示“阶段 2/4 · 名称”、已知总数进度条（百分比四舍五入为整数）或未知总数已处理量、独立计数、已用时间、速度/剩余、日志最后几十行和 DiagnosticCard；取消/中断无结果仍保留进度。
 * @throws 无；坏编号、404、409 与其他错误用统一诊断，不在页面拼接服务器失败信息。
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
    <section>
      <Typography.Title level={2}>
        {job.display_name} #{job.job_id}
      </Typography.Title>
      <Typography.Text>{jobStatusLabel(job)}</Typography.Text>
      {job.wait_reason && <div>{waitLabel(job)}</div>}
      <div>提交人：{submitterLabel(job)}</div>
      <div>GPU：{job.gpu_index ?? "未分配"}</div>
      <JobProgressView job={job} timing={timing} />
      {job.type_name === "download" && (
        <>
          <DownloadDetail job={job} />
          <IngestDownload job={job} />
        </>
      )}
      {job.resubmitted_from && (
        <Link to="/jobs/$jobId" params={{ jobId: job.resubmitted_from }}>
          重新提交自 #{job.resubmitted_from}
        </Link>
      )}
      <JobActions key={job.job_id} job={job} />
      <RevertEntry job={job} />
      <JobDiagnosticCard job={job} />
      <JobLogPanel job={job} />
    </section>
  );
}

/**
 * 用类型化表单提交示例数数作业。
 * @returns 总步数、毫秒间隔、失败步、警告步和整体中止步的 Ant Design 表单，整数范围来自生成模型契约。
 * @throws 无；字段错误保留输入，服务错误由 DiagnosticCard 展示。
 * @sideEffects 经 useSubmitCountJob POST，成功进入新详情；所有登录账号可见，不发送操作者声明、不直接读 cookie。
 * @timeSemantics 提交期间禁用重复操作，10 秒超时不宣称回滚，不自动重试；离页取消请求。
 */
export function SubmitCountJobPage(): ReactElement {
  const [form] = Form.useForm<CountFormValues>();
  const submit = useSubmitCountJob();
  return (
    <section>
      <Typography.Title level={2}>提交示例作业</Typography.Title>
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          steps: "30",
          interval_ms: "1000",
          failed_steps: "",
          warning_steps: "",
          abort_at_step: "",
        }}
        disabled={submit.isPending}
        onFinish={(values) => {
          submit.mutate(countInput(values));
        }}
      >
        <Form.Item
          name="steps"
          label="总步数"
          rules={[
            {
              validator: (_rule, value: unknown) =>
                validateField(() => countInteger(value, 1, COUNT_MAX_STEPS, COUNT_MESSAGES.steps)),
            },
          ]}
        >
          <Input inputMode="numeric" />
        </Form.Item>
        <Form.Item
          name="interval_ms"
          label="每步间隔（毫秒）"
          rules={[
            {
              validator: (_rule, value: unknown) =>
                validateField(() =>
                  countInteger(value, 0, COUNT_MAX_INTERVAL_MS, COUNT_MESSAGES.interval),
                ),
            },
          ]}
        >
          <Input inputMode="numeric" />
        </Form.Item>
        <Form.Item
          name="failed_steps"
          label="失败步"
          dependencies={["steps"]}
          rules={[
            {
              validator: (_rule, value: unknown) =>
                validateField(() => countSelection(value, form.getFieldValue("steps"))),
            },
          ]}
        >
          <Input placeholder="例如 2,4；可留空" />
        </Form.Item>
        <Form.Item
          name="warning_steps"
          label="警告步"
          dependencies={["steps"]}
          rules={[
            {
              validator: (_rule, value: unknown) =>
                validateField(() => countSelection(value, form.getFieldValue("steps"))),
            },
          ]}
        >
          <Input placeholder="例如 2,4；可留空" />
        </Form.Item>
        <Form.Item
          name="abort_at_step"
          label="整体中止步"
          dependencies={["steps"]}
          rules={[
            {
              validator: (_rule, value: unknown) =>
                validateField(() => abortStep(value, form.getFieldValue("steps"))),
            },
          ]}
        >
          <Input inputMode="numeric" placeholder="可留空" />
        </Form.Item>
        <Button
          aria-label="提交作业"
          htmlType="submit"
          type="primary"
          loading={submit.isPending}
          disabled={submit.isPending}
        >
          提交作业
        </Button>
      </Form>
      {submit.isError && <DiagnosticCard failure={toFailureView(submit.error)} />}
    </section>
  );
}

// 保持已有组件导出路径；应用外壳直接引用独立模块，以便作业页按路由拆包。
export { WorkerStatusBanner } from "./WorkerStatusBanner";

function JobFilters({ search }: { search: JobSearch }): ReactElement {
  const [state, setState] = useState<JobSearch["state"]>(search.state);
  const navigate = jobsRoute.useNavigate();
  return (
    <div>
      <Select
        aria-label="作业状态"
        value={state}
        allowClear
        style={{ width: 180 }}
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
    </div>
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
      <Typography.Title level={3}>作业日志</Typography.Title>
      {tail.truncated && <Typography.Text>仅显示日志末尾</Typography.Text>}
      <pre
        role="log"
        aria-label="作业日志"
        style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxWidth: "100%", minWidth: 0 }}
      >
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

// 与生成的CountParameters字段约束一致；服务端仍独立校验，表单只提前反馈输入错误。
const COUNT_MAX_STEPS = 10000;
const COUNT_MAX_INTERVAL_MS = 60000;
const COUNT_MESSAGES = {
  steps: `总步数须为1至${String(COUNT_MAX_STEPS)}的整数`,
  interval: `间隔须为0至${String(COUNT_MAX_INTERVAL_MS)}的整数毫秒`,
  selection: "步序号须在总步数范围内且不能重复",
  abort: "整体中止步须在总步数范围内",
};
interface CountFormValues {
  steps: string;
  interval_ms: string;
  failed_steps: string;
  warning_steps: string;
  abort_at_step: string;
}
function countInteger(value: unknown, min: number, max: number, message: string): number {
  if (typeof value !== "string" || !/^(0|[1-9][0-9]*)$/.test(value)) throw new Error(message);
  const number = Number(value);
  if (!Number.isSafeInteger(number) || number < min || number > max) throw new Error(message);
  return number;
}
function countSelection(value: unknown, steps: unknown): number[] {
  if (value === undefined || value === "") return [];
  if (typeof value !== "string") throw new Error(COUNT_MESSAGES.selection);
  const total = countInteger(steps, 1, COUNT_MAX_STEPS, COUNT_MESSAGES.steps);
  const selected = value
    .trim()
    .split(/[,，\s]+/)
    .map((item) => countInteger(item, 1, total, COUNT_MESSAGES.selection));
  if (new Set(selected).size !== selected.length) throw new Error(COUNT_MESSAGES.selection);
  return selected;
}
function abortStep(value: unknown, steps: unknown): number | null {
  if (value === undefined || value === "") return null;
  return countInteger(
    value,
    1,
    countInteger(steps, 1, COUNT_MAX_STEPS, COUNT_MESSAGES.steps),
    COUNT_MESSAGES.abort,
  );
}
function countInput(values: CountFormValues): CountInput {
  return {
    steps: countInteger(values.steps, 1, COUNT_MAX_STEPS, COUNT_MESSAGES.steps),
    interval_ms: countInteger(
      values.interval_ms,
      0,
      COUNT_MAX_INTERVAL_MS,
      COUNT_MESSAGES.interval,
    ),
    failed_steps: countSelection(values.failed_steps, values.steps),
    warning_steps: countSelection(values.warning_steps, values.steps),
    abort_at_step: abortStep(values.abort_at_step, values.steps),
  };
}
function validateField(action: () => unknown): Promise<void> {
  try {
    action();
    return Promise.resolve();
  } catch (error) {
    return Promise.reject(error instanceof Error ? error : new Error("表单输入不合法"));
  }
}

function JobProgressView({ job, timing }: { job: Job; timing: JobTiming }): ReactElement {
  const progress = job.progress;
  return (
    <>
      {progress && (
        <>
          <div>
            阶段 {progress.stage_index}/{progress.stage_count} · {progress.stage_name}
          </div>
          {progress.total === null ? (
            <div>
              已处理 {progress.done} {progress.unit}
            </div>
          ) : (
            <Progress
              aria-label="作业进度"
              percent={
                progress.total === 0 ? 0 : Math.round((100 * progress.done) / progress.total)
              }
            />
          )}
          <div>
            条目 {progress.total_items} · 失败 {progress.failed_items} · 警告{" "}
            {progress.warning_count}
          </div>
        </>
      )}
      {timing.elapsedSeconds !== null && <div>已用时间 {timing.elapsedSeconds.toFixed(1)} 秒</div>}
      {timing.unitsPerSecond !== null && (
        <div>
          速度 {timing.unitsPerSecond.toFixed(1)} {progress?.unit}/秒
        </div>
      )}
      {timing.remainingSeconds !== null && (
        <div>剩余时间 {timing.remainingSeconds.toFixed(1)} 秒</div>
      )}
    </>
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
