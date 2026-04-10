import { useEffect, useCallback } from "react";
import { createPortal } from "react-dom";

export function ImageLightbox({ src, onClose }: { src: string; onClose: () => void }) {
  const handleKey = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    },
    [onClose],
  );

  useEffect(() => {
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [handleKey]);

  const filename = decodeURIComponent(src.split("/").pop() || "");

  return createPortal(
    <div
      className="fixed inset-0 z-[100] overflow-auto bg-black/30 backdrop-blur-sm cursor-zoom-out"
      onClick={onClose}
    >
      <div className="min-h-full flex flex-col items-center justify-center p-8">
        {filename && (
          <div
            className="mb-2 text-sm text-gray-300 bg-black/50 px-3 py-1 rounded-md font-mono"
            onClick={(e) => e.stopPropagation()}
          >
            {filename}
          </div>
        )}
        <img
          src={src}
          className="rounded-lg shadow-2xl"
          onClick={(e) => e.stopPropagation()}
          alt=""
        />
      </div>
    </div>,
    document.body,
  );
}
