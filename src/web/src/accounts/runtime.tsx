// 账号页面的应用依赖和内存身份查询；不存储密码或读取 cookie。
import { createContext, useContext, type ReactElement, type ReactNode } from "react";
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import type { HealthClient } from "../api/client";
import {
  fetchCurrentAccount,
  ACCOUNT_GC_TIME_MS,
  ACCOUNT_STALE_TIME_MS,
  type Account,
} from "../api/accounts";

const ClientContext = createContext<HealthClient | null>(null);
/** 当前应用的身份查询键；登出清空整个 QueryClient，不能跨账号复用。 */
export const ACCOUNT_QUERY_KEY = ["current-account"] as const;

/** 页面依赖属性，不含 cookie 或密码。 */
interface ClientProviderProps {
  /** 必填的类型化同源客户端。 */
  client: HealthClient;
  /** 受此客户端约束的 React 子树。 */
  children: ReactNode;
}
/**
 * 向页面提供当前应用的账号感知客户端。
 * @param props - 稳定客户端和子树，不可为空。
 * @returns React 上下文提供器。
 * @throws 无。
 * @sideEffects 无；不请求或持久化数据。
 * @timeSemantics 同步渲染，无等待。
 */
export function AccountClientProvider(props: ClientProviderProps): ReactElement {
  return <ClientContext.Provider value={props.client}>{props.children}</ClientContext.Provider>;
}
/**
 * 读取应用注入的 HTTP 客户端。
 * @returns 当前应用独立客户端。
 * @throws Error 不在 AccountClientProvider 内属于装配错误。
 * @sideEffects 无。
 * @timeSemantics 同步，无等待。
 */
export function useAccountClient(): HealthClient {
  const client = useContext(ClientContext);
  if (!client) throw new Error("账号客户端未装配");
  return client;
}
/**
 * 保持页面活跃期间的可取消身份查询。
 * @returns 当前身份、加载状态或安全失败，使用生成的 Account 类型。
 * @throws 无；查询失败保存在返回值，要求位于两个应用 Provider 中。
 * @sideEffects 发起 /me 查询，聚焦时重查；401 由客户端统一通知导航，缓存仅在内存。
 * @timeSemantics staleTime/gcTime 为 0，refetchOnWindowFocus 为 true，无轮询或自动重试。
 */
export function useCurrentAccount(): UseQueryResult<Account> {
  const client = useAccountClient();
  return useQuery({
    queryKey: ACCOUNT_QUERY_KEY,
    queryFn: ({ signal }) => fetchCurrentAccount({ client, signal, payload: undefined }),
    staleTime: ACCOUNT_STALE_TIME_MS,
    gcTime: ACCOUNT_GC_TIME_MS,
    retry: false,
    refetchOnWindowFocus: true,
    refetchInterval: false,
  });
}
