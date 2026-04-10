import { useEffect, useCallback, useState } from "react";
import { createPortal } from "react-dom";

export function ImageLightbox({ src, onClose }: { src: string; onClose: () => void }) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    requestAnimationFrame(() => setVisible(true));
  }, []);

  const close = useCallback(() => {
    setVisible(false);
    setTimeout(onClose, 150);
  }, [onClose]);

  const handleKey = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    },
    [close],
  );

  useEffect(() => {
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [handleKey]);

  return createPortal(
    <div
      className={`fixed inset-0 z-[100] flex items-center justify-center bg-black/30 backdrop-blur-sm cursor-zoom-out transition-opacity duration-150 ${visible ? "opacity-100" : "opacity-0"}`}
      onClick={close}
    >
      <img
        src={src}
        className={`max-w-[90vw] max-h-[90vh] object-contain rounded-lg shadow-2xl transition-transform duration-150 ${visible ? "scale-100" : "scale-90"}`}
        onClick={(e) => e.stopPropagation()}
        alt=""
      />
    </div>,
    document.body,
  );
}
