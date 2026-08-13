import { useSSE } from "../hooks/useSSE";
import "./NewsFeed.css";

type NewsEvent = {
  symbol: string;
  uuid?: string;
  title?: string;
  description?: string;
  published_at?: string;
  url?: string;
  source?: string;
};

const MAX_VISIBLE_ARTICLES = 20;

function timeAgo(publishedAt?: string): string {
  if (!publishedAt) return "";
  const ms = Date.now() - new Date(publishedAt).getTime();
  const minutes = Math.floor(ms / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export function NewsFeed({ symbols }: { symbols?: string[] } = {}) {
  const { events } = useSSE<NewsEvent>("/stream/news");
  // Dedup by uuid: the backend's per-connection dedup state resets on every SSE
  // reconnect (EventSource auto-reconnects on drops), so cached articles can be
  // re-emitted as if new. Events without a uuid can't be deduped, so they fall
  // back to a unique per-index key and are kept as-is.
  const deduped = new Map<string, NewsEvent>();
  events.forEach((e, i) => {
    deduped.set(e.uuid ?? `__no-uuid-${i}`, e);
  });
  // `events` only ever grows for the life of this SSE connection -- an article for a symbol
  // that's since been removed from the watchlist stays in it forever otherwise, since the
  // backend has no way to retract an already-sent event. Re-filtering against the current
  // watchlist on every render is what actually drops it from view.
  const sorted = [...deduped.values()]
    .filter((e) => symbols === undefined || symbols.includes(e.symbol))
    .sort((a, b) => (b.published_at ?? "").localeCompare(a.published_at ?? ""))
    .slice(0, MAX_VISIBLE_ARTICLES);

  return (
    <div className="news-panel">
      <h2 className="news-title">
        Latest news <span className="news-live-dot" />
      </h2>
      <div>
        {sorted.map((e, i) => (
          <div className="news-item" key={e.uuid ?? i}>
            <div className="news-item-header">
              <span>{e.symbol}</span>
              {e.published_at && <span className="news-time">{timeAgo(e.published_at)}</span>}
            </div>
            <div className="news-headline">
              {e.title ?? "(untitled)"}
              {e.source && ` — ${e.source}`}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
