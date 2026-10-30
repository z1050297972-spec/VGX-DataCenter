// 布局 B：树形大表加详情抽屉（M1-05，原型 16）；状态与部件和 A、C 共用，不另写部件。
import type { ReactElement } from "react";
import { Button, Drawer, Segmented, Table } from "antd";
import type { DatasetTrees } from "../api/datasets";
import { DiagnosticCard } from "../DiagnosticCard";
import { toFailureView } from "../api/problems";
import { DatasetDetails } from "./Details";
import { TreeNodeMeta } from "./BrowserParts";
import { BrowserPanel, useBrowserActions, type BrowserQuery } from "./browserState";

/** 表格行：一个树节点及其子行；key 用节点路径，稳定且在两棵树里不重复。 */
interface Row {
  key: string;
  node: DatasetTrees["nodes"][number];
  children?: Row[];
}

// 从平铺节点按 parent_path 还原当前视图的树；目录没有子行时不带 children，免得显示空展开按钮。
function toRows(nodes: DatasetTrees["nodes"], parent: string | null): Row[] {
  return nodes
    .filter((node) => node.parent_path === parent)
    .map((node) => {
      const children = toRows(nodes, node.path);
      return { key: node.path, node, children: children.length ? children : undefined };
    });
}
// 默认展开全部目录，和布局 A 的树一致。
function directoryKeys(rows: Row[]): string[] {
  return rows.flatMap((row) => (row.children ? [row.key, ...directoryKeys(row.children)] : []));
}

/**
 * 布局 B：当前视图的树形表格，点入口在右侧抽屉看详情，一致性面板在表格上方展开。
 * @param props - 共用查询结果。
 * @param props.query - 页面外层持有的共用查询。
 * @returns 视图切换、面板开关、树形表格和抽屉；树加载失败只显示诊断，不遮住面板。
 * @throws 无。
 * @sideEffects 点击写 URL（selected、tree_view、panel）；抽屉关闭只清选中项。
 * @timeSemantics 数量与大小沿用索引快照；抽屉内详情现场读取，规则同布局 A。
 */
export function LayoutB({ query }: { query: BrowserQuery }): ReactElement {
  const actions = useBrowserActions();
  const { search } = actions;
  const view = search.tree_view ?? "format";
  const rows = query.trees.data
    ? toRows(
        query.trees.data.nodes.filter((node) => node.view === view),
        null,
      )
    : [];
  return (
    <div className="dataset-layout-b">
      <div className="dataset-toolbar">
        <Segmented
          aria-label="浏览视图"
          name="dataset-view"
          value={view}
          onChange={(value) => {
            actions.setView(value === "task" ? "task" : "format");
          }}
          options={[
            { value: "format", label: "按格式" },
            { value: "task", label: "按任务" },
          ]}
        />
        <Button aria-expanded={search.panel === true} onClick={actions.togglePanel}>
          一致性面板
        </Button>
      </div>
      {query.panel.error && <DiagnosticCard failure={toFailureView(query.panel.error)} />}
      {search.panel && <BrowserPanel query={query} />}
      {query.trees.error && <DiagnosticCard failure={toFailureView(query.trees.error)} />}
      <section aria-label="树形表格">
        <Table<Row>
          key={view}
          size="small"
          scroll={{ x: "max-content" }}
          pagination={false}
          rowKey="key"
          loading={query.trees.isPending}
          dataSource={rows}
          expandable={{ defaultExpandedRowKeys: directoryKeys(rows) }}
          rowClassName={(row) =>
            row.node.entry_path === search.selected ? "dataset-row-selected" : ""
          }
          columns={[
            {
              title: "目录 / 数据集",
              key: "name",
              render: (_, row) =>
                row.node.entry_path ? (
                  <Button
                    type="link"
                    className="dataset-table-name"
                    aria-label={`打开 ${row.node.name}`}
                    onClick={() => {
                      if (row.node.entry_path) actions.select(row.node.entry_path);
                    }}
                  >
                    <span className="dataset-tree-name" title={row.node.name}>
                      {row.node.name}
                    </span>
                  </Button>
                ) : (
                  <span className="dataset-tree-name dataset-table-name" title={row.node.name}>
                    {row.node.name}
                  </span>
                ),
            },
            {
              title: "数量与大小",
              key: "meta",
              render: (_, row) => <TreeNodeMeta node={row.node} />,
            },
          ]}
        />
      </section>
      <Drawer
        // 抽屉入场时内容会平移到视口外；根容器裁掉这段溢出，宽表仍在各自容器内滚动。
        rootStyle={{ overflow: "hidden" }}
        open={Boolean(search.selected)}
        onClose={actions.close}
        title="入口详情"
        size="60vw"
        destroyOnHidden
      >
        {search.selected && (
          <DatasetDetails
            key={search.selected}
            entryPath={search.selected}
            onClose={actions.close}
            onJump={actions.jump}
          />
        )}
      </Drawer>
    </div>
  );
}
