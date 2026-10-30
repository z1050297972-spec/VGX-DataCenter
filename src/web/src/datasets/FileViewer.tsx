// 原文件查看器（M1.5-01）：目录与预览分栏，复用Query取消、统一诊断、时间/大小和JSON Worker。
import { useState, type ReactElement } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "antd";
import { useAccountClient, useCurrentAccount } from "../accounts/runtime";
import {
  listFiles,
  readFileText,
  fileUrl,
  probeFile,
  type FileItem,
  type FileLocation,
  type FilePage,
} from "../api/fileViewer";
import { DiagnosticCard } from "../DiagnosticCard";
import { toFailureView } from "../api/problems";
import { formatDateTime } from "../time";
import { formatBytes } from "./formatBytes";
import { JsonViewer } from "./JsonViewer";
import type { FileViewerProps } from "./FileViewerEntry";
import "./fileViewer.css";

// 离开立即释放目录/大文本；禁用后台刷新，避免媒体播放时反复加载目录。
const options = {
  retry: false,
  staleTime: 0,
  gcTime: 0,
  refetchOnWindowFocus: false,
  refetchOnReconnect: false,
} as const;

/**
 * 在已登记链接目标内逐级浏览并预览文件。
 * @param props - 数据集永久编号与登记链接名。
 * @returns 链接选择、目录列表、分页与右侧只读预览。
 * @throws 无；请求失败展示五段诊断。
 * @sideEffects 仅GET目录和文件；切换链接、目录或关闭时取消旧请求，不修改URL或存储。
 * @timeSemantics 每次选择读取现场目录；不轮询，mtime只作展示，时刻显示浏览器本地时区。
 */
export function FileViewer(props: FileViewerProps & { datasetId: string }): ReactElement {
  const [linkName, setLinkName] = useState("");
  const [path, setPath] = useState("");
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<FileItem | null>(null);
  const client = useAccountClient();
  const identity = useCurrentAccount();
  const location = { datasetId: props.datasetId, linkName, path };
  const query = useQuery({
    ...options,
    enabled: !!linkName,
    queryKey: ["datasets", identity.data?.account_id, "files", location, offset],
    queryFn: ({ signal }) => listFiles({ client, payload: { ...location, offset }, signal }),
  });
  function go(next: string): void {
    setPath(next);
    setOffset(0);
    setSelected(null);
  }
  return (
    <section aria-label="原文件查看器" className="file-viewer">
      <p>数据盘原文件 · 只读</p>
      <select
        aria-label="选择原文件链接"
        value={linkName}
        onChange={(event) => {
          setLinkName(event.target.value);
          go("");
        }}
      >
        <option value="">请选择链接</option>
        {[...new Set(props.linkNames)].map((name) => (
          <option key={name} value={name}>
            {name}
          </option>
        ))}
      </select>
      {!props.linkNames.length && <p>没有已登记链接，请重新扫描后查看。</p>}
      {linkName && (
        <>
          <p className="file-viewer-path" title={path || "/"}>
            当前位置：{path || "/"}
          </p>
          <Button
            aria-label="原文件上一级"
            disabled={!path}
            onClick={() => {
              go(path.split("/").slice(0, -1).join("/"));
            }}
          >
            上一级
          </Button>
          <Button
            aria-label="刷新原文件目录"
            onClick={() => {
              void query.refetch();
            }}
          >
            刷新
          </Button>
          {query.isFetching && <p role="status">正在读取目录</p>}
          {query.error && <DiagnosticCard failure={toFailureView(query.error)} />}
          <div className="file-viewer-columns">
            <div className="file-viewer-directory" aria-label="原文件目录">
              <Directory
                page={query.data}
                fetching={query.isFetching}
                offset={offset}
                onPage={setOffset}
                onOpen={(item) => {
                  if (item.kind === "directory") go([path, item.name].filter(Boolean).join("/"));
                  else setSelected(item);
                }}
              />
            </div>
            <div className="file-viewer-preview" aria-label="原文件预览">
              {selected ? (
                <Preview
                  key={`${linkName}/${path}/${selected.name}`}
                  location={{ ...location, path: [path, selected.name].filter(Boolean).join("/") }}
                  name={selected.name}
                />
              ) : (
                <p>选择文件以预览</p>
              )}
            </div>
          </div>
        </>
      )}
    </section>
  );
}

