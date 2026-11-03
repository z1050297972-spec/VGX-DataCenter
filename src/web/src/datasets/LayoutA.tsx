// 布局 A：视图树、列表或连续详情与说明行（M1-04）；状态与部件和 B、C 共用。
import type { ReactElement } from "react";
import { Button, Card, Col, Flex, Row, Tabs, Typography } from "antd";
import { DiagnosticCard } from "../DiagnosticCard";
import { toFailureView } from "../api/problems";
import { DatasetDetails } from "./Details";
import { DatasetTree, DatasetListTable } from "./BrowserParts";
import { BrowserPanel, useBrowserActions, type BrowserQuery } from "./browserState";

/**
 * 布局 A 的双栏排布。
 * @param props - 共用查询结果。
 * @param props.query - 页面外层持有的共用查询。
 * @returns 一致性面板打开时替换内容区，否则双栏；单个请求失败不遮住其他内容。
 * @throws 无。
 * @sideEffects 点击写 URL，不发额外请求。
 * @timeSemantics 沿用共用查询的快照。
 */
export function LayoutA({ query }: { query: BrowserQuery }): ReactElement {
  const actions = useBrowserActions();
  const { search } = actions;
  return (
    <>
      <Flex justify={search.panel ? "end" : "space-between"} align="center" gap="middle" wrap>
        {!search.panel && (
          <Typography.Text type="secondary">
            按任务入口代表完整数据集，按格式入口代表对应格式下可使用的部分。
          </Typography.Text>
        )}
        <Button onClick={actions.togglePanel}>{search.panel ? "返回数据集" : "一致性面板"}</Button>
      </Flex>
      {query.panel.error && <DiagnosticCard failure={toFailureView(query.panel.error)} />}
      {search.panel ? (
        <BrowserPanel query={query} />
      ) : (
        <Row gutter={[24, 24]} className="dataset-layout-a">
          <Col xs={24} md={7}>
            <Card>
              <TreeColumn query={query} />
            </Card>
          </Col>
          <Col xs={24} md={17}>
            <Card>
              <main>
                <MainColumn query={query} />
              </main>
            </Card>
          </Col>
        </Row>
      )}
    </>
  );
}

// 节点路径是导航标识；目录选择只筛列表，叶节点选择打开现场详情。
function TreeColumn({ query }: { query: BrowserQuery }): ReactElement {
  const actions = useBrowserActions();
  const { search } = actions;
  return (
    <aside aria-label="视图树">
      <Tabs
        aria-label="浏览视图"
        activeKey={search.tree_view ?? "format"}
        onChange={(value) => {
          actions.setView(value === "scene" ? "scene" : value === "task" ? "task" : "format");
        }}
        items={[
          { key: "format", label: "按格式" },
          { key: "task", label: "按任务" },
          { key: "scene", label: "按场景" },
        ]}
      />
      {query.trees.error && <DiagnosticCard failure={toFailureView(query.trees.error)} />}
      {query.trees.data && (
        <DatasetTree
          data={query.trees.data}
          view={search.tree_view ?? "format"}
          selected={search.selected ?? search.entry_path ?? undefined}
          onSelect={(path) => {
            const node = query.trees.data?.nodes.find((item) => item.path === path);
            if (node?.entry_path) actions.select(node.entry_path);
            else actions.openDirectory(path);
          }}
        />
      )}
    </aside>
  );
}

// 连续详情替换列表，与确认原型 A 一致；返回和跨视图不丢失筛选。
function MainColumn({ query }: { query: BrowserQuery }): ReactElement {
  const actions = useBrowserActions();
  const { search } = actions;
  if (search.selected)
    return (
      <DatasetDetails
        key={search.selected}
        entryPath={search.selected}
        onClose={actions.close}
        onJump={actions.jump}
      />
    );
  return (
    <>
      {query.list.error && <DiagnosticCard failure={toFailureView(query.list.error)} />}
      {query.list.isPending && <p role="status">正在加载数据集</p>}
      {query.list.data && (
        <DatasetListTable
          data={query.list.data}
          onOpen={actions.select}
          onPage={(offset) => {
            actions.setPage(offset);
          }}
        />
      )}
    </>
  );
}
