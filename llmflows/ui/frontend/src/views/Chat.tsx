import { useState, useRef, useEffect, useCallback } from "react";
import { RotateCcw, Loader2, Workflow, Rocket, HelpCircle, ArrowUp } from "lucide-react";
import { api } from "@/api/client";
import { useApp } from "@/App";
import { MarkdownContent } from "@/components/MarkdownContent";
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

  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  const scrollToBottom = useCallback(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, []);

  useEffect(scrollToBottom, [messages, streamText, scrollToBottom]);

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
    [streaming, selectedSpaceId, sessionId],
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
        <h2 className="text-sm font-medium text-gray-400">Chat</h2>
        <button
          onClick={handleNewChat}
          className="text-xs text-gray-500 hover:text-gray-300 inline-flex items-center gap-1.5 transition"
        >
          <RotateCcw size={12} />
          New chat
        </button>
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
