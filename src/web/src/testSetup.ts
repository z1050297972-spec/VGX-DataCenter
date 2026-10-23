// 测试环境适配（工单 02）：jsdom 没有 Request，Vitest 使用的 Node Request 不接受相对 URL。
// 只补齐浏览器按 document.baseURI 解析 URL 的行为；所有传输仍由各测试显式注入，绝不替换 fetch。
// jsdom 提供浏览器 Request 后可删除此适配；本模块仅由 Vitest 加载，不进入生产入口。
import { afterEach, beforeEach, vi } from "vitest";

const NativeRequest = Request;

class BrowserRequest extends NativeRequest {
  constructor(input: RequestInfo | URL, init?: RequestInit) {
    super(typeof input === "string" ? new URL(input, document.baseURI) : input, init);
  }
}

beforeEach(() => {
  vi.stubGlobal("Request", BrowserRequest);
  // jsdom 无布局引擎；路由滚动不是本票的测试对象，仅补齐浏览器方法，不隐藏请求或渲染错误。
  vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
});

afterEach(() => {
  vi.unstubAllGlobals();
});
