// 三种布局共用的浏览状态与操作（M1-05）：筛选、选中入口、视图、面板都在 URL，布局只决定排布。
import type { ReactElement } from "react";
import { getRouteApi } from "@tanstack/react-router";
import type { DatasetDetail } from "../api/datasets";
import { DiagnosticCard } from "../DiagnosticCard";
import { toFailureView } from "../api/problems";
import { DatasetFilterBar } from "./Filters";
import { ConsistencyPanel } from "./Consistency";
import type { useDatasetBrowser } from "./queries";
import type { components } from "../api/schema";

/** 数据集路由；所有布局读写同一份 search，切换布局不会丢状态。 */
export const datasetRoute = getRouteApi("/datasets");
/** 共用查询的结果，由页面外层持有，切换布局时不重新请求。 */
export type BrowserQuery = ReturnType<typeof useDatasetBrowser>;

/**
 * 提供三种布局共用的导航动作，保证同一个操作在各布局下写入同样的 URL 参数。
 * @returns search 当前条件；select、close、jump、openDirectory、setView、togglePanel 修改 URL。
 * @throws 无。
 * @sideEffects 调用路由导航，保留未被动作改动的筛选；目录与视图切换会清除分页偏移。
 * @timeSemantics 同步写 URL，不等待数据。
 */
export function useBrowserActions() {
  const search = datasetRoute.useSearch();
  const navigate = datasetRoute.useNavigate();
  return {
    search,
    // 打开某个入口的详情，保留筛选。
    select: (entryPath: string) => void navigate({ search: { ...search, selected: entryPath } }),
    // 关闭详情，只清选中项。
    close: () => void navigate({ search: { ...search, selected: undefined } }),
    // 跨视图跳转：换到目标入口所在视图，筛选不变。
    jump: (entry: DatasetDetail["entry"]) =>
      void navigate({
        search: {
          ...search,
          selected: entry.entry_path,
          tree_view: entry.view,
          entry_path: undefined,
          offset: undefined,
        },
      }),
    // 进入目录：目录只筛选列表，不打开详情。
    openDirectory: (path: string, view?: components["schemas"]["DatasetTreeNode"]["view"]) =>
      void navigate({
        search: {
          ...search,
          selected: undefined,
          entry_path: path,
          offset: undefined,
          tree_view: view ?? search.tree_view,
        },
      }),
    // 回到导航层根：清目录和选中项，筛选保留。
    clearLocation: () =>
      void navigate({
        search: { ...search, selected: undefined, entry_path: undefined, offset: undefined },
      }),
    // 换视图树：清掉目录与分页，选中项保留。
    setView: (view: "task" | "format" | "scene") =>
      void navigate({
        search: { ...search, tree_view: view, entry_path: undefined, offset: undefined },
      }),
    // 列表翻页，条件不变。
    setPage: (offset: number) => void navigate({ search: { ...search, offset } }),
    // 打开或收起一致性面板。
    togglePanel: () => void navigate({ search: { ...search, panel: !search.panel } }),
  };
}

/**
 * 筛选栏，候选来自全局，不随当前筛选缩小，否则用户无法解除或更换筛选。
 * @param props - 共用查询结果。
 * @param props.query - 页面外层持有的共用查询。
 * @returns 候选读取失败时的诊断，加载后的筛选栏。
 * @throws 无。
 * @sideEffects 用户更改条件时写 URL。
 * @timeSemantics 候选为索引快照，不轮询。
 */
export function BrowserFilters({ query }: { query: BrowserQuery }): ReactElement {
  const search = datasetRoute.useSearch();
  const navigate = datasetRoute.useNavigate();
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

/**
 * 一致性面板内容；只显示最近索引发现，加载中或失败不伪装成无问题。
 * @param props - 共用查询结果。
 * @param props.query - 页面外层持有的共用查询。
 * @returns 加载提示或面板。
 * @throws 无。
 * @sideEffects 无。
 * @timeSemantics 最近一次索引扫描，不实时探测磁盘。
 */
export function BrowserPanel({ query }: { query: BrowserQuery }): ReactElement {
  return (
    <>
      {query.panel.isPending && <p role="status">正在加载面板</p>}
      {query.panel.data && <ConsistencyPanel data={query.panel.data} />}
    </>
  );
}
