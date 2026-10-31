// 原文件只读HTTP边界（M1.5-01）；路径只能由已选链接和相对目录生成，不携带系统绝对路径。
import type { components, operations } from "./schema";
import type { AccountCall } from "./accounts";
import { boundedRequest } from "./_request";
import { DATASET_REQUEST_TIMEOUT_MS } from "./datasets";

export type FilePage = components["schemas"]["FilePage"];
export type FileItem = components["schemas"]["FileItem"];
export type FileQuery = NonNullable<operations["list_dataset_files"]["parameters"]["query"]>;
export interface FileLocation {
  /** 数据集永久编号。 */ datasetId: string;
  /** 规范入口登记链接名。 */ linkName: string;
  /** 相对于链接目标的路径；空串代表根。 */ path: string;
}
export interface FileListing extends FileLocation {
  /** 从零开始的目录项偏移。 */ offset: number;
}
/**
 * 读取选定链接下的一页直接目录项。
 * @param input - 账号客户端、链接位置、分页及取消信号。
 * @returns 最多100项的目录页，保留服务端has_more。
 * @throws Error 请求失败、取消、超时或响应缺失。
 * @sideEffects 发一次GET目录请求，不请求文件正文，不写存储。
 * @timeSemantics 单次最多60秒；存储实际预算由后端配置控制，不重试。
 */
export function listFiles(input: AccountCall<FileListing>): Promise<FilePage> {
  return boundedRequest(input.signal, DATASET_REQUEST_TIMEOUT_MS, async (signal) => {
    const value = input.payload;
    const result = await input.client.GET("/api/datasets/{dataset_id}/files", {
      params: {
        path: { dataset_id: value.datasetId },
        query: { link_name: value.linkName, path: value.path, offset: value.offset, limit: 100 },
      },
      signal,
    });
    if (!result.data) throw new Error("目录响应缺失");
    return result.data;
  });
}
/**
 * 读取文本原字节的UTF-8解码结果，交给文本或Worker预览。
 * @param input - 账号客户端、登记链接位置与取消信号。
 * @returns 原始文本，不在主线程解析JSON。
 * @throws Error HTTP失败、超时或取消。
 * @sideEffects 发一次GET文件请求，不写文件或持久缓存。
 * @timeSemantics 只在选择文件后读取，单次最多60秒，不重试。
 */
export function readFileText(input: AccountCall<FileLocation>): Promise<string> {
  return boundedRequest(input.signal, DATASET_REQUEST_TIMEOUT_MS, async (signal) => {
    const value = input.payload;
    const result = await input.client.GET("/api/datasets/{dataset_id}/file", {
      params: {
        path: { dataset_id: value.datasetId },
        query: { link_name: value.linkName, path: value.path },
      },
      parseAs: "text",
      signal,
    });
    return result.data ?? "";
  });
}
/**
 * 生成原生图片和视频控件使用的同源文件URL。
 * @param location - 永久编号、登记链接名和相对文件路径。
 * @returns 经过分量编码的API地址，不暴露存储根。
 * @throws 无。
 * @sideEffects 无；实际请求由浏览器媒体控件发起并携带同源会话Cookie。
 * @timeSemantics 不缓存令牌；视频Range由浏览器按播放位置请求。
 */
export function fileUrl(location: FileLocation): string {
  return `/api/datasets/${encodeURIComponent(location.datasetId)}/file?link_name=${encodeURIComponent(location.linkName)}&path=${encodeURIComponent(location.path)}`;
}

/**
 * 在原生媒体控件失败后取得服务端的统一诊断。
 * @param input - 当前媒体的登记链接位置、账号客户端和取消信号。
 * @returns 接口仍可读时返回true，说明失败来自浏览器解码或播放。
 * @throws Error 接口返回离线、认证或其他失败时保留统一诊断cause；超时或取消同样拒绝。
 * @sideEffects 只发一次GET，Range固定bytes=0-0；不下载整个视频或图片，不写数据。
 * @timeSemantics 仅媒体失败时触发，最多60秒，不轮询不重试，离开预览取消。
 */
