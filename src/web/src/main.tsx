// 浏览器启动边界（工单 02）；只组装 React、QueryClientProvider 与 RouterProvider。

/**
 * 将应用挂载到页面容器。
 *
 * @param container - index.html 中的 root 元素，无单位；null 表示入口 HTML 不完整。
 * @returns 无。
 * @throws Error container 为 null 时同步报错，不尝试挂载。
 * @sideEffects 创建 React 根及独立 QueryClient，在容器内渲染路由，页面可发起健康请求。
 * @timeSemantics 每次页面加载只调用一次；查询缓存和超时遵循 useHealth 的契约。
 */
// eslint-disable-next-line @typescript-eslint/no-unused-vars -- A2 契约桩不使用参数；B 实现函数后删除此豁免。
export function mountWeb(container: HTMLElement | null): void {
  throw new Error("未实现");
}

mountWeb(document.getElementById("root"));
