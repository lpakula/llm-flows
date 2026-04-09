import { useCallback, useRef } from "react";
import { api } from "@/api/client";

/**
 * Returns a onPaste handler for a textarea that uploads pasted images
 * and inserts a markdown image reference at the cursor position.
 */
export function useImagePaste(
  taskId: string | undefined,
  setValue: React.Dispatch<React.SetStateAction<string>>,
) {
  const taskIdRef = useRef(taskId);
  taskIdRef.current = taskId;

  return useCallback(
    async (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
      if (!taskIdRef.current) return;
      const items = Array.from(e.clipboardData.items);
      const imageItem = items.find((it) => it.type.startsWith("image/"));
      if (!imageItem) return;

      e.preventDefault();

      const file = imageItem.getAsFile();
      if (!file) return;

      const textarea = e.currentTarget;
      const start = textarea.selectionStart;
      const end = textarea.selectionEnd;

      const placeholder = "![uploading…]()";

      setValue((prev) => prev.slice(0, start) + placeholder + prev.slice(end));

      try {
        const { url } = await api.uploadAttachment(taskIdRef.current!, file);
        setValue((prev) => prev.replace(placeholder, `![image](${url})`));
      } catch (err) {
        console.error("Image upload failed:", err);
        setValue((prev) => prev.replace(placeholder, ""));
      }
    },
    [setValue],
  );
}
