// 日志 Query/Mutation 契约：共享第 6 张的客户端上下文和账号切换清理，不复制传输实现。
import type { UseMutationResult, UseQueryResult } from "@tanstack/react-query";
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
// eslint-disable-next-line @typescript-eslint/no-unused-vars -- 参数由调用契约要求，函数当前只抛错；开始使用该参数后删除此豁免。
export function useOperationLogs(_search: OperationSearch): UseQueryResult<OperationLogPage> {
  throw new Error("未实现");
}

/**
 * 为当前管理员加载登录日志。
 * @param _search - 登录日志路由的类型化 search，包含全部筛选和可选游标。
 * @returns Query 页数据或安全错误；空页正常，末页无下一页按钮。
 * @throws Error Provider 缺失；请求失败保留在结果供 DiagnosticCard 显示。
 * @sideEffects 同源列表请求，queryKey 与操作日志隔离；身份切换由现有客户端取消并清空，旧响应不得污染新身份。
 * @timeSemantics 缓存 staleTime/gcTime 为 0，聚焦重查，不轮询、不重试；10 秒上限和调用方取消信号共同生效。
 */
// eslint-disable-next-line @typescript-eslint/no-unused-vars -- 参数由调用契约要求，函数当前只抛错；开始使用该参数后删除此豁免。
export function useLoginLogs(_search: LoginSearch): UseQueryResult<LoginLogPage> {
  throw new Error("未实现");
}

/**
 * 读取共同保留期供操作日志设置表单使用。
 * @returns Query 的 days、加载或失败状态；失败不默认为 30。
 * @throws Error Provider 缺失；网络/服务错误由 Query 返回。
 * @sideEffects 调用 getAuditRetention，不写数据库或 URL；仅管理员页面启用。
 * @timeSemantics staleTime/gcTime=0，聚焦重查，10 秒请求上限，不轮询、不重试。
 */
export function useAuditRetention(): UseQueryResult<AuditRetention> {
  throw new Error("未实现");
}

/**
 * 保存保留期并在确认成功后刷新相关视图。
 * @returns Mutation，变量和结果均为生成的 AuditRetention；错误保留供 DiagnosticCard。
 * @throws Error Provider 缺失；提交失败通过 mutation.error，不冒充成功。
 * @sideEffects 调用 setAuditRetention；成功使所有保留期/操作日志筛选缓存失效，回到操作日志首页；不乐观清除旧记录，失败保留表单与原列表。
 * @timeSemantics 无自动重试，10 秒上限，离页取消；不声明取消或超时必然回滚服务端事务。
 */
export function useSetAuditRetention(): UseMutationResult<AuditRetention, Error, AuditRetention> {
  throw new Error("未实现");
}
