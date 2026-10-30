// 数据集布局 A（M1-04）：装配共享部件，不承担索引计算或导航层写入。
import type { ReactElement } from "react";
import { getRouteApi } from "@tanstack/react-router";
import { Alert, Button, Tabs, Typography } from "antd";
import { DATASET_PAGE_SIZE } from "../api/datasets";
import { DiagnosticCard } from "../DiagnosticCard";
import { toFailureView } from "../api/problems";
import { StorageWarnings } from "./StorageWarnings";
import { ConsistencyPanel } from "./Consistency";
import { DatasetDetails } from "./Details";
import { DatasetFilterBar } from "./Filters";
import { useDatasetBrowser } from "./queries";
import { DatasetTree, DatasetListTable } from "./BrowserParts";
import "./browser.css";

const route = getRouteApi("/datasets");
type BrowserQuery = ReturnType<typeof useDatasetBrowser>;

/**
 * 显示登录账号的数据集视图树、筛选、列表、详情和一致性面板。
 * @returns 三栏布局 A；非法 URL 显示可修正提示，不发数据请求。
 * @throws 无；HTTP 错误通过 DiagnosticCard 展示。
 * @sideEffects 经共用查询读取索引及所选入口，所有筛选、选中入口、页签写入 URL。
 * @timeSemantics 索引读取不轮询；离页取消请求，大小沿用服务端统计时刻。
 */
export function DatasetsPage(): ReactElement {
  const search = route.useSearch();
  const navigate = route.useNavigate();
  if (search.invalidDatasetSearch)
    return (
      <section>
        <Typography.Title level={2}>数据集浏览</Typography.Title>
        <Alert type="error" title="数据集筛选参数不合法" />
        <Button
          onClick={() => {
            void navigate({ search: {}, replace: true });
          }}
        >
          重置筛选
        </Button>
      </section>
    );
  return <BrowserContent />;
}

// 列表、树、面板各自保留错误，单个请求失败不能遮住其他可用内容。
function BrowserContent(): ReactElement {
  const search = route.useSearch();
  const navigate = route.useNavigate();
  const query = useDatasetBrowser({
    robot_type: search.robot_type,
    robot_model_id: search.robot_model_id,
    data_origin: search.data_origin,
    fps: search.fps,
    offset: search.offset,
    entry_path: search.entry_path,
    limit: DATASET_PAGE_SIZE,
  });
  return (
    <section>
      <Typography.Title level={2}>数据集浏览</Typography.Title>
      {query.panel.data && <StorageWarnings roots={query.panel.data.storage_roots} />}
      <Button
        onClick={() => {
          void navigate({ search: { ...search, panel: !search.panel } });
        }}
      >
        {search.panel ? "返回数据集" : "一致性面板"}
      </Button>
      <BrowserFilters query={query} />
      {query.panel.error && <DiagnosticCard failure={toFailureView(query.panel.error)} />}
      {search.panel ? (
        <BrowserPanel query={query} />
      ) : (
        <div className="dataset-layout-a">
          <BrowserTree query={query} />
          <main>
            <BrowserMain query={query} />
          </main>
          <aside>按任务入口代表完整数据集，按格式入口代表对应格式下可使用的部分。</aside>
        </div>
      )}
    </section>
  );
}

// 全局候选不随当前筛选缩小，避免用户无法解除或更换筛选。
function BrowserFilters({ query }: { query: BrowserQuery }): ReactElement {
  const search = route.useSearch();
  const navigate = route.useNavigate();
  return (
    <>
      {query.filters.error && <DiagnosticCard failure={toFailureView(query.filters.error)} />}
      {query.filters.data && (
        <DatasetFilterBar
          options={query.filters.data}
          search={search}
          onChange={(next) => {
            void navigate({ search: next });
          }}
        />
      )}
    </>
  );
}

// 面板只显示最近索引发现；不能把加载中或失败伪装成无问题。
function BrowserPanel({ query }: { query: BrowserQuery }): ReactElement {
  return (
    <>
      {query.panel.isPending && <p role="status">正在加载面板</p>}
      {query.panel.data && <ConsistencyPanel data={query.panel.data} />}
    </>
  );
}

// 节点路径是导航标识；目录选择只筛列表，叶节点选择打开现场详情。
function BrowserTree({ query }: { query: BrowserQuery }): ReactElement {
  const search = route.useSearch();
  const navigate = route.useNavigate();
  return (
    <aside aria-label="视图树">
      <Tabs
        activeKey={search.tree_view ?? "format"}
        onChange={(value) => {
          void navigate({
            search: {
              ...search,
              tree_view: value === "task" ? "task" : "format",
              entry_path: undefined,
              offset: undefined,
            },
          });
        }}
        items={[
          { key: "format", label: "按格式" },
          { key: "task", label: "按任务" },
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
            if (node?.entry_path)
              void navigate({ search: { ...search, selected: node.entry_path } });
            else
              void navigate({
                search: { ...search, selected: undefined, entry_path: path, offset: undefined },
              });
          }}
        />
      )}
    </aside>
  );
}

// 连续详情替换列表，与确认原型 A 一致；返回和跨视图不丢失筛选。
function BrowserMain({ query }: { query: BrowserQuery }): ReactElement {
  const search = route.useSearch();
  const navigate = route.useNavigate();
  if (search.selected)
    return (
      <DatasetDetails
        key={search.selected}
        entryPath={search.selected}
        onClose={() => {
          void navigate({ search: { ...search, selected: undefined } });
        }}
        onJump={(entry) => {
          void navigate({
            search: {
              ...search,
              selected: entry.entry_path,
              tree_view: entry.view,
              entry_path: undefined,
              offset: undefined,
            },
          });
        }}
      />
    );
  return (
    <>
      {query.list.error && <DiagnosticCard failure={toFailureView(query.list.error)} />}
      {query.list.isPending && <p role="status">正在加载数据集</p>}
      {query.list.data && (
        <DatasetListTable
          data={query.list.data}
          onOpen={(selected) => {
            void navigate({ search: { ...search, selected } });
          }}
          onPage={(offset) => {
            void navigate({ search: { ...search, offset } });
          }}
        />
      )}
    </>
  );
}
