// M1.5-05 全局作业卡片；复用 antd Card 和 useJob，不自建通知、轮询或持久化体系。
import { useCallback, useState, type ReactElement, type ReactNode } from "react";
import { createLink } from "@tanstack/react-router";
import { Button, Card, Flex, Progress, Typography } from "antd";
import { useCurrentAccount } from "../accounts/runtime";
import type { Job } from "../api/jobs";
import { toFailureView } from "../api/problems";
import { DiagnosticCard } from "../DiagnosticCard";
import { JobCardContext, type ShowJobCard } from "./cardContext";
import { jobStatusLabel } from "./progress";
import { useJob } from "./queries";
import "./cards.css";

// Router 注入类型化链接属性，实际锚点由 antd 渲染，避免嵌套两个交互元素。
const JobDetailsLink = createLink(Typography.Link);

interface ProviderProps {
  /** 已登录路由内容；业务页面切换时保留卡片，身份变化时清空卡片。 */
  children: ReactNode;
}
interface CardEntry {
  /** 入队响应，详情首次返回前用于显示已知状态；不伪造进度。 */
  job: Job;
  /** 操作入口给出的中文名称，无单位，非空。 */
  title: string;
}

/**
 * 为登录页面提供可关闭的作业卡片。
 * @param props - 页面子树，沿用外层账号、Query 和 Router 上下文。
 * @param props.children - 已登录路由内容，清理卡片不重新挂载业务页。
 * @returns 页面内容与右下角卡片栈，空栈不占空间。
 * @throws 无；单张卡片请求失败使用统一诊断展示。
 * @sideEffects 每张卡片复用 useJob 请求和终态刷新；关闭仅卸载观察者，不调用取消 API。
 * @timeSemantics 每秒轮询至终态；终态保留到手动关闭，身份切换、退出或刷新清空全部卡片。
 */
export function JobCardsProvider({ children }: ProviderProps): ReactElement {
  const account = useCurrentAccount();
  const accountId = account.data?.account_id;
  const [owner, setOwner] = useState(accountId);
  const [cards, setCards] = useState<CardEntry[]>([]);
  // 身份变化仅清空卡片，不重新挂载业务页，避免触发多余身份查询或重置页面生命周期。
  if (owner !== accountId) {
    setOwner(accountId);
    setCards([]);
  }
  const show = useCallback<ShowJobCard>((job, title) => {
    setCards((current) =>
      current.some((entry) => entry.job.job_id === job.job_id)
        ? current
        : [...current, { job, title }],
    );
  }, []);
  return (
    <JobCardContext.Provider value={show}>
      {children}
      {!!cards.length && (
        <Flex className="jobs-card-stack" role="region" aria-label="已提交作业">
          {cards.map((entry) => (
            <JobCard
              key={entry.job.job_id}
              entry={entry}
              onClose={() => {
                setCards((current) =>
                  current.filter((item) => item.job.job_id !== entry.job.job_id),
                );
              }}
            />
          ))}
        </Flex>
      )}
    </JobCardContext.Provider>
  );
}

// 每张卡片单独持有查询观察者，移除卡片即可交由 Query 回收轮询与在途读取。
function JobCard({ entry, onClose }: { entry: CardEntry; onClose: () => void }): ReactElement {
  const query = useJob(entry.job.job_id);
  const job = query.data ?? entry.job;
  const title = `${entry.title} #${job.job_id}`;
  const reason = failureReason(job);
  return (
    <Card
      size="small"
      className="jobs-card"
      role="region"
      aria-label={title}
      title={<Typography.Text className="jobs-card-title">{title}</Typography.Text>}
      extra={
        <Button type="text" aria-label={`关闭作业卡片 #${job.job_id}`} onClick={onClose}>
          ×
        </Button>
      }
    >
      <Flex vertical gap="small">
        <Typography.Text role="status">{jobStatusLabel(job)}</Typography.Text>
        <CardProgress job={job} />
        {reason && (
          <Typography.Text type="danger" role="alert">
            {reason}
          </Typography.Text>
        )}
        {query.error && <DiagnosticCard failure={toFailureView(query.error)} />}
        <JobDetailsLink to="/jobs/$jobId" params={{ jobId: job.job_id }}>
          查看详情
        </JobDetailsLink>
      </Flex>
    </Card>
  );
}

// 总数未知只显示已处理计数，避免编造百分比；失败进度不能因计数达到总数显示成成功。
function CardProgress({ job }: { job: Job }): ReactElement | null {
  const progress = job.progress;
  if (!progress) return null;
  return (
    <Flex vertical gap="small">
      <Typography.Text type="secondary">
        {progress.stage_name}：{progress.done} {progress.unit}
      </Typography.Text>
      {progress.total !== null && (
        <Progress
          aria-label="作业卡片进度"
          percent={progress.total === 0 ? 0 : Math.round((100 * progress.done) / progress.total)}
          status={job.summary?.outcome === "failed" ? "exception" : "normal"}
          size="small"
        />
      )}
    </Flex>
  );
}

// 只提取第一条错误原因；程序缺陷沿用诊断组件的安全文案，完整诊断留在详情页。
function failureReason(job: Job): string | null {
  if (job.summary?.outcome !== "failed") return null;
  const diagnostic = job.diagnostics
    .flatMap((group) => group.samples)
    .find((item) => item.level === "error");
  if (!diagnostic) return "作业失败，请查看详情中的诊断。";
  return diagnostic.category === "defect"
    ? "作业发生程序缺陷，请按作业编号查看日志。"
    : (diagnostic.actual.split(/\r?\n/)[0] ?? "作业失败，请查看详情中的诊断。");
}
