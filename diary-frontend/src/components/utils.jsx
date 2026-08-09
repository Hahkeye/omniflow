export function segmentStart(seg) {
  return seg.start ?? seg.start_time ?? 0;
}

export function segmentEnd(seg) {
  return seg.end ?? seg.end_time ?? 0;
}

export function formatWhen(entry) {
  return entry.created_at || entry.id || "";
}

export function highlightSnippet(snippet) {
  if (!snippet) return null;
  const parts = String(snippet).split(/(\*\*[^*]+\*\*)/g);
  return parts.map((p, i) => {
    if (p.startsWith("**") && p.endsWith("**")) {
      return (
        <mark key={i} style={{ background: "#fef08a", padding: "0 2px" }}>
          {p.slice(2, -2)}
        </mark>
      );
    }
    return <span key={i}>{p}</span>;
  });
}
