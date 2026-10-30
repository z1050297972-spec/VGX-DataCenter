// 导航层恢复失败：所有页面顶部的提示，以及列出对不上项、供管理员确认的独立页面（M1-07）。
// 独立成页而不放进作业页：标记是全局事实，可跨多个作业；提示的链接直接到这里。
import type { ReactElement } from "react";
import { Alert, Button, Modal, Table, Typography } from "antd";
import { Link } from "@tanstack/react-router";
import { useCurrentAccount } from "../accounts/runtime";
import { DiagnosticCard } from "../DiagnosticCard";
import { toFailureView } from "../api/problems";
import type { MismatchItem, RecoveryBlock } from "../api/navigation";
import { formatDateTime } from "../format";
import { useAcknowledgeRecoveryBlock, useRecoveryBlock } from "./queries";

/**
 * 在每个已登录页面顶部提示写导航层的作业被挡住。
 * @returns 有标记时显示醒目的错误提示和跳到详情的链接；没有标记、首次加载或查询失败时不显示（worker 提示另行报告服务故障）。
 * @throws 无。
 * @sideEffects 由 AccountLayout 挂载并共享 useRecoveryBlock；不发写请求。
 * @timeSemantics 约每秒轮询；管理员确认后下一次轮询或确认成功后立即消失。
 */
export function RecoveryBlockBanner(): ReactElement {
  const query = useRecoveryBlock();
  if (!query.data?.blocked) return <></>;
  return (
    <Alert
      type="error"
      showIcon
      title="导航层写操作已被挡住：上次写入中断后有对不上的项，需管理员处理"
      description={<Link to="/navigation/recovery">查看对不上的项</Link>}
    />
  );
}

/**
 * 列出对不上的项，管理员可确认放行。
 * @returns /navigation/recovery 页面：设置时间、涉及作业、样例数与总数、表格；管理员有“已处理，放行写操作”按钮，点击后二次确认；成员不显示按钮。
 * @throws 无；请求失败用 DiagnosticCard，确认失败保留标记并显示诊断。
 * @sideEffects 确认时一次 POST，成功后标记缓存置空。
 * @timeSemantics 约每秒轮询；时间用 formatDateTime 显示本地时间；确认请求不重试。
 */
export function NavigationRecoveryPage(): ReactElement {
  const query = useRecoveryBlock();
  if (query.isError) return <DiagnosticCard failure={toFailureView(query.error)} />;
  if (!query.data) return <Typography.Text>正在读取…</Typography.Text>;
  return (
    <section style={{ maxWidth: "100%" }}>
      <Typography.Title level={2}>导航层写操作被挡住</Typography.Title>
      {query.data.blocked ? (
        <BlockDetails block={query.data} />
      ) : (
        <Alert type="success" title="当前没有被挡住的写操作" />
      )}
    </section>
  );
}

function BlockSummary({ block }: { block: RecoveryBlock }): ReactElement {
  const shown = block.items?.length ?? 0;
  const total = block.total_items ?? 0;
  return (
    <Typography.Paragraph>
      设置时间：
      {block.set_at ? <time dateTime={block.set_at}>{formatDateTime(block.set_at)}</time> : "未知"}
      ；涉及作业：
      {(block.job_ids ?? []).map((id) => (
        <span key={id}>
          <Link to="/jobs/$jobId" params={{ jobId: id }}>
            #{id}
          </Link>{" "}
        </span>
      ))}
      ；对不上的项共 {total} 项{shown < total ? `，仅显示前 ${String(shown)} 项` : ""}
    </Typography.Paragraph>
  );
}

function BlockDetails({ block }: { block: RecoveryBlock }): ReactElement {
  const account = useCurrentAccount();
  const acknowledge = useAcknowledgeRecoveryBlock();
  const [modal, holder] = Modal.useModal();
  function confirm(): void {
    modal.confirm({
      title: "确认已处理，放行写操作",
      content: "请先人工核对并修好下列路径。确认后会归档并清除写入日志，并记一条操作日志。",
      okText: "确认放行",
      cancelText: "取消",
      onOk: () => acknowledge.mutateAsync().catch(() => undefined),
    });
  }
  return (
    <>
      {holder}
      <BlockSummary block={block} />
      <Table<MismatchItem>
        rowKey={(row) => `${row.job_id}:${String(row.step_index)}:${row.path}`}
        pagination={false}
        tableLayout="fixed"
        dataSource={[...(block.items ?? [])]}
        columns={[
          { title: "作业", dataIndex: "job_id", width: 110, ellipsis: true },
          { title: "路径", dataIndex: "path", width: "28%", ellipsis: true },
          { title: "期望前像", dataIndex: "expected_before", ellipsis: true },
          { title: "期望后像", dataIndex: "expected_after", ellipsis: true },
          { title: "现在的情况", dataIndex: "actual", ellipsis: true },
        ]}
      />
      {account.data?.role === "administrator" ? (
        <Button
          type="primary"
          danger
          aria-label="已处理，放行写操作"
          loading={acknowledge.isPending}
          onClick={confirm}
          style={{ marginTop: 16 }}
        >
          已处理，放行写操作
        </Button>
      ) : (
        <Typography.Paragraph type="secondary" style={{ marginTop: 16 }}>
          需要管理员处理后才能放行。
        </Typography.Paragraph>
      )}
      {acknowledge.isError && <DiagnosticCard failure={toFailureView(acknowledge.error)} />}
    </>
  );
}
