// 调度与资源示例页面；沿用 Ant Design/DiagnosticCard，展示只读数据库快照。
import { Typography, Table, Alert, Form, Input, Button } from "antd";
import { Link } from "@tanstack/react-router";
import { useScheduling, useSubmitGpuJob, useSubmitNavigationJob } from "./queries";
import { DiagnosticCard, DiagnosticEntries } from "../DiagnosticCard";
import { toFailureView } from "../api/problems";
import { JOB_OUTCOME_LABELS, JOB_STATE_LABELS } from "../jobs/progress";
import type { Scheduling } from "../api/scheduling";
import type { ReactElement } from "react";

/**
 * 显示所有登录账号可见的只读调度页。
 * @returns /scheduling 的单一只读页面：每类上限和运行数、每张卡的可用/移出/未知状态、移出诊断及作业链接、写锁持有者、每日下次时刻及上次结果；空闲/从未提交有独立提示。
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
    <section>
      <Typography.Title level={2}>调度</Typography.Title>
      {!data.worker_online && <Alert type="warning" title="worker 离线，以下为最后已保存状态" />}
      <Table<Scheduling["types"][number]>
        rowKey="type_name"
        pagination={false}
        dataSource={data.types}
        columns={[
          { title: "作业类型", dataIndex: "display_name" },
          { title: "并发上限", dataIndex: "concurrency" },
          { title: "正在运行", dataIndex: "running_count" },
        ]}
      />
      <section aria-label="GPU 名额">
        <Typography.Title level={3}>GPU 名额</Typography.Title>
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
                    <time dateTime={card.checked_at}>
                      {new Date(card.checked_at).toLocaleString()}
                    </time>
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
      <section aria-label="导航层写锁">
        <Typography.Title level={3}>导航层写锁</Typography.Title>
        {data.navigation_job_id ? (
          <Link to="/jobs/$jobId" params={{ jobId: data.navigation_job_id }}>
            #{data.navigation_job_id}
          </Link>
        ) : (
          "无人持有"
        )}
      </section>
      <section aria-label="定时作业">
        <Typography.Title level={3}>定时作业</Typography.Title>
        <Table<Scheduling["schedules"][number]>
          rowKey="name"
          pagination={false}
          dataSource={data.schedules}
          columns={[
            { title: "名称", dataIndex: "name" },
            {
              title: "下次运行",
              render: (_value: unknown, item) => (
                <>
                  <time dateTime={item.next_run_at}>
                    {new Date(item.next_run_at).toLocaleString()}
                  </time>
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
    </section>
  );
}

/**
 * 提供资源演示的两种类型化提交表单。
 * @returns /jobs/resources 的占卡秒数表单及写锁期望值/暂停秒数表单；空期望值可提交，值不含文件路径。
 * @throws 无；范围/类型错误在字段提示，服务端故障交 DiagnosticCard，保留已填写值。
 * @sideEffects 分别调用 useSubmitGpuJob/useSubmitNavigationJob；提交期间禁用按钮，成功进入对应新详情。期望新值为成功写入作业的编号文本，页面说明可从上次详情取得。
 * @timeSemantics 只发一次 10 秒请求，不自动重试；GPU 等待可取消，锁内暂停和取消延后规则在表单说明中呈现。
 */
export function SubmitResourceJobsPage(): ReactElement {
  return (
    <section>
      <Typography.Title level={2}>资源示例作业</Typography.Title>
      <GpuForm />
      <NavigationForm />
    </section>
  );
}

// 范围与后端生成模型一致；表单暂存文本，不能把true或空值隐式转换为数字。
const GPU_HOLD_MAX_S = 600;
function integer(value: unknown, maximum: number, message: string): number {
  if (typeof value !== "string" || !/^\d+$/u.test(value) || Number(value) > maximum)
    throw new Error(message);
  return Number(value);
}
function validate(check: () => unknown): Promise<void> {
  try {
    check();
    return Promise.resolve();
  } catch (error) {
    return Promise.reject(error instanceof Error ? error : new Error("输入不合法"));
  }
}
function GpuForm(): ReactElement {
  const submit = useSubmitGpuJob();
  const message = `占用秒数须为0至${String(GPU_HOLD_MAX_S)}的整数`;
  return (
    <section>
      <Typography.Title level={3}>示例：占用 GPU</Typography.Title>
      <Typography.Paragraph>等待 GPU 和占用名额期间可以取消作业。</Typography.Paragraph>
      <Form<{ hold_s: string }>
        layout="vertical"
        initialValues={{ hold_s: "0" }}
        disabled={submit.isPending}
        onFinish={(values) => {
          submit.mutate({ hold_s: integer(values.hold_s, GPU_HOLD_MAX_S, message) });
        }}
      >
        <Form.Item
          name="hold_s"
          label="占用秒数"
          rules={[
            {
              validator: (_rule, value: unknown) =>
                validate(() => integer(value, GPU_HOLD_MAX_S, message)),
            },
          ]}
        >
          <Input inputMode="numeric" />
        </Form.Item>
        <Button
          aria-label="提交占卡作业"
          htmlType="submit"
          type="primary"
          disabled={submit.isPending}
          loading={submit.isPending}
        >
          提交占卡作业
        </Button>
      </Form>
      {submit.isError && <DiagnosticCard failure={toFailureView(submit.error)} />}
    </section>
  );
}

// 写锁暂停受worker的共同停止预算约束；期望值按Unicode码点计数，与生成模型一致。
const NAVIGATION_PAUSE_MAX_S = 10;
const EXPECTED_VALUE_MAX_CHARS = 256;
function expectedValue(value: unknown): string {
  if (typeof value !== "string" || Array.from(value).length > EXPECTED_VALUE_MAX_CHARS)
    throw new Error(`期望值最多${String(EXPECTED_VALUE_MAX_CHARS)}个字符`);
  return value;
}
function NavigationForm(): ReactElement {
  const submit = useSubmitNavigationJob();
  const message = `暂停须为0至${String(NAVIGATION_PAUSE_MAX_S)}的整数秒`;
  return (
    <section>
      <Typography.Title level={3}>示例：写锁</Typography.Title>
      <Typography.Paragraph>
        首次期望值为空，后续填写上次成功写入的作业编号。等待写锁时可取消，写入开始后会在写完后处理取消。
      </Typography.Paragraph>
      <Form<{ expected_value: string; pause_s: string }>
        layout="vertical"
        initialValues={{ expected_value: "", pause_s: "0" }}
        disabled={submit.isPending}
        onFinish={(values) => {
          submit.mutate({
            expected_value: expectedValue(values.expected_value),
            pause_s: integer(values.pause_s, NAVIGATION_PAUSE_MAX_S, message),
          });
        }}
      >
        <Form.Item
          name="expected_value"
          label="期望值"
          rules={[{ validator: (_rule, value: unknown) => validate(() => expectedValue(value)) }]}
        >
          <Input />
        </Form.Item>
        <Form.Item
          name="pause_s"
          label="写入前暂停（秒）"
          rules={[
            {
              validator: (_rule, value: unknown) =>
                validate(() => integer(value, NAVIGATION_PAUSE_MAX_S, message)),
            },
          ]}
        >
          <Input inputMode="numeric" />
        </Form.Item>
        <Button
          aria-label="提交写锁作业"
          htmlType="submit"
          type="primary"
          disabled={submit.isPending}
          loading={submit.isPending}
        >
          提交写锁作业
        </Button>
      </Form>
      {submit.isError && <DiagnosticCard failure={toFailureView(submit.error)} />}
    </section>
  );
}
