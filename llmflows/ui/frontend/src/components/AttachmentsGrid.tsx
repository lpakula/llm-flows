import { useState } from "react";
import { ImageLightbox } from "./ImageLightbox";

const IMAGE_EXTS = new Set([".png", ".jpg", ".jpeg", ".gif", ".webp"]);

function isImage(name: string) {
  const ext = name.slice(name.lastIndexOf(".")).toLowerCase();
  return IMAGE_EXTS.has(ext);
}

export function AttachmentsGrid({ files }: { files: { name: string; url: string }[] }) {
  const [lightboxSrc, setLightboxSrc] = useState<string | null>(null);

  if (!files || files.length === 0) return null;

  return (
    <>
      <h3 className="text-sm font-semibold text-gray-400 mt-6 mb-3">Attachments</h3>
      <div className="flex flex-wrap gap-3" onClick={(e) => e.stopPropagation()}>
        {files.map((f) => (
          <div
            key={f.name}
            className="border border-gray-700 rounded-lg overflow-hidden bg-gray-800/50 w-[180px] cursor-pointer hover:border-gray-500 transition-colors"
            onClick={() => isImage(f.name) ? setLightboxSrc(f.url) : window.open(f.url, "_blank")}
          >
            <div className="px-2.5 py-1.5 text-xs text-gray-300 font-mono truncate border-b border-gray-700" title={f.name}>
              {f.name}
            </div>
            {isImage(f.name) ? (
              <img
                src={f.url}
                alt={f.name}
                className="w-full h-[120px] object-cover"
              />
            ) : (
              <div className="w-full h-[120px] flex items-center justify-center text-gray-500 text-2xl">
                📄
              </div>
            )}
          </div>
        ))}
      </div>
      {lightboxSrc && <ImageLightbox src={lightboxSrc} onClose={() => setLightboxSrc(null)} />}
    </>
  );
}
