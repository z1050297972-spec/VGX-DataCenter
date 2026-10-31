// parquet只读预览（M1.5-04）：结构与数据分开显示；宽表只在局部滚动，不撑宽查看器。
import { useState, type ReactElement } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button, Table } from "antd";
import { useAccountClient, useCurrentAccount } from "../accounts/runtime";
import { readParquet, type FileLocation, type ParquetPage } from "../api/fileViewer";
import { toFailureView } from "../api/problems";
import { DiagnosticCard } from "../DiagnosticCard";

// 工单单页上限200；与后端返回limit配合，分页偏移不依赖表格的内部行键。
const PAGE_ROWS = 200;

interface ParquetPreviewProps {
  /** 已登记文件位置，不接受系统绝对路径。 */ location: FileLocation;
}

/**
 * 显示parquet表结构、行组计数和有界单元格分页。
 * @param props - 当前已登记文件的位置，路径相对于链接目标。
 * @returns 结构表与局部可滚动的数据表，超过2GiB明确提示仅结构。
 * @throws 无；接口失败展示统一诊断。
 * @sideEffects GET结构和分页；离开或翻页取消旧请求，不写存储或URL。
 * @timeSemantics 不轮询、不重试、不保留离开后的缓存；文件变化在下一次读取体现。
 */
export function ParquetPreview(props: ParquetPreviewProps): ReactElement {
  const { location } = props;
  const [offset, setOffset] = useState(0);
  const client = useAccountClient();
  const account = useCurrentAccount();
  const query = useQuery({
    queryKey: ["datasets", account.data?.account_id, "parquet", location, offset],
    queryFn: ({ signal }) => readParquet({ client, payload: { ...location, offset }, signal }),
    retry: false,
    staleTime: 0,
    gcTime: 0,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
  const page = query.data;
  return (
    <section aria-label="parquet预览">
      {query.isFetching && <p role="status">正在读取parquet</p>}
      {query.error && <DiagnosticCard failure={toFailureView(query.error)} />}
      {page && (
        <>
          <p>
            总行数：{page.total_rows} · 行组：{page.row_groups}
          </p>
          <div className="file-viewer-table" role="region" aria-label="parquet表结构">
            <Table
              size="small"
              pagination={false}
              scroll={{ x: "max-content" }}
              rowKey={(_, index) => String(index)}
              dataSource={page.columns}
              columns={[
                { title: "列名", dataIndex: "name" },
                { title: "类型", dataIndex: "type" },
              ]}
            />
          </div>
          {page.schema_only ? (
            <p>文件超过2 GiB，仅展示表结构和行数。</p>
          ) : (
            <>
              <div className="file-viewer-table" role="region" aria-label="parquet数据表格">
                <Table
                  size="small"
                  pagination={false}
                  scroll={{ x: "max-content" }}
                  rowKey={(_, index) => String(offset + (index ?? 0))}
                  dataSource={page.rows}
                  columns={page.columns.map((column, index) => ({
                    title: column.name,
                    key: String(index),
                    render: (_: unknown, row: ParquetPage["rows"][number]) => {
                      const cell = row[index];
                      return (
                        <span className="file-viewer-cell">
                          {cell?.text}
                          {cell?.truncated ? "…（已截断）" : ""}
                        </span>
                      );
                    },
                  }))}
                />
              </div>
              <p>当前行偏移：{offset}</p>
              <Button
                aria-label="parquet上一页"
                disabled={offset === 0 || query.isFetching}
                onClick={() => {
                  setOffset(Math.max(0, offset - PAGE_ROWS));
                }}
              >
                上一页
              </Button>
              <Button
                aria-label="parquet下一页"
                disabled={!page.has_more || query.isFetching}
                onClick={() => {
                  setOffset(offset + PAGE_ROWS);
                }}
              >
                下一页
              </Button>
            </>
          )}
        </>
      )}
    </section>
  );
}
