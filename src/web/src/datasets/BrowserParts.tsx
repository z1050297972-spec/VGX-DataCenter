// 布局无关的树、列表和大小展示（M1-04、16）；树汇总值由服务端提供，不叠加跨视图副本。
import type { ReactElement } from "react";
import { Button, Table, Tree } from "antd";
import type { TreeDataNode } from "antd";
import type { components } from "../api/schema";
import type { DatasetList, DatasetTrees } from "../api/datasets";
import { exactBytes, formatBytes } from "./formatBytes";
import { formatDateTime } from "../time";

import { useDatasetFilterOptions } from "./queries";
import { classificationName, classificationTasks } from "./classificationLabels";

type Size = components["schemas"]["DatasetSize"];

/**
 * 显示统计值或带记录日期的大小，未知值不当成零。
 * @param props - size 为服务端字节数及其来源，不自行重算。
 * @param props.size - 服务端字节值、来源与统计时刻。
 * @returns 可见大小和来源。
 * @throws 无。
 * @sideEffects 无。
 * @timeSemantics 统计值显示原统计时刻，转换为浏览器本地时间。
 */
export function DatasetSizeLabel(props: {
  /** 服务端单入口或数据集大小。 */ size: Size;
}): ReactElement {
  return (
    <span
      title={
        [
          exactBytes(props.size.display_bytes),
          props.size.size_checked_at ? formatDateTime(props.size.size_checked_at) : undefined,
        ]
          .filter((part) => part !== undefined)
          .join(" · ") || undefined
      }
    >
      {formatBytes(props.size.display_bytes)} ·{" "}
      {props.size.display_source === "recorded"
        ? "10-12 记录"
        : props.size.display_source === "measured"
          ? "统计值"
          : "未统计"}
    </span>
  );
}

type TreeNode = DatasetTrees["nodes"][number];
/**
 * 显示树节点的数据集数量和大小；三种布局的目录、入口行都用它，数字口径一致。
 * @param props - 服务端树节点，汇总值由服务端给出，不在前端叠加。
 * @param props.node - 树节点。
 * @returns 数量、人读大小、10-12 记录标记；悬停给精确字节。
 * @throws 无。
 * @sideEffects 无。
 * @timeSemantics 沿用索引快照，不实时统计。
 */
export function TreeNodeMeta(props: { node: TreeNode }): ReactElement {
  const { node } = props;
  return (
    <span className="dataset-tree-meta" title={exactBytes(node.size.total_bytes)}>
      {node.dataset_count} 个 ·{" "}
      {node.size.total_bytes === null ? "大小部分未知" : formatBytes(node.size.total_bytes)}
      {node.size.recorded_entry_count > 0 ? " · 含 10-12 记录" : ""}
    </span>
  );
}

interface TreeProps {
  /** 接口返回的全部树节点。 */ data: DatasetTrees;
  /** 当前显示的视图。 */ view: components["schemas"]["DatasetTreeNode"]["view"];
  /** 用户选择节点路径的回调。 */ onSelect: (path: string) => void;
  /** 当前选中的入口或目录路径。 */ selected?: string;
}
/**
 * 展示指定视图的树及每节点数量、大小来源。
 * @param props - 平铺索引与选中回调，字段见 TreeProps。
 * @returns Ant Design 树；空视图仍保留根。
 * @throws 无。
 * @sideEffects 用户选择时调用 onSelect；不发送请求。
 * @timeSemantics 展示索引快照，不实时统计数据盘。
 */
export function DatasetTree(props: TreeProps): ReactElement {
  const nodes = props.data.nodes.filter((node) => node.view === props.view);
  function children(parent: string | null): TreeDataNode[] {
    return nodes
      .filter((node) => node.parent_path === parent)
      .map((node) => ({
        key: node.path,
        title: (
          <span className="dataset-tree-node">
            <span className="dataset-tree-name" title={node.name}>
              {node.name}
            </span>
            <TreeNodeMeta node={node} />
          </span>
        ),
        children: children(node.path),
      }));
  }
  return (
    <Tree
      key={props.view}
      defaultExpandAll
      blockNode
      treeData={children(null)}
      selectedKeys={nodes
        .filter((node) => node.path === props.selected || node.entry_path === props.selected)
        .map((node) => node.path)}
      onSelect={(keys) => {
        const path = keys[0];
        if (typeof path === "string") props.onSelect(path);
      }}
    />
  );
}

interface ListProps {
  /** 服务端当前页，total 是去重数据集数量。 */ data: DatasetList;
  /** 用户打开一个入口时调用。 */ onOpen: (path: string) => void;
  /** 用户翻页时给出从零开始的偏移。 */ onPage: (offset: number) => void;
}
/**
 * 显示去重数据集列表及有界分页。
 * @param props - 列表、打开入口和翻页回调。
 * @returns 名称、中文场景与任务、导航型号、大小、原文件型号标签和 FPS 表格。
 * @throws 无。
 * @sideEffects 点击通过回调改变路由，不自动预加载详情。
 * @timeSemantics 仅展示服务端索引快照。
 */
export function DatasetListTable(props: ListProps): ReactElement {
  const vocabulary = useDatasetFilterOptions().data;
  return (
    <section aria-label="数据集列表">
      <p>共 {props.data.total} 个数据集</p>
      <Table
        scroll={{ x: "max-content" }}
        size="small"
        rowKey={(item) => item.dataset_id ?? item.entries[0]?.entry_path ?? item.name}
        dataSource={props.data.items}
        columns={[
          {
            title: "数据集",
            key: "name",
            render: (_, item) => (
              <div>
                <Button
                  type="link"
                  aria-label={`打开 ${item.name}`}
                  onClick={() => {
                    const path = item.canonical_entry_path ?? item.entries[0]?.entry_path;
                    if (path) props.onOpen(path);
                  }}
                >
                  {item.name}
                </Button>
                <div className="dataset-classification">
                  <span>场景：{classificationName(item.scene, vocabulary?.scene_vocabulary)}</span>
                  <span>任务：{classificationTasks(item.tasks, vocabulary?.task_vocabulary)}</span>
                  <span>机器人型号：{item.robot_model || "未填写"}</span>
                </div>
              </div>
            ),
          },
          {
            title: "大小",
            key: "size",
            render: (_, item) => <DatasetSizeLabel size={item.size} />,
          },
          {
            title: "型号标签",
            key: "robot",
            render: (_, item) => item.robot_types.map((value) => value ?? "未知").join("、"),
          },
          {
            title: "FPS",
            key: "fps",
            render: (_, item) => item.fps.map((value) => value ?? "未知").join("、"),
          },
        ]}
        pagination={{
          current: Math.floor(props.data.offset / props.data.limit) + 1,
          pageSize: props.data.limit,
          total: props.data.total,
          showSizeChanger: false,
          onChange: (page) => {
            props.onPage((page - 1) * props.data.limit);
          },
        }}
      />
    </section>
  );
}
