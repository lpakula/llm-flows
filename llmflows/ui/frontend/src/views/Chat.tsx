import { useState, useRef, useEffect, useCallback } from "react";
import { RotateCcw, Loader2, Workflow, Rocket, HelpCircle, ArrowUp, ChevronDown } from "lucide-react";
import { api } from "@/api/client";
import { useApp } from "@/App";
import { MarkdownContent } from "@/components/MarkdownContent";
import { formatCost } from "@/lib/format";
import type { ChatEvent } from "@/api/types";

type Message = { role: "user" | "assistant"; content: string };

const SUGGESTIONS = [
  { icon: Rocket, label: "How to start?", question: "How do I get started? Just the essential setup steps. Keep it short." },
  { icon: Workflow, label: "Help me build a flow", question: "Help me build a flow" },
  { icon: HelpCircle, label: "How it works", question: "How does llm-flows work?" },
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

function StreamingBubble({ text }: { text: string }) {
  return (
    <div className="flex justify-start">
      <div className="max-w-[85%]">
        <div className="bg-gray-800/50 border border-gray-700/50 rounded-xl px-4 py-3">
          {text ? (
            <MarkdownContent
              text={text + "\u258C"}
              className="text-sm text-gray-200"
            />
          ) : (
            <div className="flex items-center gap-2 text-sm text-gray-500">
              <Loader2 size={12} className="animate-spin" />
              Thinking...
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

const TIERS = ["mini", "normal", "max"] as const;
type Tier = (typeof TIERS)[number];

export function ChatView() {
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
  const [tier, setTier] = useState<Tier>("max");
  const [totalCost, setTotalCost] = useState(0);
  const [tierOpen, setTierOpen] = useState(false);

  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  const scrollToBottom = useCallback(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, []);

  useEffect(scrollToBottom, [messages, streamText, scrollToBottom]);

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
    async (text: string) => {
      if (!text.trim() || streaming) return;

      const userMsg: Message = { role: "user", content: text.trim() };
      setMessages((prev) => [...prev, userMsg]);
      setInput("");
      setStreaming(true);
      setStreamText("");

      const abort = new AbortController();
      abortRef.current = abort;

      try {
        const response = await api.sendChat(
          text.trim(),
          selectedSpaceId,
          sessionId,
          tier,
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

        for await (const event of readChatStream(response)) {
          if (abort.signal.aborted) break;

          if (event.type === "text_delta") {
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
        abortRef.current = null;
        setTimeout(() => inputRef.current?.focus(), 50);
      }
    },
    [streaming, selectedSpaceId, sessionId, tier],
  );

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

          <div className="relative mt-2.5 self-start flex items-center gap-1.5">
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
        <div className="flex items-center gap-3">
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
          {streaming && <StreamingBubble text={streamText} />}
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
