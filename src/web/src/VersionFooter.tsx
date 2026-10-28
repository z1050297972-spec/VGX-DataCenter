// 登录后布局底部的版本显示（11 M2），复用版本查询；不暴露本机路径，不自行推断 git 信息。
import type { ReactElement } from "react";
import type { HealthClient } from "./api/client";

/** 版本组件输入；认证后的共享客户端由布局传入。 */
export interface VersionFooterProps {
  /** 类型化同源客户端，身份保持稳定；不创建独立登录会话。 */
  client: HealthClient;
}

/**
 * 在已登录页面底部展示当前服务版本。
 * @param _props - 包含共享客户端，不接收人工拼接的版本字符串。
 * @returns footer 元素；成功显示与 rdp --version 逐字一致的文字，加载显示“版本加载中”，失败显示“版本暂不可用”。
 * @throws 无；请求故障转为组件状态，不妨碍页面业务。
 * @sideEffects 通过 usePlatformVersion 发起只读请求；不记录日志、不修改导航状态。
 * @timeSemantics 沿用查询缓存和取消语义；登录、强制改密页面不挂载，避免为版本查询制造认证错误。
 */
// eslint-disable-next-line @typescript-eslint/no-unused-vars -- 仅抛异常的契约函数保留调用参数；函数使用参数后删除。
export function VersionFooter(_props: VersionFooterProps): ReactElement {
  throw new Error("NotImplementedError");
}
