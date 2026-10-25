// 账号页面骨架（06）：采用 antd 与 TanStack Router/Query；错误统一用 DiagnosticCard，秘密只在表单内存。
import type { ReactElement } from "react";
import { Card } from "antd";

/**
 * 登录名和口令表单；成功后按必须改密标记转改密页，否则回 safeReturnTo；已登录者不重复显示登录表单。401/403/422/429/网络失败均显示 DiagnosticCard，429 展示安全倒计时，不区分未知账号与错口令。
 *
 * @returns 使用 antd 的页面；骨架阶段只渲染占位，行为由跳过测试登记。
 * @throws 无。请求错误经 toFailureView/DiagnosticCard 呈现，不展示原始异常或执行服务端 HTML。
 * @sideEffects 仅提交时调用 login；未登录不加载受保护内容；口令在任何结束路径清空，不进入 URL、日志、缓存或浏览器存储。
 * @timeSemantics 请求上限 ACCOUNT_TIMEOUT_MS；切页/卸载取消请求和倒计时，忽略迟到结果，无自动重试。
 */
export function LoginPage(): ReactElement {
  return <Card title="登录">待实现</Card>;
}

/**
 * 本人当前/新口令与确认表单；强制改密者不能绕过，成功后回安全目的地；旧口令错误400提示“当前口令不正确”并留在本页，第五次429；真实401仍跳登录，错误统一用 DiagnosticCard。
 *
 * @returns 使用 antd 的页面；骨架阶段只渲染占位，行为由跳过测试登记。
 * @throws 无。请求错误经 toFailureView/DiagnosticCard 呈现，不展示原始异常或执行服务端 HTML。
 * @sideEffects 提交 changePassword，成功刷新身份；任何结束路径清空秘密；不因超时声称服务端已回滚。
 * @timeSemantics 请求上限 ACCOUNT_TIMEOUT_MS；切页/卸载取消请求和倒计时，忽略迟到结果，无自动重试。
 */
export function PasswordPage(): ReactElement {
  return <Card title="修改口令">待实现</Card>;
}

/**
 * 管理员分页账号列表、新建、改角色、启停、重置口令、删除。停用和删除均用 antd Modal 二次确认，取消不发请求；403/404/409/422/429/网络错误用 DiagnosticCard，失败保留原列表。
 *
 * @returns 使用 antd 的页面；骨架阶段只渲染占位，行为由跳过测试登记。
 * @throws 无。请求错误经 toFailureView/DiagnosticCard 呈现，不展示原始异常或执行服务端 HTML。
 * @sideEffects 通过生成类型的 accounts API 操作；写成功才刷新列表，不乐观删除；新建/重置口令只在表单内存，结束后清除。
 * @timeSemantics 请求上限 ACCOUNT_TIMEOUT_MS；切页/卸载取消请求和倒计时，忽略迟到结果，无自动重试。
 */
export function AccountsPage(): ReactElement {
  return <Card title="账号管理">待实现</Card>;
}

/**
 * 在右上角显示当前显示名、角色、改口令入口和登出；管理员额外显示账号管理入口，成员不显示。
 *
 * @returns 使用 antd 的页面；骨架阶段只渲染占位，行为由跳过测试登记。
 * @throws 无。请求错误经 toFailureView/DiagnosticCard 呈现，不展示原始异常或执行服务端 HTML。
 * @sideEffects 订阅共享的内存身份查询，设置 refetchOnWindowFocus: true、staleTime: 0；切回窗口重新查 /api/auth/me，401 统一清缓存并跳登录；登出成功或 401 才清缓存去登录页，网络失败显示 DiagnosticCard，不假装退出。
 * @timeSemantics 请求上限 ACCOUNT_TIMEOUT_MS；切页/卸载取消请求和倒计时，忽略迟到结果，无自动重试。
 */
export function AccountMenu(): ReactElement {
  return <Card title="当前账号">待实现</Card>;
}

/**
 * 提供右上角 AccountMenu 和受保护页面 Outlet；身份未知时显示加载状态，不闪现受保护内容。
 *
 * @returns 使用 antd 的页面；骨架阶段只渲染占位，行为由跳过测试登记。
 * @throws 无。请求错误经 toFailureView/DiagnosticCard 呈现，不展示原始异常或执行服务端 HTML。
 * @sideEffects 由 guardAccountRoute 完成进入前鉴权，并保持一份活跃身份 Query（refetchOnWindowFocus: true、staleTime: 0）；
 * 成员被停用后，切回窗口立即重新查 /api/auth/me，收到 401 就清缓存并跳登录；任何其他 API 的 401 同样统一 handleUnauthorized。
 * 不使用定时轮询；空闲且不切回窗口时不承诺无请求自动跳转。骨架暂不替换现有根布局。
 * @timeSemantics 请求上限 ACCOUNT_TIMEOUT_MS；切页/卸载取消请求和倒计时，忽略迟到结果，无自动重试。
 */
export function AccountLayout(): ReactElement {
  return <Card title="账号页面">待实现</Card>;
}
