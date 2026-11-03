import "./storage.css";
// 存储根只读页面（10、L3）：成员与管理员相同，不提供配置编辑或文件访问入口。
import type { ReactElement } from "react";
import { Breadcrumb, Button, Card, Flex, Table, Typography } from "antd";
import type { StorageRoot } from "../api/storage";
import { useStorageRoots } from "./queries";
import schema from "../api/openapi.json";
import { DiagnosticCard } from "../DiagnosticCard";
import { toFailureView } from "../api/problems";
import { formatDateTime } from "../time";

// 中文文案由后端唯一映射生成到OpenAPI，生成类型仍负责核对枚举覆盖完整。
const offlineLabels: Record<NonNullable<StorageRoot["reason"]>, string> = schema.components.schemas
  .StorageRootResponse.properties.reason["x-display-labels"];

/**
 * 展示登记根的许可、挂载状态与检查时间。
 * @returns Ant Design 表格，含名字、路径、只读或可写、在线或离线原因、浏览器本地检查时间；空列表显示未登记存储根。
 * @throws 无；请求失败交 DiagnosticCard，不能把失败显示成没挂载。
 * @sideEffects 调用 useStorageRoots，打开页面检查一次；重新检查按钮在请求中禁用；不写配置，不改变 URL search。
 * @timeSemantics 不轮询；等待时显示加载状态，失败保留上次数据和旧时刻并提示失败，不把旧结果标成新检查。
 * 原因逐项显示为“没挂载”“挂错了盘”“超时”；说明本页只核对挂载身份，访问超时只能由作业检查发现。
 */
export function StorageRootsPage(): ReactElement {
  const query = useStorageRoots();
  return (
    <section className="storage-page">
      <header className="app-page-header">
        <Breadcrumb items={[{ title: "数据" }, { title: "存储根" }]} />
        <Flex justify="space-between" align="center" wrap="wrap">
          <Typography.Title level={2} className="app-page-title">
            存储根
          </Typography.Title>
          <Button
            aria-label="重新检查"
            disabled={query.isFetching}
            loading={query.isFetching}
            onClick={() => {
              void query.refetch();
            }}
          >
            重新检查
          </Button>
        </Flex>
      </header>
      {query.error && <DiagnosticCard failure={toFailureView(query.error)} />}
      <Card>
        <Typography.Paragraph>
          本页只核对挂载身份，访问超时只能由作业检查发现。
        </Typography.Paragraph>
        {query.isFetching && <Typography.Text role="status">正在检查</Typography.Text>}
        <Table<StorageRoot>
          scroll={{ x: "max-content" }}
          rowKey="name"
          pagination={false}
          dataSource={query.data?.items}
          locale={{ emptyText: query.data ? "未登记存储根" : "暂无检查结果" }}
          columns={[
            { title: "名字", dataIndex: "name" },
            { title: "路径", dataIndex: "path", className: "storage-path" },
            { title: "许可", render: (_, root) => (root.writable ? "可写" : "只读") },
            {
              title: "状态",
              render: (_, root) =>
                root.online ? "在线" : root.reason ? offlineLabels[root.reason] : "离线",
            },
            {
              title: "检查时间",
              render: (_, root) => (
                <time dateTime={root.checked_at}>{formatDateTime(root.checked_at)}</time>
              ),
            },
          ]}
        />
      </Card>
    </section>
  );
}
