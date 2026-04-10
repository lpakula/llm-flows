import { useMemo, useState, useCallback } from "react";
import { marked } from "marked";
import { ImageLightbox } from "./ImageLightbox";

marked.setOptions({ breaks: true });

export function MarkdownContent({ text, className = "" }: { text: string; className?: string }) {
  const html = useMemo(() => marked.parse(text) as string, [text]);
  const [lightboxSrc, setLightboxSrc] = useState<string | null>(null);

  const handleClick = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    const target = e.target as HTMLElement;
    if (target.tagName === "IMG") {
      e.preventDefault();
      setLightboxSrc((target as HTMLImageElement).src);
    }
  }, []);

  return (
    <>
      <div
        className={`md-content ${className}`}
        dangerouslySetInnerHTML={{ __html: html }}
        onClick={handleClick}
      />
      {lightboxSrc && <ImageLightbox src={lightboxSrc} onClose={() => setLightboxSrc(null)} />}
    </>
  );
}
