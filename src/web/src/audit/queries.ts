// 日志 Query/Mutation 契约：共享第 6 张的客户端上下文和账号切换清理，不复制传输实现。
import {
  useMutation,
  useQueryClient,
  useQuery,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { getRouteApi } from "@tanstack/react-router";
import { useAccountClient } from "../accounts/runtime";
import {
  listOperationLogs,
  listLoginLogs,
  getAuditRetention,
  setAuditRetention,
  AUDIT_STALE_TIME_MS,
  AUDIT_GC_TIME_MS,
} from "../api/audit";
import type {
  AuditRetention,
  LoginLogPage,
  LoginSearch,
  OperationLogPage,
  OperationSearch,
} from "../api/audit";

/**
 * 为当前管理员按类型化筛选加载操作日志。
 * @param _search - 当前操作日志路由 useSearch 的结果，必须已经 validateSearch；account_id 与 target_account_id 为独立的可选十进制文本。
 * @returns Query 的页数据、加载或错误状态，错误可交 toFailureView；不保留前一个筛选的页冒充新结果。
 * @throws Error 缺少 AccountClientProvider/QueryClientProvider 属于装配错误；请求失败存在返回值中。
 * @sideEffects 用 useAccountClient 发一次列表查询，queryKey 同时含操作人、对象账号和其余规范化筛选；变更筛选/离页取消旧请求，401 由统一客户端清缓存。
 * @timeSemantics AUDIT_STALE_TIME_MS/AUDIT_GC_TIME_MS 均 0，refetchOnWindowFocus=true，无轮询、retry=false；单请求 AUDIT_TIMEOUT_MS。
 */
export function useOperationLogs(_search: OperationSearch): UseQueryResult<OperationLogPage> {
  const client = useAccountClient();
  return useQuery({
    queryKey: ["audit", "operations", _search],
    queryFn: ({ signal }) => listOperationLogs({ client, payload: _search, signal }),
    staleTime: AUDIT_STALE_TIME_MS,
    gcTime: AUDIT_GC_TIME_MS,
    retry: false,
    refetchOnWindowFocus: true,
    refetchInterval: false,
  });
}

/**
 * 为当前管理员加载登录日志。
 * @param _search - 登录日志路由的类型化 search，包含全部筛选和可选游标。
 * @returns Query 页数据或安全错误；空页正常，末页无下一页按钮。
 * @throws Error Provider 缺失；请求失败保留在结果供 DiagnosticCard 显示。
 * @sideEffects 同源列表请求，queryKey 与操作日志隔离；身份切换由现有客户端取消并清空，旧响应不得污染新身份。
 * @timeSemantics 缓存 staleTime/gcTime 为 0，聚焦重查，不轮询、不重试；10 秒上限和调用方取消信号共同生效。
 */
export function useLoginLogs(_search: LoginSearch): UseQueryResult<LoginLogPage> {
  const client = useAccountClient();
  return useQuery({
    queryKey: ["audit", "logins", _search],
    queryFn: ({ signal }) => listLoginLogs({ client, payload: _search, signal }),
    staleTime: AUDIT_STALE_TIME_MS,
    gcTime: AUDIT_GC_TIME_MS,
    retry: false,
    refetchOnWindowFocus: true,
    refetchInterval: false,
  });
}

/**
 * 读取共同保留期供操作日志设置表单使用。
 * @returns Query 的 days、加载或失败状态；失败不默认为 30。
 * @throws Error Provider 缺失；网络/服务错误由 Query 返回。
 * @sideEffects 调用 getAuditRetention，不写数据库或 URL；仅管理员页面启用。
 * @timeSemantics staleTime/gcTime=0，聚焦重查，10 秒请求上限，不轮询、不重试。
 */
export function useAuditRetention(): UseQueryResult<AuditRetention> {
  const client = useAccountClient();
  return useQuery({
    queryKey: ["audit", "retention"],
    queryFn: ({ signal }) => getAuditRetention({ client, payload: undefined, signal }),
    staleTime: AUDIT_STALE_TIME_MS,
    gcTime: AUDIT_GC_TIME_MS,
    retry: false,
    refetchOnWindowFocus: true,
    refetchInterval: false,
  });
}

/**
 * 保存保留期并在确认成功后刷新相关视图。
 * @returns Mutation，变量和结果均为生成的 AuditRetention；错误保留供 DiagnosticCard。
 * @throws Error Provider 缺失；提交失败通过 mutation.error，不冒充成功。
 * @sideEffects 调用 setAuditRetention；成功使所有保留期/操作日志筛选缓存失效，回到操作日志首页；不乐观清除旧记录，失败保留表单与原列表。
 * @timeSemantics 无自动重试，10 秒上限，离页取消；不声明取消或超时必然回滚服务端事务。
 */
export function useSetAuditRetention(): UseMutationResult<AuditRetention, Error, AuditRetention> {
  const client = useAccountClient();
  const cache = useQueryClient();
  const navigate = getRouteApi("/audit/operations").useNavigate();
  const active = useRef<AbortController | null>(null);
  useEffect(
    () => () => {
      active.current?.abort();
    },
    [],
  );
  return useMutation({
    mutationFn: async (payload) => {
      const controller = new AbortController();
      active.current = controller;
      try {
        return await setAuditRetention({ client, payload, signal: controller.signal });
      } finally {
        if (active.current === controller) active.current = null;
      }
    },
    onSuccess: async () => {
      // 只有服务器确认成功才丢弃旧游标；先导航，避免在旧页刷新后留下游标。
      await navigate({ search: (previous) => ({ ...previous, cursor: undefined }) });
      await Promise.all([
        cache.invalidateQueries({ queryKey: ["audit", "retention"] }),
        cache.invalidateQueries({ queryKey: ["audit", "operations"] }),
      ]);
    },
    retry: false,
    gcTime: AUDIT_GC_TIME_MS,
  });
}
