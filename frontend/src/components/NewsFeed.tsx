import { useSSE } from "../hooks/useSSE";

type NewsEvent = {
  symbol: string;
  uuid?: string;
  title?: string;
  description?: string;
  published_at?: string;
  url?: string;
  source?: string;
};

export function NewsFeed() {
  const { events } = useSSE<NewsEvent>("/stream/news");
  return (
    <div>
      <h2>Live News Feed</h2>
      <ul>
        {events.map((e, i) => (
          <li key={e.uuid ?? i}>
            <strong>{e.symbol}</strong> — {e.title ?? "(untitled)"}
            {e.published_at && <span> ({e.published_at})</span>}
            {e.source && <span>, {e.source}</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}
