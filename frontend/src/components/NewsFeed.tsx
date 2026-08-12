import { useSSE } from "../hooks/useSSE";

type NewsEvent = { agent: string; status: string; timestamp: string; reason: string };

export function NewsFeed() {
  const { events } = useSSE<NewsEvent>("/stream/news");
  return (
    <div>
      <h2>Live News Feed</h2>
      <ul>
        {events.map((e, i) => (
          <li key={i}>{e.timestamp}: {e.agent} ({e.reason})</li>
        ))}
      </ul>
    </div>
  );
}
