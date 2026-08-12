import { useEffect, useState } from "react";

export function useSSE<T>(url: string): { events: T[] } {
  const [events, setEvents] = useState<T[]>([]);

  useEffect(() => {
    const source = new EventSource(`/api${url}`);
    source.onmessage = (event) => {
      setEvents((prev) => [...prev, JSON.parse(event.data) as T]);
    };
    return () => source.close();
  }, [url]);

  return { events };
}
