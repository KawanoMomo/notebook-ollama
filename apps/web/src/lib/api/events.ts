export interface SourceStatusEvent {
  source_id: string;
  status: string;
  [key: string]: unknown;
}

export function openNotebookEvents(
  notebookId: string,
  onEvent: (ev: SourceStatusEvent) => void,
  onError?: (e: Event) => void,
): () => void {
  const url = `/api/notebooks/${notebookId}/events`;
  const es = new EventSource(url);
  es.addEventListener('source_status', (e) => {
    const ev = e as MessageEvent;
    try {
      onEvent(JSON.parse(ev.data) as SourceStatusEvent);
    } catch {
      // ignore
    }
  });
  if (onError) es.addEventListener('error', onError);
  return () => es.close();
}