export function probeFile(input: AccountCall<FileLocation>): Promise<boolean> {
  return boundedRequest(input.signal, DATASET_REQUEST_TIMEOUT_MS, async (signal) => {
    const value = input.payload;
    await input.client.GET("/api/datasets/{dataset_id}/file", {
      params: {
        path: { dataset_id: value.datasetId },
        query: { link_name: value.linkName, path: value.path },
      },
      headers: { Range: "bytes=0-0" },
      parseAs: "arrayBuffer",
      signal,
    });
    return true;
  });
}

export type VideoInfo = components["schemas"]["VideoInfo"];
export interface VideoLocation extends FileLocation {
  /** 起点秒数，有限且非负；每段固定60秒。 */ startS: number;
}

/**
 * 探测首个视频流编码和总时长。
 * @param input - 已认证客户端、文件位置与取消信号。
 * @returns 编码与以秒计的总时长。
 * @throws Error 探测或HTTP失败，保留服务端五段诊断。
 * @sideEffects GET探测接口，不写存储。
 * @timeSemantics 最多60秒，不轮询，离开预览取消。
 */
export function readVideoInfo(input: AccountCall<FileLocation>): Promise<VideoInfo> {
  return boundedRequest(input.signal, DATASET_REQUEST_TIMEOUT_MS, async (signal) => {
    const value = input.payload;
    const result = await input.client.GET("/api/datasets/{dataset_id}/video-info", {
      params: {
        path: { dataset_id: value.datasetId },
        query: { link_name: value.linkName, path: value.path },
      },
      signal,
    });
    if (!result.data) throw new Error("视频探测响应缺失");
    return result.data;
  });
}

/**
 * 生成浏览器直接播放的分段转码地址。
 * @param location - 文件位置与非负起点秒数。
 * @returns 同源转码URL，片长固定60秒。
 * @throws 无。
 * @sideEffects 无；媒体控件发起实际请求。
 * @timeSemantics 起点相对于源视频开始，不缓存流。
 */
export function videoUrl(location: VideoLocation): string {
  return `/api/datasets/${encodeURIComponent(location.datasetId)}/video?link_name=${encodeURIComponent(location.linkName)}&path=${encodeURIComponent(location.path)}&start_s=${String(location.startS)}&duration_s=60`;
}

/**
 * 在转码播放失败时取得统一诊断，成功时立即取消探针流。
 * @param input - 已认证客户端、分段位置和取消信号。
 * @returns 取得可读响应时为true。
 * @throws Error 工具或HTTP失败，保留服务端诊断。
 * @sideEffects GET转码接口；仅探测响应头，不缓冲整个视频，成功后取消正文。
 * @timeSemantics 最多60秒，无重试，离开预览取消。
 */
export function probeVideo(input: AccountCall<VideoLocation>): Promise<boolean> {
  return boundedRequest(input.signal, DATASET_REQUEST_TIMEOUT_MS, async (signal) => {
    const value = input.payload;
    const result = await input.client.GET("/api/datasets/{dataset_id}/video", {
      params: {
        path: { dataset_id: value.datasetId },
        query: {
          link_name: value.linkName,
          path: value.path,
          start_s: value.startS,
          duration_s: 60,
        },
      },
      signal,
      parseAs: "stream",
    });
    await result.data?.cancel();
    return true;
  });
}

export type ParquetPage = components["schemas"]["ParquetPage"];
export interface ParquetLocation extends FileLocation {
  /** 从零起的行偏移，最大10000000。 */ offset: number;
}

/**
 * 读取parquet结构、计数和最多200行。
 * @param input - 已认证客户端、文件位置、行偏移和取消信号。
 * @returns 服务端有界单元格与结构，大文件仅有结构。
 * @throws Error HTTP失败、超时或响应缺失，保留统一诊断。
 * @sideEffects GET分页接口，不读取或缓存整表。
 * @timeSemantics 每次选择或翻页读取，不轮询，最多60秒，切换文件取消。
 */
export function readParquet(input: AccountCall<ParquetLocation>): Promise<ParquetPage> {
  return boundedRequest(input.signal, DATASET_REQUEST_TIMEOUT_MS, async (signal) => {
    const value = input.payload;
    const result = await input.client.GET("/api/datasets/{dataset_id}/parquet", {
      params: {
        path: { dataset_id: value.datasetId },
        query: { link_name: value.linkName, path: value.path, offset: value.offset, limit: 200 },
      },
      signal,
    });
    if (!result.data) throw new Error("parquet响应缺失");
    return result.data;
  });
}
