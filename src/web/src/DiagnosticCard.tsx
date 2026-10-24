// 统一诊断展示组件（M0 工单 04、规范 10.5）；使用 Ant Design，不负责请求协议或作业结果。
// 本票没有报错详情接口；可选回调为第 5 张存表后的接入点，缺省仅提示按编号查运行日志。
import type { ReactElement } from "react";
import { Card, Button, Collapse } from "antd";
import { useState, useEffect } from "react";
import type { ProblemResponse, RequestFailureView } from "./api/problems";

// 类别中文名与后端 DiagnosticCategory 的显示约定一致，统一用于诊断标题。
const CATEGORY_LABELS: Record<ProblemResponse["category"], string> = {
  input: "输入或数据问题",
  conflict: "冲突",
  external: "外部失败",
  defect: "程序缺陷",
};

/** 工单 04 选择的详情加载上限，单位毫秒；避免展开后永久等待，独立于健康检查的超时策略。 */
export const ERROR_DETAILS_TIMEOUT_MS = 5000;

/** 卡片属性无物理量；服务端结构全部从 OpenAPI 生成类型间接取得。 */
export interface DiagnosticCardProps {
  /** 必填的已归一化请求失败；无默认值，无单位；服务端诊断保持原顺序。 */
  failure: RequestFailureView;
  /**
   * 可选的完整报错加载器；参数为服务端错误编号和取消信号，返回已脱敏纯文本。
   * 默认不提供；只用于程序缺陷。不得在回调中直接使用未批准的详情接口或回显秘密。
   */
  loadDetails?: (errorId: ProblemResponse["error_id"], signal: AbortSignal) => Promise<string>;
}

/**
 * 显示五段诊断或程序缺陷摘要，并在用户展开后才显示完整报错区域。
 *
 * @param props - 卡片输入，无单位，字段约束见 DiagnosticCardProps。
 * @returns 非缺陷 problem 的每条诊断标题显示级别、类别中文名、阶段和“来源：来源名”；
 * 按诊断顺序展示五段：对象、规则、实际与期望
 * （同一行）、后果、检查（下一步建议）。对象按原键值顺序显示，空对象显示“全局”，expected=null
 * 不显示期望；所有 problem 均显示“错误编号：<编号>”。无诊断时显示服务端 detail；
 * 程序缺陷折叠时只显示 detail 和带标签的错误编号，
 * 不显示诊断/栈；展开后没有 loadDetails 时显示“请按错误编号在运行日志中查询完整报错。”；
 * 有回调时显示加载提示、返回的纯文本或固定“完整报错暂不可用，请按编号查询运行日志。”。
 * unavailable 只显示适配层提供的固定文案，有编号时同样显示“错误编号：<编号>”，
 * 不提供完整报错展开按钮。
 * D1：诊断 error_chain 非空时显示“错误链（N 层）”折叠入口，展开后按外到内顺序显示；
 * 空链无入口。所有服务端文字及详情均按 React 文本渲染，不执行 HTML；组件不自行拼接报错原因。
 * @throws 无。详情回调的同步异常或 Promise 拒绝都转成固定提示，不显示异常原文。
 * @sideEffects 默认不发请求、不改 URL/存储。仅用户首次展开缺陷详情且提供回调时调用一次；
 * 同编号折叠再展开复用本次挂载的成功结果或失败提示，不轮询、不自动重试。
 * 卸载、编号或回调变化时取消旧请求并清空详情，忽略迟到结果；新编号重新从折叠态开始。
 * @timeSemantics 详情请求上限使用 ERROR_DETAILS_TIMEOUT_MS（5000 毫秒），超时取消并显示固定失败提示；
 * 完成、切换或卸载时清理计时器；本次挂载之外不缓存。其他展示同步，无额外轮询。
 */
export function DiagnosticCard(props: DiagnosticCardProps): ReactElement {
  if (props.failure.kind === "unavailable")
    return (
      <Card role="alert">
        <div>{props.failure.message}</div>
        {props.failure.errorId && <div>错误编号：{props.failure.errorId}</div>}
      </Card>
    );
  const problem = props.failure.problem;
  if (problem.category === "defect")
    return <DefectCard key={problem.error_id} problem={problem} loadDetails={props.loadDetails} />;
  if (!problem.diagnostics.length)
    return (
      <Card role="alert">
        <div>{problem.detail}</div>
        <div>错误编号：{problem.error_id}</div>
      </Card>
    );
  return (
    <div role="alert">
      <div>错误编号：{problem.error_id}</div>
      {problem.diagnostics.map((d, index) => (
        <Card key={index}>
          <div>
            {d.level === "error" ? "错误" : "警告"} · {CATEGORY_LABELS[d.category]} · {d.stage} ·
            来源：{d.source}
          </div>
          <div>
            对象：{d.objects.map((item) => item.key + "=" + item.value).join(" ") || "全局"}
          </div>
          <div>规则：{d.rule}</div>
          <div>
            实际：{d.actual}
            {d.expected != null ? "；期望：" + d.expected : ""}
          </div>
          <div>后果：{d.consequence}</div>
          <div>检查：{d.next_step}</div>
          {!!d.error_chain.length && (
            <Collapse
              items={[
                {
                  key: "chain",
                  label: `错误链（${String(d.error_chain.length)} 层）`,
                  children: (
                    <ol>
                      {d.error_chain.map((layer, i) => (
                        <li key={i}>{layer}</li>
                      ))}
                    </ol>
                  ),
                },
              ]}
            />
          )}
        </Card>
      ))}
    </div>
  );
}

function DefectCard({
  problem,
  loadDetails,
}: {
  problem: ProblemResponse;
  loadDetails?: DiagnosticCardProps["loadDetails"];
}): ReactElement {
  const [previousLoader, setPreviousLoader] = useState(() => loadDetails);
  const [open, setOpen] = useState(false);
  const [requested, setRequested] = useState(false);
  const [details, setDetails] = useState("正在加载完整报错…");
  // 同编号更换加载器也视为新详情来源，先在渲染阶段复位，避免旧内容闪现。
  if (previousLoader !== loadDetails) {
    setPreviousLoader(() => loadDetails);
    setOpen(false);
    setRequested(false);
    setDetails("正在加载完整报错…");
  }
  useEffect(() => {
    if (!requested || !loadDetails) return;
    const controller = new AbortController();
    let active = true;
    const timer = setTimeout(() => {
      active = false;
      controller.abort();
      setDetails("完整报错暂不可用，请按编号查询运行日志。");
    }, ERROR_DETAILS_TIMEOUT_MS);
    void Promise.resolve()
      .then(() => loadDetails(problem.error_id, controller.signal))
      .then((value) => {
        if (active) setDetails(value);
      })
      .catch(() => {
        if (active) setDetails("完整报错暂不可用，请按编号查询运行日志。");
      })
      .finally(() => {
        clearTimeout(timer);
      });
    return () => {
      active = false;
      controller.abort();
      clearTimeout(timer);
    };
  }, [requested, loadDetails, problem.error_id]);
  return (
    <Card role="alert">
      <div>{problem.detail}</div>
      <div>错误编号：{problem.error_id}</div>
      <Button
        onClick={() => {
          setOpen(!open);
          if (!requested && loadDetails) setRequested(true);
        }}
      >
        完整报错
      </Button>
      {open && <pre>{loadDetails ? details : "请按错误编号在运行日志中查询完整报错。"}</pre>}
    </Card>
  );
}
