// 布局无关的树、列表和大小展示（M1-04、16）；树汇总值由服务端提供，不叠加跨视图副本。
import type { ReactElement } from "react";
import { Button, Table, Tree } from "antd";
import type { TreeDataNode } from "antd";
import type { components } from "../api/schema";
import type { DatasetList, DatasetTrees } from "../api/datasets";

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
        props.size.size_checked_at
          ? new Date(props.size.size_checked_at).toLocaleString()
          : undefined
      }
    >
      {props.size.display_bytes?.toLocaleString() ?? "未知"}
      {props.size.display_bytes !== null ? " B" : ""} ·{" "}
      {props.size.display_source === "recorded"
        ? "10-12 记录"
        : props.size.display_source === "measured"
          ? "统计值"
          : "未统计"}
    </span>
  );
}

interface TreeProps {
  /** 接口返回的全部树节点。 */ data: DatasetTrees;
  /** 当前显示的视图。 */ view: components["schemas"]["View"];
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
          <span>
            {node.name} · {node.dataset_count} 个 ·{" "}
            {node.size.total_bytes?.toLocaleString() ?? "大小部分未知"}
            {node.size.total_bytes !== null ? " B" : ""}
            {node.size.recorded_entry_count > 0 ? " · 含 10-12 记录" : ""}
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
      selectedKeys={props.selected ? [props.selected] : []}
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
 * @returns 名称、大小、型号标签和 FPS 表格。
 * @throws 无。
 * @sideEffects 点击通过回调改变路由，不自动预加载详情。
 * @timeSemantics 仅展示服务端索引快照。
 */
export function DatasetListTable(props: ListProps): ReactElement {
  return (
    <section aria-label="数据集列表">
      <p>共 {props.data.total} 个数据集</p>
      <Table
        size="small"
        rowKey={(item) => item.dataset_id ?? item.entries[0]?.entry_path ?? item.name}
        dataSource={props.data.items}
        columns={[
          {
            title: "数据集",
            key: "name",
            render: (_, item) => (
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
