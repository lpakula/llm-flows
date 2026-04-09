import { useEffect, useRef } from "react";

function findScrollParent(el: HTMLElement): HTMLElement | null {
  let node = el.parentElement;
  while (node) {
    const { overflowY } = getComputedStyle(node);
    if (overflowY === "auto" || overflowY === "scroll") return node;
    node = node.parentElement;
  }
  return null;
}

export function useAutoResize(value: string) {
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.overflow = "hidden";
    const scroller = findScrollParent(el);
    const prevScroll = scroller ? scroller.scrollTop : window.scrollY;
    el.style.height = "0";
    el.style.height = `${el.scrollHeight}px`;
    if (scroller) scroller.scrollTop = prevScroll;
    else window.scrollTo({ top: prevScroll });
  }, [value]);

  return ref;
}
