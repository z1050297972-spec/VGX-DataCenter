// 第09、15张的信息项定位；服务端标签由 number+name 生成，只有精确匹配时才把结构化输入放入正文行。
// 共用映射保证正文行与独立后备位置互斥，不从 Markdown 内容猜测字段位置。
/** 顶层字段对应的信息项标签；不在表中的字段保持独立位置。 */
export const INFORMATION_FIELD_ROWS: Readonly<Record<string, string>> = {
  robot_model: "第 5 项：采集机器人型号",
  scene: "第 6 项：任务与场景",
  tasks: "第 6 项：任务与场景",
  fps: "第 8 项：FPS",
  data_origin: "第 3 项：类型与组成",
};
