// 转换暂存只展示worker结果；删除与入库的最终许可始终由worker重新判定。
import { useEffect, useRef, type ReactElement } from "react";
import { Breadcrumb, Button, Card, Flex, Popconfirm, Space, Table, Typography } from "antd";
import { getRouteApi, Link } from "@tanstack/react-router";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useAccountClient, useCurrentAccount } from "../accounts/runtime";
import {
  deleteConversionStaging,
  getConversionStaging,
  type ConversionStaging,
} from "../api/conversionIngest";
import { JOB_POLL_INTERVAL_MS } from "../api/jobs";
import { toFailureView } from "../api/problems";
import { DiagnosticCard } from "../DiagnosticCard";
import { IngestConversion } from "../downloads/Ingest";

const route = getRouteApi("/conversions");
type Item = ConversionStaging["items"][number];

/**
 * 展示转换暂存、检查结论和人工入库入口。
 * @returns 作业页附近的列表，含同页可展开预览和删除确认。
 * @throws Error 缺少应用客户端或路由上下文。
 * @sideEffects 查询作业投影；点击操作后才提交worker作业。
 * @timeSemantics 每秒刷新当前页，离页取消；大小标注为最近检查快照。
 */
export function ConversionStagingPage(): ReactElement {
  const client = useAccountClient();
  const search = route.useSearch();
  const navigate = route.useNavigate();
  const result = useQuery({
    queryKey: ["conversions", "staging", search.before],
    queryFn: ({ signal }) => getConversionStaging(client, search.before, signal),
    refetchInterval: JOB_POLL_INTERVAL_MS,
    retry: false,
  });
  return (
    <Space orientation="vertical" size="large">
      <header>
        <Breadcrumb items={[{ title: "作业" }, { title: "转换暂存" }]} />
        <Typography.Title level={2}>转换暂存</Typography.Title>
      </header>
      <Card>
        <Flex gap="middle" align="center">
          <Typography.Text>大小与检查结果取最近一次检查快照。</Typography.Text>
          <Button
            onClick={() => {
              void result.refetch();
            }}
          >
            刷新
          </Button>
        </Flex>
      </Card>
      {result.isError && <DiagnosticCard failure={toFailureView(result.error)} />}
      <Card>
        <Table<Item>
          rowKey="job_id"
          dataSource={result.data?.items ?? []}
          pagination={false}
          loading={result.isPending}
          scroll={{ x: "max-content" }}
          columns={[
            {
              title: "作业编号",
              render: (_, item) => (
                <Link to="/jobs/$jobId" params={{ jobId: item.job_id }}>
                  #{item.job_id}
                </Link>
              ),
            },
            { title: "输入数据集", dataIndex: "input_dataset" },
            { title: "工具", dataIndex: "tool" },
            { title: "格式", dataIndex: "output_format" },
            { title: "大小（B）", render: (_, item) => item.size_bytes ?? "未知" },
            { title: "检查结果", render: (_, item) => item.check?.result ?? "待检查" },
            { title: "状态", dataIndex: "status" },
            { title: "操作", render: (_, item) => <Actions item={item} /> },
          ]}
        />
        <Space>
          <Button
            disabled={!search.before}
            onClick={() => {
              void navigate({ search: {} });
            }}
          >
            最新
          </Button>
          <Button
            disabled={!result.data?.next_before}
            onClick={() => {
              if (result.data?.next_before)
                void navigate({ search: { before: result.data.next_before } });
            }}
          >
            更早
          </Button>
        </Space>
      </Card>
    </Space>
  );
}

// 删除请求绑定组件生命周期，服务端再次核对活动作业和已提交导航。
function Actions({ item }: { item: Item }): ReactElement {
  const client = useAccountClient();
  const account = useCurrentAccount();
  const active = useRef<AbortController | null>(null);
  useEffect(
    () => () => {
      active.current?.abort();
    },
    [],
  );
  const remove = useMutation({
    mutationFn: async () => {
      active.current = new AbortController();
      try {
        return await deleteConversionStaging(client, item.job_id, active.current.signal);
      } finally {
        active.current = null;
      }
    },
    retry: false,
  });
  return (
    <Space orientation="vertical">
      {item.status !== "已入库" && <IngestConversion jobId={item.job_id} disabled={item.in_use} />}
      {account.data?.role === "administrator" && (
        <Popconfirm
          title="确认删除未入库的转换暂存？"
          onConfirm={() => {
            remove.mutate();
          }}
        >
          <Button
            danger
            disabled={
              item.status === "已入库" || item.in_use || remove.isPending || remove.isSuccess
            }
          >
            删除
          </Button>
        </Popconfirm>
      )}
      {remove.isError && <DiagnosticCard failure={toFailureView(remove.error)} />}
      {remove.data && (
        <Link to="/jobs/$jobId" params={{ jobId: remove.data.job_id }}>
          查看删除作业
        </Link>
      )}
    </Space>
  );
}