function Directory(props: {
  page: FilePage | undefined;
  fetching: boolean;
  offset: number;
  onPage: (offset: number) => void;
  onOpen: (item: FileItem) => void;
}): ReactElement {
  return (
    <>
      {props.page?.items.map((item) => (
        <FileRow key={item.name} item={item} onOpen={props.onOpen} />
      ))}
      {props.page && !props.page.items.length && <p>空目录</p>}
      <Button
        aria-label="原文件上一页"
        disabled={!props.offset || props.fetching}
        onClick={() => {
          props.onPage(Math.max(0, props.offset - 100));
        }}
      >
        上一页
      </Button>
      <Button
        aria-label="原文件下一页"
        disabled={!props.page?.has_more || props.fetching}
        onClick={() => {
          props.onPage(props.offset + 100);
        }}
      >
        下一页
      </Button>
    </>
  );
}

function FileRow({
  item,
  onOpen,
}: {
  item: FileItem;
  onOpen: (item: FileItem) => void;
}): ReactElement {
  return (
    <div className="file-viewer-row">
      <Button
        block
        disabled={item.kind === "special" || item.kind === "symlink"}
        title={item.name}
        aria-label={`${item.kind === "directory" ? "打开目录" : "预览文件"} ${item.name}`}
        onClick={() => {
          onOpen(item);
        }}
      >
        {item.kind === "directory" ? "📁 " : ""}
        {item.name}
      </Button>
      <small>
        {item.kind} · {formatBytes(item.size_bytes)} · {formatDateTime(item.modified_at)}
      </small>
    </div>
  );
}

type PreviewKind = "json" | "text" | "video" | "image" | "other";
function previewKind(name: string): PreviewKind {
  if (/\.(mp4|webm|mov|m4v|ogv)$/i.test(name)) return "video";
  if (/\.(png|jpe?g|gif|webp|bmp|avif)$/i.test(name)) return "image";
  if (/\.(json|jsonl)$/i.test(name)) return "json";
  if (/\.(txt|md|csv|tsv|log|yaml|yml|toml|xml|ini|cfg)$/i.test(name)) return "text";
  return "other";
}

function Preview({ location, name }: { location: FileLocation; name: string }): ReactElement {
  const kind = previewKind(name);
  const text = kind === "json" || kind === "text";
  const client = useAccountClient();
  const identity = useCurrentAccount();
  const query = useQuery({
    ...options,
    enabled: text,
    queryKey: ["datasets", identity.data?.account_id, "file-text", location],
    queryFn: ({ signal }) => readFileText({ client, payload: location, signal }),
  });
  return (
    <>
      <p className="file-viewer-path" title={name}>
        {name}
      </p>
      <MediaPreview kind={kind} location={location} name={name} />
      {text && query.isPending && <p role="status">正在读取文件</p>}
      {query.error && <DiagnosticCard failure={toFailureView(query.error)} />}
      {query.data !== undefined &&
        (kind === "json" ? (
          <JsonViewer content={query.data} label="原文件 JSON" format />
        ) : (
          <pre className="file-viewer-text">{query.data}</pre>
        ))}
      {kind === "other" && <p>此格式不支持在线预览，请下载工具查看。</p>}
    </>
  );
}

function MediaPreview({
  kind,
  location,
  name,
}: {
  kind: PreviewKind;
  location: FileLocation;
  name: string;
}): ReactElement {
  const [failed, setFailed] = useState(false);
  const src = fileUrl(location);
  const client = useAccountClient();
  const identity = useCurrentAccount();
  const diagnostic = useQuery({
    ...options,
    enabled: failed,
    queryKey: ["datasets", identity.data?.account_id, "file-media-error", location],
    queryFn: ({ signal }) => probeFile({ client, payload: location, signal }),
  });
  return (
    <>
      {failed && <DiagnosticCard failure={toFailureView(diagnostic.error)} />}
      {kind === "video" && (
        <video
          aria-label="原文件视频"
          src={src}
          controls
          preload="metadata"
          onError={() => {
            setFailed(true);
          }}
        />
      )}
      {kind === "image" && (
        <img
          aria-label="原文件图片"
          alt={name}
          src={src}
          onError={() => {
            setFailed(true);
          }}
        />
      )}
    </>
  );
}
