// 存储根传输契约清单（10）；请求只经账号客户端与生成OpenAPI类型。
import { describe, it } from "vitest";

describe("存储根传输", () => {
  // 验证稳定相对接口与完整响应类型，不手写重复字段模型。
  it.skip("getStorageRoots经openapi-fetch发送一次GET并返回生成的StorageRoots类型");
  // 验证请求超时独立于worker的可配置访问预算，取消不会重试。
  it.skip("十秒上限、外部取消和网络失败交统一诊断，无自动重试");
  // 验证缺响应体属于传输失败，禁止制造空根列表。
  it.skip("成功响应缺data仍报错，401/403/502/500保留统一身份和诊断行为");
  // 验证默认传输不被作为对象方法错误绑定this，覆盖已有评审回归。
  it.skip("默认fetch按浏览器this约束调用，响应无UUID、NFS来源或挂载表原文");
});
