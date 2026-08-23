import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { apiClient } from "../api/client";
import { CHAT_CATEGORIES, type ChatCategory, type ChatSubtopic } from "./chatSuggestions";
import "./ChatPanel.css";

type Message = { role: "user" | "assistant" | "error"; text: string };
type Phase = "category" | "subtopic" | "symbol";

export function ChatPanel({ symbols = [] }: { symbols?: string[] } = {}) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);

  const [phase, setPhase] = useState<Phase>("category");
  const [activeCategory, setActiveCategory] = useState<ChatCategory | null>(null);
  const [activeSubtopic, setActiveSubtopic] = useState<ChatSubtopic | null>(null);
  const [selectedSymbols, setSelectedSymbols] = useState<string[]>([]);

  const resetGuide = () => {
    setPhase("category");
    setActiveCategory(null);
    setActiveSubtopic(null);
    setSelectedSymbols([]);
  };

  const sendQuestion = async (question: string, questionSymbols: string[]) => {
    setMessages((m) => [...m, { role: "user", text: question }]);
    resetGuide();
    setSending(true);
    try {
      const { answer } = await apiClient.sendChatMessage(question, questionSymbols);
      setMessages((m) => [...m, { role: "assistant", text: answer }]);
    } catch {
      setMessages((m) => [...m, { role: "error", text: "Something went wrong — try again." }]);
    } finally {
      setSending(false);
    }
  };

  const send = () => {
    if (!input.trim()) return;
    const question = input;
    setInput("");
    sendQuestion(question, symbols);
  };

  const pickCategory = (category: ChatCategory) => {
    setActiveCategory(category);
    setActiveSubtopic(null);
    setSelectedSymbols([]);
    setPhase(category.skipSubtopic ? "symbol" : "subtopic");
  };

  const pickSubtopic = (subtopic: ChatSubtopic) => {
    setActiveSubtopic(subtopic);
    setSelectedSymbols([]);
    if (subtopic.skipSymbol) {
      sendQuestion(subtopic.question(symbols), symbols);
    } else {
      setPhase("symbol");
    }
  };

  const pickSymbol = (symbol: string) => {
    if (selectedSymbols.includes(symbol) || !activeCategory) return;
    const next = [...selectedSymbols, symbol];
    const need = activeSubtopic ? activeSubtopic.need : (activeCategory.need ?? 1);
    if (next.length >= need) {
      const questionFn = activeSubtopic ? activeSubtopic.question : activeCategory.question!;
      sendQuestion(questionFn(next), next);
    } else {
      setSelectedSymbols(next);
    }
  };

  const backToCategories = () => resetGuide();
  const backToSubtopics = () => {
    setPhase("subtopic");
    setActiveSubtopic(null);
    setSelectedSymbols([]);
  };

  const symbolNeed = activeSubtopic ? activeSubtopic.need : (activeCategory?.need ?? 1);

  return (
    <div className="chat-panel">
      <h2 className="chat-title">Chat</h2>
      <div className="chat-messages">
        {messages.map((m, i) =>
          m.role === "assistant" ? (
            <div key={i} className="chat-bubble chat-bubble-assistant chat-markdown">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  table: ({ children }) => (
                    <div className="chat-markdown-table-wrap">
                      <table>{children}</table>
                    </div>
                  ),
                }}
              >
                {m.text}
              </ReactMarkdown>
            </div>
          ) : (
            <p key={i} className={`chat-bubble chat-bubble-${m.role}`}>{m.text}</p>
          )
        )}
      </div>

      {!sending && (
        <div className="chat-suggest">
          {phase === "category" && (
            <>
              <p className="chat-suggest-label">
                {messages.length ? "Ask about something else" : "What do you want to know?"}
              </p>
              <div className="chat-suggest-row">
                {CHAT_CATEGORIES.map((category) => (
                  <button key={category.id} className="chat-chip" onClick={() => pickCategory(category)}>
                    {category.label}
                  </button>
                ))}
              </div>
            </>
          )}

          {phase === "subtopic" && activeCategory?.subtopics && (
            <>
              <p className="chat-suggest-label">
                <span className="chat-suggest-crumb">{activeCategory.label} — </span>
                pick a question
                <button className="chat-suggest-back" onClick={backToCategories}>← topics</button>
              </p>
              <div className="chat-suggest-row">
                {activeCategory.subtopics.map((subtopic) => (
                  <button key={subtopic.id} className="chat-chip" onClick={() => pickSubtopic(subtopic)}>
                    {subtopic.label}
                  </button>
                ))}
              </div>
            </>
          )}

          {phase === "symbol" && activeCategory && (
            <>
              <p className="chat-suggest-label">
                <span className="chat-suggest-crumb">
                  {activeCategory.label}{activeSubtopic ? ` / ${activeSubtopic.label}` : ""} —{" "}
                </span>
                {symbolNeed === 2
                  ? selectedSymbols.length === 0
                    ? "pick two stocks to compare"
                    : `pick one more (${selectedSymbols[0]} selected)`
                  : "pick a stock"}
                <button
                  className="chat-suggest-back"
                  onClick={activeCategory.skipSubtopic ? backToCategories : backToSubtopics}
                >
                  {activeCategory.skipSubtopic ? "← topics" : "← questions"}
                </button>
              </p>
              <div className="chat-suggest-row">
                {symbols.length === 0 && (
                  <span className="chat-suggest-empty">your watchlist is empty — add a symbol to ask about it</span>
                )}
                {symbols.map((symbol) => (
                  <button
                    key={symbol}
                    className={`chat-chip chat-chip-symbol${selectedSymbols.includes(symbol) ? " chat-chip-selected" : ""}`}
                    onClick={() => pickSymbol(symbol)}
                  >
                    {symbol}
                  </button>
                ))}
              </div>
            </>
          )}
        </div>
      )}

      <div className="chat-input-row">
        <input
          className="chat-input"
          placeholder="Ask about your watchlist..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
        />
        <button className="chat-send" onClick={send}>Send</button>
      </div>
    </div>
  );
}
