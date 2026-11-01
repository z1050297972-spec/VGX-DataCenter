// 测试环境适配（工单 02）：jsdom 没有 Request，Vitest 使用的 Node Request 不接受相对 URL。
// 只补齐浏览器按 document.baseURI 解析 URL 的行为；传输由测试替身处理，不访问真实网络。
// jsdom 提供浏览器 Request 后可删除此适配；本模块仅由 Vitest 加载，不进入生产入口。
import { afterEach, beforeEach, vi } from "vitest";
import { configure } from "@testing-library/react";

// 工单13：页面并行加载在高负载机器上可能超过默认1秒；所有findBy/waitFor统一给5秒。
configure({ asyncUtilTimeout: 5000 });

const NativeRequest = Request;

class BrowserRequest extends NativeRequest {
  constructor(input: RequestInfo | URL, init?: RequestInit) {
    super(typeof input === "string" ? new URL(input, document.baseURI) : input, init);
  }
}

// jsdom 没有 ResizeObserver；Ant Design 表格设了 scroll 以后会用它监听容器宽度（M1-05 起所有页面表格都在自己的容器里横向滚动）。
// 只补空实现，不模拟尺寸变化；真实浏览器自带。
class SilentResizeObserver {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

beforeEach(() => {
  vi.stubGlobal("Request", BrowserRequest);
  vi.stubGlobal("ResizeObserver", SilentResizeObserver);
  // jsdom 无布局引擎；路由滚动不是本票的测试对象，仅补齐浏览器方法，不隐藏请求或渲染错误。
  vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
});

afterEach(() => {
  vi.unstubAllGlobals();
});
