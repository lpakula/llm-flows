import { useState, useRef, useEffect, useCallback, forwardRef, useImperativeHandle } from "react";
import { useSearchParams } from "react-router-dom";
import { RotateCcw, Loader2, Workflow, Rocket, HelpCircle, ArrowUp, ChevronDown, Plus, X } from "lucide-react";
import { api } from "@/api/client";
import { useApp } from "@/App";
import { MarkdownContent } from "@/components/MarkdownContent";
import { formatCost } from "@/lib/format";
import type { ChatEvent, ConnectorConfig } from "@/api/types";

type Message = { role: "user" | "assistant"; content: string };

const SUGGESTIONS = [
  { icon: Rocket, label: "How to start?", question: "How do I get started? Just the essential setup steps. Keep it short." },
  { icon: Workflow, label: "Help me build a flow", question: "Help me build a flow" },
  { icon: HelpCircle, label: "Help me create a skill", question: "Help me create a skill for my project" },
];

async function* readChatStream(
  response: Response,
): AsyncGenerator<ChatEvent, void, undefined> {
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (line.startsWith("data: ")) {
        try {
          yield JSON.parse(line.slice(6)) as ChatEvent;
        } catch {
          /* skip malformed */
        }
      }
    }
  }
}

function ChatInput({
  inputRef,
  input,
  setInput,
  onSend,
  onKeyDown,
  streaming,
  placeholder,
  centered,
}: {
  inputRef: React.RefObject<HTMLTextAreaElement | null>;
  input: string;
  setInput: (v: string) => void;
  onSend: () => void;
  onKeyDown: (e: React.KeyboardEvent) => void;
  streaming: boolean;
  placeholder: string;
  centered?: boolean;
}) {
  return (
    <div className={centered ? "w-full max-w-2xl" : "max-w-3xl mx-auto"}>
      <div className="flex items-end gap-2 bg-gray-800/80 border border-gray-700 rounded-xl px-4 py-2 focus-within:ring-1 focus-within:ring-gray-600 focus-within:border-gray-600">
        <textarea
          ref={inputRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          onInput={(e) => {
            const t = e.currentTarget;
            t.style.height = "auto";
            t.style.height = Math.min(t.scrollHeight, 160) + "px";
          }}
          placeholder={placeholder}
          rows={1}
          disabled={streaming}
          className="flex-1 bg-transparent text-sm text-gray-200 placeholder:text-gray-500 focus:outline-none resize-none overflow-hidden disabled:opacity-50 py-1"
        />
        <button
          onClick={onSend}
          disabled={streaming || !input.trim()}
          className="p-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-30 disabled:bg-gray-700 transition flex-shrink-0 mb-0.5"
        >
          {streaming ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <ArrowUp size={14} />
          )}
        </button>
      </div>
    </div>
  );
}

function MessageBubble({ msg }: { msg: Message }) {
  if (msg.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] bg-blue-600/20 border border-blue-500/20 rounded-xl px-4 py-2.5 text-sm text-gray-200">
          {msg.content}
        </div>
      </div>
    );
  }

  return (
    <div className="flex justify-start">
      <div className="max-w-[85%]">
        <div className="bg-gray-800/50 border border-gray-700/50 rounded-xl px-4 py-3">
          <MarkdownContent
            text={msg.content}
            className="text-sm text-gray-200"
          />
        </div>
      </div>
    </div>
  );
}

