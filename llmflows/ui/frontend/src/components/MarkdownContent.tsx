import { useMemo } from "react";
import { marked } from "marked";

marked.setOptions({ breaks: true });

export function MarkdownContent({ text, className = "" }: { text: string; className?: string }) {
  const html = useMemo(() => marked.parse(text) as string, [text]);
  return (
    <div
      className={`md-content ${className}`}
      // Safe: content is user-supplied in a local single-user app
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
