export type SourceData = {
  search_suggestions?: string;
  retrieved?: string;
  last_refresh?: string;
  freshness?: string;
  refresh_error?: string;
  citations?: { title: string; url: string; excerpt?: string }[];
  items?: {
    title: string;
    url: string;
    source: string;
    published: string;
    fetched: string;
  }[];
  apple_maps_url?: string;
  google_maps_url?: string;
};
export function sourceURL(value: string): string | null {
  try {
    const u = new URL(value);
    return u.protocol === "https:" && !u.username && !u.password
      ? u.href
      : null;
  } catch {
    return null;
  }
}
export function SourceCards({ data }: { data: SourceData }) {
  const links = data.citations || data.items || [];
  return (
    <aside className="source-cards" aria-label="Retrieved sources">
      {!!links.length && (
        <p className="source-meta">
          Sources · Retrieved{" "}
          {data.retrieved || data.last_refresh || "time unavailable"}
          {data.freshness === "stale_or_offline_cache"
            ? " · Dated offline/stale cache"
            : ""}
        </p>
      )}
      {data.refresh_error && <p role="status">{data.refresh_error}</p>}
      {links.slice(0, 6).map(
        (item, i) =>
          sourceURL(item.url) && (
            <a
              key={item.url + i}
              href={sourceURL(item.url)!}
              target="_blank"
              rel="noopener noreferrer"
            >
              <strong>{item.title}</strong>
              {"published" in item && (
                <small>
                  {item.source} · Published {item.published} · Fetched{" "}
                  {item.fetched}
                </small>
              )}
            </a>
          ),
      )}
      {data.search_suggestions && (
        <iframe
          title="Google Search suggestions"
          sandbox="allow-popups allow-popups-to-escape-sandbox"
          referrerPolicy="no-referrer"
          srcDoc={data.search_suggestions}
        />
      )}
      {data.apple_maps_url && sourceURL(data.apple_maps_url) && (
        <a href={data.apple_maps_url} target="_blank" rel="noopener noreferrer">
          Open route in Apple Maps
        </a>
      )}
      {data.google_maps_url && sourceURL(data.google_maps_url) && (
        <a
          href={data.google_maps_url}
          target="_blank"
          rel="noopener noreferrer"
        >
          Open route in Google Maps
        </a>
      )}
    </aside>
  );
}
