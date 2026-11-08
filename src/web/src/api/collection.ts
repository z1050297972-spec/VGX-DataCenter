// 机器人和采集词表的 HTTP 边界；复用账号客户端的鉴权、统一诊断和有界请求。
import { boundedRequest } from "./_request";
import { ACCOUNT_TIMEOUT_MS, type AccountCall } from "./accounts";
import { toFailureView } from "./problems";
import type { components } from "./schema";

/** 历史身份沿用作业提交人的生成模型。 */
export type HistoricalActor = components["schemas"]["HistoricalActorResponse"];
/** 登记对象的状态以服务端枚举为准。 */
export type RegistryStatus = components["schemas"]["RegistryStatus"];
/** 采集方式允许的数据来源，不包含开源下载和未知。 */
export type DataOrigin = components["schemas"]["CollectionOrigin"];
/** 机器人可编辑字段，保留生成模型的可选项和默认值语义。 */
export type RobotInput = components["schemas"]["RobotInput"];
/** 完整机器人登记，平台编号为整数。 */
export type Robot = components["schemas"]["RobotResponse"];
/** 包含停用项的机器人列表。 */
export type Robots = components["schemas"]["RobotsResponse"];
/** 已登记及数据集索引中的型号候选。 */
export type RobotModels = components["schemas"]["ModelOptionsResponse"];
/** 用途可编辑字段。 */
export type PurposeInput = components["schemas"]["PurposeInput"];
/** 采集方式可编辑字段。 */
export type MethodInput = components["schemas"]["MethodInput"];
/** 用途登记及历史身份。 */
export type Purpose = components["schemas"]["PurposeResponse"];
/** 采集方式登记及其对应来源。 */
export type Method = components["schemas"]["MethodResponse"];
/** 两个词表的完整响应。 */
export type Vocabulary = components["schemas"]["VocabularyResponse"];
/** 管理页的页签名直接取词表响应的字段名。 */
export type VocabularyKind = keyof Vocabulary;
/** 共用行操作接受任意一种词表项。 */
export type Term = Method | Purpose;

/**
 * 读取包含停用项的机器人登记列表。
 * @param input - 客户端、取消信号和空载荷。
 * @returns 按编号升序的机器人列表。
 * @throws Error 请求失败或缺少响应，交统一诊断。
 * @sideEffects 发送一次 GET /api/robots。
 * @timeSemantics 上限 ACCOUNT_TIMEOUT_MS，无重试。
 */
export function listRobots(input: AccountCall): Promise<Robots> {
  return boundedRequest(input.signal, ACCOUNT_TIMEOUT_MS, async (signal) =>
    required((await input.client.GET("/api/robots", { signal })).data),
  );
}
/**
 * 读取数据集与已登记机器人的型号候选。
 * @param input - 客户端、取消信号和空载荷。
 * @returns 去重排序的型号文本列表，可为空。
 * @throws Error 请求失败或缺少响应。
 * @sideEffects 发送一次 GET /api/robots/model-options。
 * @timeSemantics 上限 ACCOUNT_TIMEOUT_MS，无轮询。
 */
export function listRobotModels(input: AccountCall): Promise<RobotModels> {
  return boundedRequest(input.signal, ACCOUNT_TIMEOUT_MS, async (signal) =>
    required((await input.client.GET("/api/robots/model-options", { signal })).data),
  );
}
/**
 * 保存新机器人或修改已有登记。
 * @param input - RobotInput 载荷；id 为 null 表示新建，否则为正整数编号。
 * @returns 服务端规范化后的机器人。
 * @throws Error 字段、重复值、权限或传输错误，保留服务端诊断。
 * @sideEffects 发送一次 POST 或 PUT，服务端登记操作日志。
 * @timeSemantics 上限 ACCOUNT_TIMEOUT_MS，失败不自动重试。
 */
