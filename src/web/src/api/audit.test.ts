// 07 前端契约清单；全部使用注入传输与内存路由，按行为逐条验证。
import { it } from "vitest";

it.skip("验收1：列表只调用相对路径GET并按生成query类型发送游标，不提供单条编辑删除函数", () => {
  throw new Error("未实现");
});

it.skip("验收1：操作日志和登录日志空页及next_cursor=null正确返回，不自动全量翻页", () => {
  throw new Error("未实现");
});

it.skip("验收4：编号大于2^53仍保持文本，不回传口令、令牌、cookie或未知登录名", () => {
  throw new Error("未实现");
});

it.skip("验收5：读取保留期失败不伪造30天，PUT仅发送严格整数days", () => {
  throw new Error("未实现");
});

it.skip("验收5：写保留期成功才失效缓存，超时不宣称服务端已经回滚或自动重试", () => {
  throw new Error("未实现");
});

it.skip("验收6：两个日志接口及设置的401走账号感知客户端清缓存并导航登录", () => {
  throw new Error("未实现");
});

it.skip("验收6：403保持统一诊断，502不误判为未登录，422不回显输入值", () => {
  throw new Error("未实现");
});

it.skip("传输回归：沿用defaultFetch和createAccountClient，不把原生fetch存为对象方法导致Illegal invocation", () => {
  throw new Error("未实现");
});

it.skip("时间契约：所有四种请求最多10000毫秒，超时和取消释放计时器且忽略迟到结果", () => {
  throw new Error("未实现");
});

it.skip("诊断契约：畸形响应、网络错误和取消统一用toFailureView，不展示原始异常或HTML", () => {
  throw new Error("未实现");
});

it.skip("Origin契约：保留期PUT是同源请求并由浏览器携带Origin，不读取HttpOnly cookie", () => {
  throw new Error("未实现");
});

it.skip("修订7：OperationSearch由OpenAPI生成，account_id和target_account_id作为两个独立字符串query发送，64位编号不转Number", () => {
  throw new Error("未实现");
});

it.skip("修订7：只传对象账号可查询谁动过该账号，同时传操作人取交集，不把设置对象当账号对象", () => {
  throw new Error("未实现");
});
