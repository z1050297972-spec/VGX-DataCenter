// 健康展示组件（工单 02）；不包含传输实现、业务权限或数据库状态。
import type { ReactElement } from "react";
import type { HealthClient } from "./api/client";

/** 页面输入不含物理量；依赖可注入，避免测试修改全局 fetch。 */
export interface HealthPageProps {
  /** 可选的稳定客户端，无单位；未提供时页面创建并复用默认客户端。 */
  client?: HealthClient;
}

// 权宜：统一诊断组件尚未交付；M0 日志和报错框架就绪后用其替代失败 Alert。
/**
 * 用 Ant Design 展示后端健康查询结果。
 *
 * @param props - 页面属性，无单位；可为空对象，字段约束见 HealthPageProps。
 * @returns 加载提示、成功文字“后端正常”或请求失败的 Alert；失败时不保留成功提示。
 * @throws 无。请求错误经 useHealth 转为 Alert；必须在 QueryClientProvider 内渲染。
 * @sideEffects 经 useHealth 请求 /api/health，不修改 URL、浏览器存储或全局 fetch。
 * @timeSemantics 沿用 HEALTH_STALE_TIME_MS 的缓存和 HEALTH_TIMEOUT_MS 的超时，无额外轮询。
 */
// eslint-disable-next-line @typescript-eslint/no-unused-vars -- A2 契约桩不使用参数；B 实现函数后删除此豁免。
export function HealthPage(props: HealthPageProps = {}): ReactElement {
  throw new Error("未实现");
}