export function saveRobot(input: AccountCall<RobotInput> & { id: number | null }): Promise<Robot> {
  return boundedRequest(input.signal, ACCOUNT_TIMEOUT_MS, async (signal) => {
    const client = input.client;
    const response =
      input.id === null
        ? await client.POST("/api/robots", { body: input.payload, signal })
        : await client.PUT("/api/robots/{robot_id}", {
            params: { path: { robot_id: input.id } },
            body: input.payload,
            signal,
          });
    return required(response.data);
  });
}
/**
 * 读取两个采集词表，保留停用项。
 * @param input - 客户端、取消信号和空载荷。
 * @returns 各自按编号升序的采集方式和用途。
 * @throws Error 请求失败或缺少响应。
 * @sideEffects 发送一次 GET /api/collection-vocabulary。
 * @timeSemantics 上限 ACCOUNT_TIMEOUT_MS，无重试。
 */
export function listVocabulary(input: AccountCall): Promise<Vocabulary> {
  return boundedRequest(input.signal, ACCOUNT_TIMEOUT_MS, async (signal) =>
    required((await input.client.GET("/api/collection-vocabulary", { signal })).data),
  );
}
/**
 * 保存词表名称及采集方式的数据来源。
 * @param input - 词表、正整数编号或新建用 null；采集方式载荷必须包含来源。
 * @returns 请求完成，无额外页面状态。
 * @throws Error 重名、字段或传输错误，交统一诊断。
 * @sideEffects 发送一次 POST 或 PUT；成功后由页面刷新词表。
 * @timeSemantics 上限 ACCOUNT_TIMEOUT_MS，无自动重试。
 */
export function saveTerm(
  input: AccountCall & { id: number | null } & (
      { kind: "methods"; values: MethodInput } | { kind: "purposes"; values: PurposeInput }
    ),
): Promise<void> {
  return boundedRequest(input.signal, ACCOUNT_TIMEOUT_MS, async (signal) => {
    const client = input.client;
    if (input.kind === "methods") {
      if (input.id === null)
        await client.POST("/api/collection-vocabulary/methods", { body: input.values, signal });
      else
        await client.PUT("/api/collection-vocabulary/methods/{id}", {
          body: input.values,
          params: { path: { id: input.id } },
          signal,
        });
    } else if (input.id === null)
      await client.POST("/api/collection-vocabulary/purposes", { body: input.values, signal });
    else
      await client.PUT("/api/collection-vocabulary/purposes/{id}", {
        body: input.values,
        params: { path: { id: input.id } },
        signal,
      });
  });
}
/**
 * 停用、恢复或删除一条登记记录。
 * @param input - robots、methods 或 purposes；正整数编号及操作名称。
 * @returns 操作完成，不乐观删除页面行。
 * @throws Error 被引用不能删除、记录不存在或传输错误。
 * @sideEffects 发送一次 POST 状态操作或 DELETE，服务端写操作日志。
 * @timeSemantics 上限 ACCOUNT_TIMEOUT_MS，取消不表示服务端回滚。
 */
export function changeRegistry(
  input: AccountCall & {
    kind: "robots" | VocabularyKind;
    id: number;
    action: "retire" | "restore" | "delete";
  },
): Promise<void> {
  return boundedRequest(input.signal, ACCOUNT_TIMEOUT_MS, async (signal) => {
    const client = input.client;
    if (input.kind === "robots") {
      const options = { params: { path: { robot_id: input.id } }, signal };
      if (input.action === "delete") await client.DELETE("/api/robots/{robot_id}", options);
      else await client.POST(`/api/robots/{robot_id}/${input.action}`, options);
    } else {
      const path = `/api/collection-vocabulary/${input.kind}/{id}` as const;
      const options = { params: { path: { id: input.id } }, signal };
      if (input.action === "delete") await client.DELETE(path, options);
      else await client.POST(`${path}/${input.action}`, options);
    }
  });
}

// HTTP 错误已由统一传输抛出；空成功体使用现有安全失败格式。
function required<T>(value: T | undefined): T {
  if (value === undefined) throw new Error("请求失败", { cause: toFailureView(null) });
  return value;
}
