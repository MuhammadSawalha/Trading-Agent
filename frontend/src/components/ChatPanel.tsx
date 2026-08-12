import { useState } from "react";
import { apiClient } from "../api/client";
import "./ChatPanel.css";

type Message = { role: "user" | "assistant" | "error"; text: string };

export function ChatPanel({ symbols = [] }: { symbols?: string[] } = {}) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");

  const send = async () => {
    const question = input;
    setMessages((m) => [...m, { role: "user", text: question }]);
    setInput("");
    try {
      const { answer } = await apiClient.sendChatMessage(question, symbols);
      setMessages((m) => [...m, { role: "assistant", text: answer }]);
    } catch {
      setMessages((m) => [...m, { role: "error", text: "Something went wrong — try again." }]);
    }
  };

  return (
    <div className="chat-panel">
      <h2 className="chat-title">Chat</h2>
      <div className="chat-messages">
        {messages.map((m, i) => (
          <p key={i} className={`chat-bubble chat-bubble-${m.role}`}>{m.text}</p>
        ))}
      </div>
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
