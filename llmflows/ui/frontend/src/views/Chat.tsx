import { useState, useRef, useEffect, useCallback } from "react";
import { RotateCcw, Send, Loader2 } from "lucide-react";
import { api } from "@/api/client";
import { useApp } from "@/App";
import { MarkdownContent } from "@/components/MarkdownContent";
import type { ChatEvent } from "@/api/types";

interface Message {
  role: "user" | "assistant";
  content: string;
}

const SAMPLE_QUESTIONS = [
  "How does llm-flows work?",
  "I want to build a flow",
  "What are gates and IFs?",
  "Show me a flow example",
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

function WelcomeScreen({ onSend }: { onSend: (q: string) => void }) {
  return (
    <div className="flex flex-col items-center justify-center h-full select-none">
      <div className="text-center max-w-md">
        <h3 className="text-lg font-semibold text-gray-200 mb-2">
          How can I help?
        </h3>
        <p className="text-sm text-gray-500 mb-8">
          I can explain how llm-flows works and build automations for you.
        </p>
        <div className="grid grid-cols-2 gap-2.5">
          {SAMPLE_QUESTIONS.map((q) => (
            <button
              key={q}
              onClick={() => onSend(q)}
              className="text-left text-sm text-gray-300 bg-gray-800/60 hover:bg-gray-800 border border-gray-700/60 hover:border-gray-600 rounded-lg px-4 py-3 transition"
            >
              {q}
            </button>
          ))}
        </div>
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
  const { selectedSpaceId } = useApp();
  const [messages, setMessages] = useState<Message[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
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
    setMessages([]);
    setSessionId(null);
    setStreaming(false);
    setStreamText("");
    setInput("");
  }, [streaming, sessionId]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage(input);
      }
    },
    [input, sendMessage],
  );

  const showWelcome = messages.length === 0 && !streaming;

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* Header */}
      <div className="px-6 py-4 border-b border-gray-800 flex-shrink-0 flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold">Chat</h2>
          <p className="text-sm text-gray-500">
            Ask questions about llm-flows or build a flow.
          </p>
        </div>
        {messages.length > 0 && (
          <button
            onClick={handleNewChat}
            className="text-xs text-gray-500 hover:text-gray-300 inline-flex items-center gap-1.5 transition"
          >
            <RotateCcw size={12} />
            New chat
          </button>
        )}
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-6">
        {showWelcome ? (
          <WelcomeScreen onSend={sendMessage} />
        ) : (
          <div className="max-w-3xl mx-auto space-y-4">
            {messages.map((msg, i) => (
              <MessageBubble key={i} msg={msg} />
            ))}
            {streaming && <StreamingBubble text={streamText} />}
          </div>
        )}
      </div>

      {/* Input */}
      <div className="border-t border-gray-800 px-6 py-3 flex-shrink-0">
        <div className="max-w-3xl mx-auto flex items-end gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            onInput={(e) => {
              const t = e.currentTarget;
              t.style.height = "auto";
              t.style.height = Math.min(t.scrollHeight, 160) + "px";
            }}
            placeholder={
              selectedSpaceId
                ? "Ask about llm-flows or describe a flow to build..."
                : "Ask about llm-flows... (select a space to create flows)"
            }
            rows={1}
            disabled={streaming}
            className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder:text-gray-600 focus:outline-none focus:ring-1 focus:ring-gray-600 focus:border-gray-600 resize-none overflow-hidden disabled:opacity-50"
          />
          <button
            onClick={() => sendMessage(input)}
            disabled={streaming || !input.trim()}
            className="p-2 rounded-lg text-gray-400 hover:text-gray-200 hover:bg-gray-800 disabled:opacity-30 disabled:hover:bg-transparent transition flex-shrink-0"
          >
            {streaming ? (
              <Loader2 size={16} className="animate-spin" />
            ) : (
              <Send size={16} />
            )}
          </button>
        </div>
        <div className="max-w-3xl mx-auto mt-1.5 px-1">
          <span className="text-[10px] text-gray-700">
            Enter to send, Shift+Enter for new line
          </span>
        </div>
      </div>
    </div>
  );
}
