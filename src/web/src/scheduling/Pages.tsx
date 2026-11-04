import "./scheduling.css";
// 只读调度页面；沿用 Ant Design/DiagnosticCard，展示只读数据库快照。
import { Typography, Table, Alert, Breadcrumb, Card } from "antd";
import { Link } from "@tanstack/react-router";
import { useScheduling } from "./queries";
import { DiagnosticCard, DiagnosticEntries } from "../DiagnosticCard";
import { toFailureView } from "../api/problems";
import { JOB_OUTCOME_LABELS, JOB_STATE_LABELS } from "../jobs/progress";
import type { Scheduling } from "../api/scheduling";
import type { ReactElement } from "react";
import { formatDateTime } from "../time";

/**
 * 显示所有登录账号可见的只读调度页。
 * @returns /scheduling 的单一只读页面：每类上限和运行数、每张卡的可用/移出/未知状态、移出诊断及作业链接、写锁持有者、每日下次时刻及上次结果；空闲/从未提交有独立提示。页头及资源区附说明，定时作业用途直接显示接口的规则说明。
 * @throws 无；请求失败用 DiagnosticCard，不把故障伪装为资源空闲。
 * @sideEffects 调用 useScheduling，同时显示资源与每日计划，不添加页签或 URL 参数；不提供资源/并发配置修改操作。登录菜单增加“调度”入口，普通成员同样可见。
 * @timeSemantics 每秒轮询，离页停止；服务端 UTC 仅显示时转浏览器本地。worker 离线时注明“最后已保存状态”，到期而未提交显示等待 worker，不伪造下一天。
 */
export function SchedulingPage(): ReactElement {
  const query = useScheduling();
  if (query.isError) return <DiagnosticCard failure={toFailureView(query.error)} />;
  if (!query.data) return <Typography.Text>正在读取调度…</Typography.Text>;
  const data = query.data;
  return (
    <section className="scheduling-page">
      <header className="app-page-header">
        <Breadcrumb items={[{ title: "作业" }, { title: "调度" }]} />
        <Typography.Title level={2} className="app-page-title">
          调度
        </Typography.Title>
        <Typography.Paragraph type="secondary">
          这里只读，显示后台 worker
          现在在忙什么、资源被谁占着、定时任务的运行情况。作业一直排队或显示在等待时，来这里看卡在哪。
        </Typography.Paragraph>
      </header>
      {!data.worker_online && <Alert type="warning" title="worker 离线，以下为最后已保存状态" />}
      <Card>
        <Table<Scheduling["types"][number]>
          scroll={{ x: "max-content" }}
          rowKey="type_name"
          pagination={false}
          dataSource={data.types}
          columns={[
            { title: "作业类型", dataIndex: "display_name" },
            { title: "并发上限", dataIndex: "concurrency" },
            { title: "正在运行", dataIndex: "running_count" },
          ]}
        />
      </Card>
      <Card>
        <section aria-label="GPU 名额">
          <Typography.Title level={3}>GPU 名额</Typography.Title>
          <Typography.Paragraph type="secondary">
            {
              '两张显卡各在给哪个作业用。worker 启动时会核对每张卡，核对不过的卡显示"已移出名额池"和原因，之后不再分配。需要 GPU 的作业领到卡才开始运行，领不到就排队。'
            }
          </Typography.Paragraph>
          {data.gpus.length === 0 && <Typography.Text>平台未配置 GPU</Typography.Text>}
          {data.gpus.map((card) => (
            <div key={card.gpu_index}>
              <Typography.Text>GPU {card.gpu_index}：</Typography.Text>
              {card.availability === "excluded" ? (
                <>
                  <Typography.Text>已移出名额池</Typography.Text>
                  <div>修复后需重启 worker 重新核对</div>
                  {card.checked_at && (
                    <div>
                      核对时间：
                      <time dateTime={card.checked_at}>{formatDateTime(card.checked_at)}</time>
                    </div>
                  )}
                  <DiagnosticEntries diagnostics={card.diagnostics} />
                </>
              ) : card.job_id ? (
                <Link to="/jobs/$jobId" params={{ jobId: card.job_id }}>
                  #{card.job_id}
                </Link>
              ) : (
                <Typography.Text>
                  {card.availability === "available" ? "空闲" : "尚未核对"}
                </Typography.Text>
              )}
            </div>
          ))}
        </section>
      </Card>
      <Card>
        <section aria-label="导航层写锁">
          <Typography.Title level={3}>导航层写锁</Typography.Title>
          <Typography.Paragraph type="secondary">
            {
              '导航层是数据集的唯一事实来源，同一时间只允许一个作业修改，例如建链、改字段、撤回，避免两个作业同时改坏同一份文件。某个作业一直显示"等待导航层写锁"时，在这里可以看到锁在谁手里。'
            }
          </Typography.Paragraph>
          {data.navigation_job_id ? (
            <Link to="/jobs/$jobId" params={{ jobId: data.navigation_job_id }}>
              #{data.navigation_job_id}
            </Link>
          ) : (
            "无人持有"
          )}
        </section>
      </Card>
      <Card>
        <section aria-label="定时作业">
          <Typography.Title level={3}>定时作业</Typography.Title>
          <Typography.Paragraph type="secondary">
            {
              'worker 每天自动提交的作业，提交人显示为"系统"。机器关着错过了时间，下次 worker 启动时会补跑一次。另外，worker 每 10 分钟会自动重新扫描一次导航层，扫描作业出现在作业列表里，不列在这里。'
            }
          </Typography.Paragraph>
          <Table<Scheduling["schedules"][number]>
            scroll={{ x: "max-content" }}
            rowKey="name"
            pagination={false}
            dataSource={data.schedules}
            columns={[
              { title: "名称", dataIndex: "name" },
              { title: "做什么", dataIndex: "description" },
              {
                title: "下次运行",
                render: (_value: unknown, item) => (
                  <>
                    <time dateTime={item.next_run_at}>{formatDateTime(item.next_run_at)}</time>
                    {Date.parse(item.next_run_at) <= Date.parse(data.checked_at) && (
                      <div>已到点，等待 worker</div>
                    )}
                  </>
                ),
              },
              {
                title: "上次作业",
                render: (_value: unknown, item) =>
                  item.last_job_id ? (
                    <Link to="/jobs/$jobId" params={{ jobId: item.last_job_id }}>
                      #{item.last_job_id}
                    </Link>
                  ) : (
                    "从未提交"
                  ),
              },
              {
                title: "上次结果",
                render: (_value: unknown, item) =>
                  item.last_outcome
                    ? JOB_OUTCOME_LABELS[item.last_outcome]
                    : item.last_state && item.last_state !== "completed"
                      ? JOB_STATE_LABELS[item.last_state]
                      : "—",
              },
            ]}
          />
        </section>
      </Card>
    </section>
  );
}
