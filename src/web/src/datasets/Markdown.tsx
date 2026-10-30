// 快照 Markdown 展示（11 Q12、原型16）：沿用原型的行内代码与链接语法，补充常见块和强调。
// 标准库和现有依赖没有 Markdown 渲染器；这里只渲染快照使用的语法，其余原样保留，绝不执行 HTML。
// 数据路径不是 Web 地址，保持为可复制文本；外部链接只允许 HTTP(S)/mailto，不探测目标。
import type { ReactElement, ReactNode } from "react";

interface Props {
  /** value_markdown 原文，不从中推导型号、FPS 或大小。 */ text: string;
}
/**
 * 将快照的 Markdown 文本安全地显示为段落、列表、标题、引用及行内格式。
 * @param props - 原始说明文字；不接受 HTML 作为组件或属性。
 * @returns React 文本与语义元素；不支持的语法保留原文，数据路径不作为可点击地址。
 * @throws 无；非法 URL 保留文字。
 * @sideEffects 无；不会请求图片、执行 HTML 或访问本地路径。
 * @timeSemantics 同步渲染，不解释原文中的时间或业务含义。
 */
export function MarkdownValue(props: Props): ReactElement {
  return <div className="dataset-markdown">{blocks(props.text)}</div>;
}

// 先分隔围栏代码，防止代码里的链接与标记被二次解释。
function blocks(text: string): ReactNode[] {
  const sections = text.split(/(```[^\n]*\n[\s\S]*?```)/g);
  return sections.flatMap((section, index) => {
    if (section.startsWith("```"))
      return [
        <pre key={index}>
          <code>{section.slice(section.indexOf("\n") + 1, -3)}</code>
        </pre>,
      ];
    return section
      .split(/\n\s*\n/)
      .filter(Boolean)
      .map((paragraph, offset) => (
        <Block key={`${String(index)}:${String(offset)}`} text={paragraph} />
      ));
  });
}

// 列表只展示说明，不根据数字条目建立业务数据关系。
function Block({ text }: { text: string }): ReactElement {
  const lines = text.split("\n");
  if (lines.every((line) => /^\s*[-*+]\s+/.test(line)))
    return (
      <ul>
        {lines.map((line, index) => (
          <li key={index}>{inline(line.replace(/^\s*[-*+]\s+/, ""))}</li>
        ))}
      </ul>
    );
  if (lines.every((line) => /^\s*\d+[.)]\s+/.test(line)))
    return (
      <ol>
        {lines.map((line, index) => (
          <li key={index}>{inline(line.replace(/^\s*\d+[.)]\s+/, ""))}</li>
        ))}
      </ol>
    );
  if (text.startsWith("> ")) return <blockquote>{inline(text.replace(/^>\s?/gm, ""))}</blockquote>;
  if (/^#{1,6} /.test(text)) return <h4>{inline(text.replace(/^#{1,6} /, ""))}</h4>;
  return <p style={{ whiteSpace: "pre-wrap" }}>{inline(text)}</p>;
}

// 行内匹配仅产生 React 元素，服务器文字永远不会进入 dangerouslySetInnerHTML。
function inline(text: string): ReactNode[] {
  const result: ReactNode[] = [];
  const pattern = /`([^`]+)`|\[([^\]]+)\]\((?:<([^>]+)>|([^)]+))\)|\*\*([^*]+)\*\*|\*([^*]+)\*/g;
  let cursor = 0;
  for (const match of text.matchAll(pattern)) {
    result.push(text.slice(cursor, match.index));
    result.push(<InlineMatch key={match.index} match={match} />);
    cursor = match.index + match[0].length;
  }
  result.push(text.slice(cursor));
  return result;
}

// 原型中的本地链接采用 [文字](<路径>)，只展示文字与路径；外部链接显式限制协议。
function InlineMatch({ match }: { match: RegExpExecArray }): ReactElement {
  if (match[1] !== undefined) return <code>{match[1]}</code>;
  if (match[5] !== undefined) return <strong>{match[5]}</strong>;
  if (match[6] !== undefined) return <em>{match[6]}</em>;
  const target = match[3] ?? match[4] ?? "";
  const href = safeHref(target);
  if (href)
    return (
      <a href={href} target="_blank" rel="noopener noreferrer">
        {match[2]}
      </a>
    );
  return (
    <span>
      {match[2]}（<code>{target}</code>）
    </span>
  );
}

// 相对路径不补本站地址，未知或脚本协议不能变成可执行链接。
function safeHref(target: string): string | null {
  try {
    const url = new URL(target);
    return ["http:", "https:", "mailto:"].includes(url.protocol) ? url.href : null;
  } catch {
    return null;
  }
}
