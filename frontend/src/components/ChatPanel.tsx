import { useState } from "react";
import { apiClient } from "../api/client";

type Message = { role: "user" | "assistant"; text: string };

export function ChatPanel() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");

  const send = async () => {
    const question = input;
    setMessages((m) => [...m, { role: "user", text: question }]);
    setInput("");
    const { answer } = await apiClient.sendChatMessage(question, []);
    setMessages((m) => [...m, { role: "assistant", text: answer }]);
  };

  return (
    <div>
      <h2>Chat</h2>
      <div>{messages.map((m, i) => <p key={i}><strong>{m.role}:</strong> {m.text}</p>)}</div>
      <input
        placeholder="Ask about your watchlist..."
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && send()}
      />
      <button onClick={send}>Send</button>
    </div>
  );
}
