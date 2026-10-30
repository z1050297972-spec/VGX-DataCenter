// 原文件查看器轻量入口（M1.5-01）；点击后才加载预览和目录组件，控制主入口体积。
import { lazy, Suspense, useState, type ReactElement } from "react";
import { Button } from "antd";

const Viewer = lazy(() =>
  import("./FileViewer").then((module) => ({ default: module.FileViewer })),
);
export interface FileViewerProps {
  /** 已知永久编号。 */ datasetId: string | null;
  /** 当前规范登记链接名，不是文件系统路径。 */ linkNames: string[];
}
/**
 * 在详情中按需打开原文件只读查看器。
 * @param props - 永久编号与可选登记链接名。
 * @returns 入口按钮和按需加载的查看器。
 * @throws 无；加载中的状态由Suspense呈现。
 * @sideEffects 点击只改变本地展示，文件请求由查看器按选择发起。
 * @timeSemantics 首次点击加载组件；关闭卸载并取消目录和文本请求。
 */
export function FileViewerEntry(props: FileViewerProps): ReactElement {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button
        aria-label="查看原文件"
        disabled={!props.datasetId}
        onClick={() => {
          setOpen((value) => !value);
        }}
      >
        {open ? "关闭原文件" : "查看原文件"}
      </Button>
      {open && props.datasetId && (
        <Suspense fallback={<p role="status">正在加载原文件查看器</p>}>
          <Viewer {...props} datasetId={props.datasetId} />
        </Suspense>
      )}
    </>
  );
}