function StreamingBubble({ text, thinkingText }: { text: string; thinkingText?: string }) {
  return (
    <div className="flex justify-start">
      <div className="max-w-[85%]">
        {!text && thinkingText && (
          <div className="bg-gray-800/30 border border-gray-700/30 rounded-xl px-4 py-3 mb-2">
            <div className="flex items-center gap-2 text-[11px] text-gray-500 mb-1.5">
              <Loader2 size={10} className="animate-spin" />
              Reasoning
            </div>
            <p className="text-xs text-gray-500 leading-relaxed whitespace-pre-wrap">{thinkingText}</p>
          </div>
        )}
        {!text && !thinkingText && (
          <div className="bg-gray-800/50 border border-gray-700/50 rounded-xl px-4 py-3">
            <div className="flex items-center gap-2 text-sm text-gray-500">
              <Loader2 size={12} className="animate-spin" />
              Thinking...
            </div>
          </div>
        )}
        {text && (
          <div className="bg-gray-800/50 border border-gray-700/50 rounded-xl px-4 py-3">
            <MarkdownContent
              text={text + "\u258C"}
              className="text-sm text-gray-200"
            />
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Connector picker ──────────────────────────────────────────── */

function ConnectorPicker({
  available,
  selected,
  onToggle,
  disabled,
}: {
  available: ConnectorConfig[];
  selected: string[];
  onToggle: (id: string) => void;
  disabled: boolean;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    requestAnimationFrame(() => document.addEventListener("click", close));
    return () => document.removeEventListener("click", close);
  }, [open]);

  const unselected = available.filter((c) => !selected.includes(c.server_id));

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        disabled={disabled || unselected.length === 0}
        className="flex items-center gap-1 text-[11px] text-gray-500 hover:text-gray-300 bg-gray-800/60 hover:bg-gray-700/60 border border-dashed border-gray-700/60 rounded-md px-1.5 py-0.5 transition disabled:opacity-30 disabled:cursor-not-allowed"
      >
        <Plus size={10} />
        tool
      </button>
      {open && unselected.length > 0 && (
        <div className="absolute bottom-full left-0 mb-1 bg-gray-800 border border-gray-700 rounded-lg shadow-xl z-50 py-1 min-w-[120px]">
          {unselected.map((c) => (
            <button
              key={c.server_id}
              onClick={() => { onToggle(c.server_id); setOpen(false); }}
              className="block w-full text-left px-3 py-1.5 text-xs text-gray-300 hover:bg-gray-700/60 transition"
            >
              {c.name}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function ConnectorPills({
  available,
  selected,
  onRemove,
  locked,
}: {
  available: ConnectorConfig[];
  selected: string[];
  onRemove: (id: string) => void;
  locked: boolean;
}) {
  if (selected.length === 0) return null;
  return (
    <>
      {selected.map((id) => {
        const c = available.find((x) => x.server_id === id);
        return (
          <span
            key={id}
            className="inline-flex items-center gap-1 text-[11px] text-gray-400 bg-gray-800/60 border border-gray-700/60 rounded-md px-1.5 py-0.5"
          >
            {c?.name ?? id}
            {!locked && (
              <button
                onClick={() => onRemove(id)}
                className="text-gray-600 hover:text-gray-300 transition"
              >
                <X size={9} />
              </button>
            )}
          </span>
        );
      })}
    </>
  );
}

const TIERS = ["mini", "normal", "max"] as const;
type Tier = (typeof TIERS)[number];

export function ChatView() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { selectedSpaceId, chatState, setChatState } = useApp();
  const messages = chatState.messages;
  const sessionId = chatState.sessionId;
  const setMessages = useCallback(
    (updater: Message[] | ((prev: Message[]) => Message[])) =>
      setChatState((s) => ({
        ...s,
        messages: typeof updater === "function" ? updater(s.messages) : updater,
      })),
    [setChatState],
  );
  const setSessionId = useCallback(
    (id: string | null) => setChatState((s) => ({ ...s, sessionId: id })),
    [setChatState],
  );
  const [streaming, setStreaming] = useState(false);
  const [input, setInput] = useState("");
  const [streamText, setStreamText] = useState("");
  const [thinkingText, setThinkingText] = useState("");
  const [tier, setTier] = useState<Tier>("max");
  const [totalCost, setTotalCost] = useState(0);
  const [tierOpen, setTierOpen] = useState(false);

  const [availableConnectors, setAvailableConnectors] = useState<ConnectorConfig[]>([]);
  const [selectedConnectors, setSelectedConnectors] = useState<string[]>([]);
  const connectorsLocked = messages.length > 0 || streaming;

  useEffect(() => {
    api.getConnectors().then((all) => setAvailableConnectors(all.filter((c) => c.enabled)));
  }, []);

  const toggleConnector = useCallback((id: string) => {
    setSelectedConnectors((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  }, []);
  const removeConnector = useCallback((id: string) => {
    setSelectedConnectors((prev) => prev.filter((x) => x !== id));
  }, []);

  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  const scrollToBottom = useCallback(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, []);

  useEffect(scrollToBottom, [messages, streamText, thinkingText, scrollToBottom]);

  useEffect(() => {
    if (!tierOpen) return;
    const close = (e: MouseEvent) => {
      if ((e.target as HTMLElement).closest?.("[data-tier-toggle]")) return;
      setTierOpen(false);
    };
    requestAnimationFrame(() => document.addEventListener("click", close));
    return () => document.removeEventListener("click", close);
  }, [tierOpen]);

  const sendMessage = useCallback(
    async (text: string, overrides?: { connectors?: string[]; sessionId?: string | null }) => {
      if (!text.trim() || streaming) return;

      const userMsg: Message = { role: "user", content: text.trim() };
      setMessages((prev) => [...prev, userMsg]);
      setInput("");
      setStreaming(true);
      setStreamText("");
      setThinkingText("");

      const abort = new AbortController();
      abortRef.current = abort;

      try {
        const connectors = overrides?.connectors ?? selectedConnectors;
        const sid = overrides?.sessionId !== undefined ? overrides.sessionId : sessionId;
        const response = await api.sendChat(
          text.trim(),
          selectedSpaceId,
          sid,
          tier,
          undefined,
          connectors.length > 0 ? connectors : undefined,
        );

        if (!response.ok) {
          const errText = await response.text();
          setMessages((prev) => [
            ...prev,
            { role: "assistant", content: `Error: ${response.status} — ${errText}` },
          ]);
          setStreaming(false);
          return;
        }

        let accumulated = "";
        let accumulatedThinking = "";

        for await (const event of readChatStream(response)) {
          if (abort.signal.aborted) break;

          if (event.type === "thinking_delta") {
            accumulatedThinking += event.text;
            setThinkingText(accumulatedThinking);
          } else if (event.type === "text_delta") {
            accumulated += event.text;
            setStreamText(accumulated);
          } else if (event.type === "done") {
            if (event.session_id) {
              setSessionId(event.session_id);
            }
            if (event.cost_usd) {
              setTotalCost((prev) => prev + event.cost_usd!);
            }
          }
        }

        const finalContent = accumulated.trim();
        if (finalContent) {
          setMessages((prev) => [
            ...prev,
            { role: "assistant", content: finalContent },
          ]);
        }
      } catch (err) {
        if (!abort.signal.aborted) {
          setMessages((prev) => [
            ...prev,
            { role: "assistant", content: `Connection error: ${err instanceof Error ? err.message : String(err)}` },
          ]);
        }
      } finally {
        setStreaming(false);
        setStreamText("");
        setThinkingText("");
        abortRef.current = null;
        setTimeout(() => inputRef.current?.focus(), 50);
      }
    },
    [streaming, selectedSpaceId, sessionId, tier, selectedConnectors],
  );

  const promptHandled = useRef(false);

  useEffect(() => {
    const prompt = searchParams.get("prompt");
    const tools = searchParams.get("tools");
    if (prompt && !streaming && !promptHandled.current) {
      promptHandled.current = true;
      setSearchParams({}, { replace: true });

      const ids = tools ? tools.split(",").filter(Boolean) : [];

      if (abortRef.current) abortRef.current.abort();
      if (sessionId) api.deleteChatSession(sessionId).catch(() => {});
      setChatState({ messages: [], sessionId: null });
      setTotalCost(0);
      setSelectedConnectors(ids);

      sendMessage(prompt, { connectors: ids, sessionId: null });
    }
    if (!searchParams.get("prompt")) {
      promptHandled.current = false;
    }
  }, [searchParams, setSearchParams, sendMessage, streaming, sessionId, setChatState]);

  const handleNewChat = useCallback(() => {
    if (streaming && abortRef.current) {
      abortRef.current.abort();
    }
    if (sessionId) {
      api.deleteChatSession(sessionId).catch(() => {});
    }
    setChatState({ messages: [], sessionId: null });
    setStreaming(false);
    setStreamText("");
    setInput("");
    setTotalCost(0);
    setSelectedConnectors([]);
  }, [streaming, sessionId, setChatState]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage(input);
      }
    },
    [input, sendMessage],
  );

  const placeholder = selectedSpaceId
    ? "Ask about llm-flows or describe a flow to build..."
    : "Ask about llm-flows... (select a space to create flows)";

  const showWelcome = messages.length === 0 && !streaming;

  if (showWelcome) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center px-6 select-none pb-[15%]">
        <div className="w-full max-w-2xl flex flex-col items-center">
          <h2 className="text-2xl font-semibold text-gray-100 mb-8">
            How can I help you?
          </h2>

          <ChatInput
            inputRef={inputRef}
            input={input}
            setInput={setInput}
            onSend={() => sendMessage(input)}
            onKeyDown={handleKeyDown}
            streaming={streaming}
            placeholder={placeholder}
            centered
          />

          <div className="relative mt-2.5 self-start flex items-center gap-1.5 flex-wrap">
            <span className="text-[11px] text-gray-500">Agent</span>
            <button
              data-tier-toggle
              onClick={() => setTierOpen((v) => !v)}
              className="flex items-center gap-1 text-[11px] text-gray-400 hover:text-gray-200 bg-gray-800/60 hover:bg-gray-700/60 border border-gray-700/60 rounded-md px-2 py-0.5 transition"
            >
              {tier}
              <ChevronDown size={10} />
            </button>
            {tierOpen && (
              <div className="absolute top-full left-0 mt-1 bg-gray-800 border border-gray-700 rounded-lg shadow-xl z-50 py-1 min-w-[80px]">
                {TIERS.map((t) => (
                  <button
                    key={t}
                    onClick={() => { setTier(t); setTierOpen(false); }}
                    className={`block w-full text-left px-3 py-1.5 text-xs transition ${
                      t === tier ? "text-blue-400 bg-blue-500/10" : "text-gray-300 hover:bg-gray-700/60"
                    }`}
                  >
                    {t}
                  </button>
                ))}
              </div>
            )}
            <ConnectorPills available={availableConnectors} selected={selectedConnectors} onRemove={removeConnector} locked={false} />
            {availableConnectors.length > 0 && (
              <ConnectorPicker available={availableConnectors} selected={selectedConnectors} onToggle={toggleConnector} disabled={false} />
            )}
          </div>

          <div className="w-full mt-8">
            <p className="text-xs text-gray-500 mb-3 px-0.5">Get started</p>
            <div className="grid grid-cols-3 gap-3">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s.question}
                  onClick={() => sendMessage(s.question)}
                  className="flex items-center gap-2.5 text-left text-sm text-gray-300 bg-gray-800/50 hover:bg-gray-800 border border-gray-700/50 hover:border-gray-600 rounded-xl px-4 py-3 transition"
                >
                  <s.icon size={16} className="text-blue-400 flex-shrink-0" />
                  <span>{s.label}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* Header */}
      <div className="px-6 py-3 border-b border-gray-800 flex-shrink-0 flex items-center justify-between">
        <div className="flex items-center gap-3 flex-wrap">
          <h2 className="text-sm font-medium text-gray-400">Chat</h2>
          <div className="relative">
            <button
              data-tier-toggle
              onClick={() => setTierOpen((v) => !v)}
              disabled={streaming}
              className="flex items-center gap-1 text-[11px] text-gray-400 hover:text-gray-200 bg-gray-800/60 hover:bg-gray-700/60 border border-gray-700/60 rounded-md px-2 py-0.5 transition disabled:opacity-40"
            >
              {tier}
              <ChevronDown size={10} />
            </button>
            {tierOpen && (
              <div className="absolute top-full left-0 mt-1 bg-gray-800 border border-gray-700 rounded-lg shadow-xl z-50 py-1 min-w-[80px]">
                {TIERS.map((t) => (
                  <button
                    key={t}
                    onClick={() => { setTier(t); setTierOpen(false); }}
                    className={`block w-full text-left px-3 py-1.5 text-xs transition ${
                      t === tier ? "text-blue-400 bg-blue-500/10" : "text-gray-300 hover:bg-gray-700/60"
                    }`}
                  >
                    {t}
                  </button>
                ))}
              </div>
            )}
          </div>
          <ConnectorPills available={availableConnectors} selected={selectedConnectors} onRemove={removeConnector} locked={connectorsLocked} />
        </div>
        <div className="flex items-center gap-3">
          {totalCost > 0 && (
            <span className="text-[11px] text-emerald-400 tabular-nums">{formatCost(totalCost)}</span>
          )}
          <button
            onClick={handleNewChat}
            className="text-xs text-gray-500 hover:text-gray-300 inline-flex items-center gap-1.5 transition"
          >
            <RotateCcw size={12} />
            New chat
          </button>
        </div>
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-6">
        <div className="max-w-3xl mx-auto space-y-4">
          {messages.map((msg, i) => (
            <MessageBubble key={i} msg={msg} />
          ))}
          {streaming && <StreamingBubble text={streamText} thinkingText={thinkingText} />}
        </div>
      </div>

      {/* Input */}
      <div className="border-t border-gray-800 px-6 py-3 flex-shrink-0">
        <ChatInput
          inputRef={inputRef}
          input={input}
          setInput={setInput}
          onSend={() => sendMessage(input)}
          onKeyDown={handleKeyDown}
          streaming={streaming}
          placeholder={placeholder}
        />
      </div>
    </div>
  );
}


/* ── Floating flow chat window (persisted via localStorage) ─── */

const FLOW_CHAT_KEY = "llmflows-flow-chat:";

interface FlowChatState {
  messages: Message[];
  sessionId: string | null;
  tier: Tier;
  totalCost: number;
}

function loadFlowChat(flowId: string): FlowChatState {
  try {
    const raw = localStorage.getItem(FLOW_CHAT_KEY + flowId);
    if (!raw) return { messages: [], sessionId: null, tier: "max", totalCost: 0 };
    const p = JSON.parse(raw);
    return { messages: p.messages || [], sessionId: p.sessionId || null, tier: p.tier || "max", totalCost: p.totalCost || 0 };
  } catch { return { messages: [], sessionId: null, tier: "max", totalCost: 0 }; }
}

function saveFlowChat(flowId: string, state: FlowChatState) {
  try { localStorage.setItem(FLOW_CHAT_KEY + flowId, JSON.stringify(state)); }
  catch { /* quota exceeded */ }
}

export function FlowChatWindow({ spaceId, flowId, flowName, open, onClose }: {
  spaceId: string; flowId: string; flowName: string; open: boolean; onClose: () => void;
}) {
  const initial = useRef(loadFlowChat(flowId));
  const [messages, setMessages] = useState<Message[]>(initial.current.messages);
  const [sessionId, setSessionId] = useState<string | null>(initial.current.sessionId);
  const [tier, setTier] = useState<Tier>(initial.current.tier);
  const [tierOpen, setTierOpen] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [input, setInput] = useState("");
  const [streamText, setStreamText] = useState("");
  const [thinkingText, setThinkingText] = useState("");
  const [totalCost, setTotalCost] = useState(initial.current.totalCost);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    saveFlowChat(flowId, { messages, sessionId, tier, totalCost });
  }, [flowId, messages, sessionId, tier, totalCost]);

  const scrollToBottom = useCallback(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, []);

  useEffect(scrollToBottom, [messages, streamText, thinkingText, scrollToBottom]);
  useEffect(() => { if (open) setTimeout(() => inputRef.current?.focus(), 150); }, [open]);

  // Close tier dropdown on outside click
  useEffect(() => {
    if (!tierOpen) return;
    const close = (e: MouseEvent) => {
      if ((e.target as HTMLElement).closest?.("[data-flow-tier]")) return;
      setTierOpen(false);
    };
    requestAnimationFrame(() => document.addEventListener("click", close));
    return () => document.removeEventListener("click", close);
  }, [tierOpen]);

  const sendMessage = useCallback(
    async (text: string) => {
      if (!text.trim() || streaming) return;
      setMessages((prev) => [...prev, { role: "user", content: text.trim() }]);
      setInput("");
      setStreaming(true);
      setStreamText("");
      setThinkingText("");

      const abort = new AbortController();
      abortRef.current = abort;

      try {
        const response = await api.sendChat(text.trim(), spaceId, sessionId, tier, flowName);
        if (!response.ok) {
          const errText = await response.text();
          setMessages((prev) => [...prev, { role: "assistant", content: `Error: ${response.status} — ${errText}` }]);
          setStreaming(false);
          return;
        }

        let accumulated = "";
        let accumulatedThinking = "";
        for await (const event of readChatStream(response)) {
          if (abort.signal.aborted) break;
          if (event.type === "thinking_delta") {
            accumulatedThinking += event.text;
            setThinkingText(accumulatedThinking);
          } else if (event.type === "text_delta") {
            accumulated += event.text;
            setStreamText(accumulated);
          } else if (event.type === "done") {
            if (event.session_id) setSessionId(event.session_id);
            if (event.cost_usd) setTotalCost((prev) => prev + event.cost_usd!);
          }
        }
        if (accumulated.trim()) {
          setMessages((prev) => [...prev, { role: "assistant", content: accumulated.trim() }]);
        }
      } catch (err) {
        if (!abort.signal.aborted) {
          setMessages((prev) => [
            ...prev,
            { role: "assistant", content: `Connection error: ${err instanceof Error ? err.message : String(err)}` },
          ]);
        }
      } finally {
        setStreaming(false);
        setStreamText("");
        setThinkingText("");
        abortRef.current = null;
        setTimeout(() => inputRef.current?.focus(), 50);
      }
    },
    [streaming, spaceId, sessionId, tier, flowName],
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(input); }
    },
    [input, sendMessage],
  );

  const handleNewChat = useCallback(() => {
    if (streaming && abortRef.current) abortRef.current.abort();
    if (sessionId) api.deleteChatSession(sessionId).catch(() => {});
    setMessages([]);
    setSessionId(null);
    setStreaming(false);
    setStreamText("");
    setThinkingText("");
    setInput("");
    setTotalCost(0);
    localStorage.removeItem(FLOW_CHAT_KEY + flowId);
  }, [streaming, sessionId, flowId]);

  const empty = messages.length === 0 && !streaming;

  return (
    <div
      className={`fixed bottom-20 right-6 z-50 w-[420px] h-[560px] bg-gray-900 border border-gray-700 rounded-2xl shadow-2xl flex flex-col overflow-hidden transition-all duration-200 origin-bottom-right ${
        open ? "scale-100 opacity-100" : "scale-95 opacity-0 pointer-events-none"
      }`}
    >
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2.5">
          <span className="text-sm font-medium text-gray-200">Chat</span>
          <span className="text-[10px] text-gray-500 font-mono truncate max-w-[140px]" title={flowName}>{flowName}</span>
        </div>
        <div className="flex items-center gap-2">
          {totalCost > 0 && (
            <span className="text-[10px] text-emerald-400 tabular-nums">{formatCost(totalCost)}</span>
          )}
          {messages.length > 0 && (
            <button onClick={handleNewChat} disabled={streaming}
              className="text-[11px] text-blue-400 hover:text-blue-300 inline-flex items-center gap-1 disabled:opacity-40">
              <RotateCcw size={10} /> New chat
            </button>
          )}
          <button onClick={onClose} className="text-gray-500 hover:text-gray-300 text-lg leading-none px-1">✕</button>
        </div>
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-3">
        {empty ? (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <p className="text-sm text-gray-400 mb-1">What do you need help with?</p>
            <p className="text-xs text-gray-600">Fix issues, improve steps, or ask anything about this flow.</p>
          </div>
        ) : (
          <div className="space-y-3">
            {messages.map((msg, i) => (
              <MessageBubble key={i} msg={msg} />
            ))}
            {streaming && <StreamingBubble text={streamText} thinkingText={thinkingText} />}
          </div>
        )}
      </div>

      {/* Input */}
      <div className="border-t border-gray-800 px-4 py-2.5 shrink-0">
        <div className="flex items-end gap-2 bg-gray-800/80 border border-gray-700 rounded-xl px-3 py-1.5 focus-within:ring-1 focus-within:ring-gray-600 focus-within:border-gray-600">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            onInput={(e) => {
              const t = e.currentTarget;
              t.style.height = "auto";
              t.style.height = Math.min(t.scrollHeight, 120) + "px";
            }}
            placeholder="Ask about this flow..."
            rows={1}
            disabled={streaming}
            className="flex-1 bg-transparent text-sm text-gray-200 placeholder:text-gray-500 focus:outline-none resize-none overflow-hidden disabled:opacity-50 py-1"
          />
          <button
            onClick={() => sendMessage(input)}
            disabled={streaming || !input.trim()}
            className="p-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-30 disabled:bg-gray-700 transition flex-shrink-0 mb-0.5"
          >
            {streaming ? <Loader2 size={14} className="animate-spin" /> : <ArrowUp size={14} />}
          </button>
        </div>
        {/* Tier selector */}
        <div className="relative mt-1.5 flex items-center gap-1.5">
          <span className="text-[10px] text-gray-600">Agent</span>
          <button
            data-flow-tier
            onClick={() => setTierOpen((v) => !v)}
            disabled={streaming}
            className="flex items-center gap-1 text-[10px] text-gray-500 hover:text-gray-300 bg-gray-800/60 hover:bg-gray-700/60 border border-gray-700/60 rounded px-1.5 py-0.5 transition disabled:opacity-40"
          >
            {tier}
            <ChevronDown size={9} />
          </button>
          {tierOpen && (
            <div className="absolute bottom-full left-0 mb-1 bg-gray-800 border border-gray-700 rounded-lg shadow-xl z-50 py-1 min-w-[72px]">
              {TIERS.map((t) => (
                <button
                  key={t}
                  onClick={() => { setTier(t); setTierOpen(false); }}
                  className={`block w-full text-left px-3 py-1.5 text-[11px] transition ${
                    t === tier ? "text-blue-400 bg-blue-500/10" : "text-gray-300 hover:bg-gray-700/60"
                  }`}
                >
                  {t}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
