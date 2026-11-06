// M1.5-12 前后端并行期间的类型桥接；生成类型更新后可移除此覆盖并直接引用 schema。
// 只覆盖载荷和响应内的 scene；query 保持原样，避免把场景筛选参数改成数组。
/** 将接口数据中的场景字段统一为数组，其余字段沿用生成契约。 */
export type SceneArrays<T> = T extends object
  ? {
      [K in keyof T]: K extends "query" ? T[K] : K extends "scene" ? string[] : SceneArrays<T[K]>;
    }
  : T;
