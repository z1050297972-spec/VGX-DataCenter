// 存储根只读页面（10、L3）：成员与管理员相同，不提供配置编辑或文件访问入口。
import type { ReactElement } from "react";

/**
 * 展示登记根的许可、挂载状态与检查时间。
 * @returns Ant Design 表格，含名字、路径、只读或可写、在线或离线原因、浏览器本地检查时间；空列表显示未登记存储根。
 * @throws 无；请求失败交 DiagnosticCard，不能把失败显示成没挂载。
 * @sideEffects 调用 useStorageRoots，打开页面检查一次；重新检查按钮在请求中禁用；不写配置，不改变 URL search。
 * @timeSemantics 不轮询；等待时显示加载状态，失败保留上次数据和旧时刻并提示失败，不把旧结果标成新检查。
 * 原因逐项显示为“没挂载”“挂错了盘”“超时”；说明本页只核对挂载身份，访问超时只能由作业检查发现。
 */
export function StorageRootsPage(): ReactElement {
  throw new Error("NotImplementedError");
}
