// 布局 C：文件管理器式逐级目录分栏加右侧预览（M1-05，原型 16）；状态与部件和 A、B 共用。
import type { ReactElement } from "react";
import { Button, Drawer } from "antd";
import type { DatasetTrees } from "../api/datasets";
import { DiagnosticCard } from "../DiagnosticCard";
import { toFailureView } from "../api/problems";
import { DatasetDetails } from "./Details";
import { TreeNodeMeta } from "./BrowserParts";
import { BrowserPanel, useBrowserActions, type BrowserQuery } from "./browserState";

type Node = DatasetTrees["nodes"][number];

// 从当前位置沿 parent_path 向上走到根，得到由浅到深的祖先链（含自身）。
// 位置不在树里（例如被筛选排除）时返回空链，分栏只显示根，预览照常显示。
function chainTo(nodes: Node[], location: string | undefined): Node[] {
  const chain: Node[] = [];
  let current = location
    ? nodes.find((node) => node.entry_path === location || node.path === location)
    : undefined;
  while (current) {
    chain.unshift(current);
    const parent: string | null = current.parent_path;
    current = parent === null ? undefined : nodes.find((node) => node.path === parent);
  }
  return chain;
}

/**
 * 布局 C：路径栏、逐级目录分栏和右侧预览；一致性面板在抽屉里。
 * @param props - 共用查询结果。
 * @param props.query - 页面外层持有的共用查询。
 * @returns 路径栏、目录分栏、预览区和面板抽屉；树加载失败时显示诊断。
 * @throws 无。
 * @sideEffects 点击目录写 entry_path 并清选中项，点击入口写 selected，均保留筛选。
 * @timeSemantics 沿用索引快照；预览里的详情现场读取，规则同布局 A。
 */
export function LayoutC({ query }: { query: BrowserQuery }): ReactElement {
  const actions = useBrowserActions();
  const { search } = actions;
  const nodes = query.trees.data?.nodes ?? [];
  const chain = chainTo(nodes, search.selected ?? search.entry_path ?? undefined);
  const directories = chain.filter((node) => !node.entry_path);
  const roots = nodes.filter((node) => node.parent_path === null);
  const open = (node: Node): void => {
    if (node.entry_path) actions.select(node.entry_path);
    else actions.openDirectory(node.path, node.view);
  };
  const item = (node: Node): ReactElement => {
    const active = chain.some((step) => step.path === node.path);
    return (
      <Button
        key={node.path}
        type={active ? "primary" : "text"}
        block
        className="dataset-miller-item"
        aria-label={`${node.entry_path ? "打开" : "进入"} ${node.name}`}
        aria-current={active ? "true" : undefined}
        onClick={() => {
          open(node);
        }}
      >
        <span className="dataset-tree-node">
          <span className="dataset-tree-name" title={node.name}>
            {node.name}
          </span>
          <TreeNodeMeta node={node} />
        </span>
      </Button>
    );
  };
  const column = (title: string, children: Node[], key: string): ReactElement => (
    <div className="dataset-miller-column" role="group" aria-label={`目录列 ${title}`} key={key}>
      <div className="dataset-miller-heading" title={title}>
        {title}
      </div>
      {children.map(item)}
      {children.length === 0 && <p className="dataset-miller-empty">空目录</p>}
    </div>
  );
  return (
    <div className="dataset-layout-c">
      <div className="dataset-toolbar">
        <nav aria-label="当前路径" className="dataset-path-bar">
          <Button type="link" onClick={actions.clearLocation}>
            导航层
          </Button>
          {chain.map((node) => (
            <span key={node.path} className="dataset-path-step">
              /
              <Button
                type="link"
                title={node.name}
                onClick={() => {
                  open(node);
                }}
              >
                {node.name}
              </Button>
            </span>
          ))}
        </nav>
        <Button aria-expanded={search.panel === true} onClick={actions.togglePanel}>
          一致性面板
        </Button>
      </div>
      {query.panel.error && <DiagnosticCard failure={toFailureView(query.panel.error)} />}
      {query.trees.error && <DiagnosticCard failure={toFailureView(query.trees.error)} />}
      <div className="dataset-miller-workspace">
        <section aria-label="目录分栏" className="dataset-miller-scroll">
          {column("导航层", roots, "root")}
          {directories.map((node) =>
            column(
              node.name,
              nodes.filter((child) => child.parent_path === node.path),
              node.path,
            ),
          )}
        </section>
        <section aria-label="文件预览" className="dataset-preview">
          {search.selected ? (
            <DatasetDetails
              key={search.selected}
              entryPath={search.selected}
              onClose={actions.close}
              onJump={actions.jump}
            />
          ) : (
            <div className="dataset-preview-empty">
              <h3>从目录开始浏览</h3>
              <p>选择一个入口，右侧显示它的详情与 JSON 文件。</p>
            </div>
          )}
        </section>
      </div>
      <Drawer
        open={search.panel === true}
        onClose={actions.togglePanel}
        title="一致性面板"
        size="min(920px, 88vw)"
        destroyOnHidden
      >
        <BrowserPanel query={query} />
      </Drawer>
    </div>
  );
}
