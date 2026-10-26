// 管理员日志页面契约（07）：antd 只读表格、TanStack Router 类型化 search 和 Query 数据状态。
// 历史名字和明细只做安全文本展示，页面不提供修改单条记录的入口。
import type { ReactElement } from "react";

/**
 * 显示管理员操作日志、筛选和共同保留期设置。
 * @returns antd 的倒序只读表格、类型化时间/操作人账号/对象账号/操作/结果筛选、游标翻页和 7-365 天设置表单；无单条编辑/删除入口。actor/target.deleted 显示“名字（已删除）”，不按同名新账号改写旧记录；空来源显示“未知”，运维显示“运维”。
 * @throws 无；查询/保存失败用 DiagnosticCard，服务端文字作为文本渲染。
 * @sideEffects 通过 getRouteApi("/audit/operations").useSearch 与 useNavigate 的 typed search 管理筛选；“操作人”绑定 account_id，“对象账号”绑定 target_account_id，可独立清空并同时取交集；改任一筛选清 cursor，翻页用 next_cursor。用 useOperationLogs/useAuditRetention/useSetAuditRetention，来源为既有账号感知客户端；成员不加载日志或设置，管理员菜单才有入口。
 * @timeSemantics 显示时转浏览器本地时间，提交时带偏移并转 UTC；缓存立即过期、离页释放、窗口聚焦重查；请求上限 10 秒、无轮询或自动重试，迟到结果不覆盖新筛选。
 */
export function OperationLogsPage(): ReactElement {
  throw new Error("未实现");
}

/**
 * 显示管理员登录日志和来源 IP。
 * @returns antd 只读表格和时间/账号/kind/result 筛选、游标翻页；未知账号只显示“账号不存在”，空 IP 显示“未知”；已删账号以历史显示名加“（已删除）”，可显示已知账号当时的登录名。
 * @throws 无；失败用统一 DiagnosticCard，不回显未知登录名或凭据。
 * @sideEffects 用 getRouteApi("/audit/logins").useSearch 读取已校验的 typed search，useNavigate 更新筛选或游标，变更筛选回首页；用 useLoginLogs，不解析 URLSearchParams、不单独创建 fetch 客户端。成员看不到菜单、无法加载页面内容或发日志查询。
 * @timeSemantics UTC 事件时间只在显示转浏览器本地；固定时间测试不修改全局时区。缓存 staleTime/gcTime=0、聚焦重查，无轮询/retry，离页取消 10 秒上限请求并忽略迟到结果。
 */
export function LoginLogsPage(): ReactElement {
  throw new Error("未实现");
}
