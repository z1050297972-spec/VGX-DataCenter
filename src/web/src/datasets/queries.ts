// 数据集查询状态（M1-04）；使用现有 Query 的取消与账号生命周期，不维护第二套缓存。
import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useAccountClient, useCurrentAccount } from "../accounts/runtime";
import {
  DATASET_STALE_TIME_MS,
  DATASET_GC_TIME_MS,
  getDatasetLayout,
  getDatasetPanel,
  setDatasetLayout,
  type DatasetLayout,
  getDatasetDetail,
  getDatasetFilters,
  getDatasetTrees,
  listDatasets,
  type DatasetQuery,
} from "../api/datasets";

/**
 * 订阅同一筛选下的列表及两棵树。
 * @param filters - 生成接口类型约束的筛选及分页。
 * @returns 列表、树、候选和面板四个独立查询，任一失败仍可展示其他项。
 * @throws Error 缺少账号 Provider；请求错误保留在查询 error。
 * @sideEffects 经账号客户端发列表和树 GET，key 含账号；不改 URL。
 * @timeSemantics 进入或参数变化时读取，立即失效、离页清除，不轮询、不重试；卸载取消请求。
 */
export function useDatasetBrowser(filters: DatasetQuery) {
  const client = useAccountClient();
  const identity = useCurrentAccount();
  const options = {
    retry: false,
    staleTime: DATASET_STALE_TIME_MS,
    gcTime: DATASET_GC_TIME_MS,
    refetchOnWindowFocus: false,
  } as const;
  const treeFilters = {
    robot_type: filters.robot_type,
    robot_model_id: filters.robot_model_id,
    data_origin: filters.data_origin,
    fps: filters.fps,
    // 不传 entry_path：目录选择只筛列表。树若按目录收窄，另一个视图和上级目录的数量会变成 0，无法再走回去。
  };
  return {
    panel: useQuery({
      ...options,
      queryKey: ["datasets", identity.data?.account_id, "panel"],
      queryFn: ({ signal }) => getDatasetPanel({ client, payload: undefined, signal }),
    }),
    filters: useQuery({
      ...options,
      queryKey: ["datasets", identity.data?.account_id, "filters"],
      queryFn: ({ signal }) => getDatasetFilters({ client, payload: undefined, signal }),
    }),
    list: useQuery({
      ...options,
      queryKey: ["datasets", identity.data?.account_id, "list", filters],
      queryFn: ({ signal }) => listDatasets({ client, payload: filters, signal }),
    }),
    trees: useQuery({
      ...options,
      queryKey: ["datasets", identity.data?.account_id, "trees", treeFilters],
      queryFn: ({ signal }) => getDatasetTrees({ client, payload: treeFilters, signal }),
    }),
  };
}

/**
 * 订阅当前入口详情，取消前一个入口的请求。
 * @param entryPath - 已选中的相对入口路径。
 * @returns 详情查询状态，失败时不伪造空详情。
 * @throws Error 缺少 Provider；服务端故障在 error 中返回。
 * @sideEffects 通过账号客户端读详情，缓存按账号及入口隔离。
 * @timeSemantics 进入及切换入口现场读取，不轮询；离页清缓存并取消请求，不重试。
 */
export function useDatasetDetail(entryPath: string) {
  const client = useAccountClient();
  const identity = useCurrentAccount();
  return useQuery({
    queryKey: ["datasets", identity.data?.account_id, "detail", entryPath],
    queryFn: ({ signal }) => getDatasetDetail({ client, payload: entryPath, signal }),
    retry: false,
    staleTime: DATASET_STALE_TIME_MS,
    gcTime: DATASET_GC_TIME_MS,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
}

/** 读取失败或尚未读到时使用的布局，与服务端“无偏好行”时的返回一致。 */
export const DEFAULT_DATASET_LAYOUT: DatasetLayout = "A";

/**
 * 读取并保存当前账号的数据集布局偏好。
 * @returns layout 当前应显示的布局；pending 表示尚未读到偏好；loadError、saveError 分别是读取和保存的失败；choose 切换并保存。
 * @throws Error 缺少账号 Provider；请求错误保留在 loadError、saveError，不抛出。
 * @sideEffects 挂载时 GET 一次；choose 立即切换显示并 PUT 保存，保存失败不回退本次选择。
 * @timeSemantics 读取立即失效、离页清除，不轮询、不重试；会话内本地选择优先于已读到的值，避免保存往返期间界面跳回；保存请求不随卸载取消，页面离开后仍会到达服务端。
 */
export function useDatasetLayout() {
  const client = useAccountClient();
  const identity = useCurrentAccount();
  const [chosen, setChosen] = useState<DatasetLayout | undefined>(undefined);
  const load = useQuery({
    queryKey: ["datasets", identity.data?.account_id, "layout"],
    queryFn: ({ signal }) => getDatasetLayout({ client, payload: undefined, signal }),
    retry: false,
    staleTime: DATASET_STALE_TIME_MS,
    gcTime: DATASET_GC_TIME_MS,
    refetchOnWindowFocus: false,
  });
  const save = useMutation({
    mutationFn: (layout: DatasetLayout) =>
      setDatasetLayout({ client, payload: layout, signal: new AbortController().signal }),
    retry: false,
  });
  return {
    layout: chosen ?? load.data ?? DEFAULT_DATASET_LAYOUT,
    pending: chosen === undefined && load.isPending,
    loadError: chosen === undefined ? load.error : null,
    saveError: save.error,
    choose: (layout: DatasetLayout) => {
      setChosen(layout);
      save.mutate(layout);
    },
  };
}
