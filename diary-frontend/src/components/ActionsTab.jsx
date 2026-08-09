export default function ActionsTab({
  actionsOpen,
  actionsStatus,
  onRefresh,
  onComplete,
}) {
  return (
    <div>
      <p style={{ color: "#666", fontSize: 14 }}>
        Open action items across all sessions. Synced from analyses.
      </p>
      <button onClick={onRefresh} style={{ marginBottom: 12 }}>
        Refresh / sync
      </button>
      <p style={{ fontSize: 13, color: "#555" }}>{actionsStatus}</p>
      <div style={{ border: "1px solid #ddd", borderRadius: 8 }}>
        {actionsOpen.length === 0 && (
          <p style={{ padding: 12, color: "#888" }}>No open actions.</p>
        )}
        {actionsOpen.map((it) => (
          <div
            key={it.id}
            style={{
              padding: "10px 12px",
              borderBottom: "1px solid #eee",
              display: "flex",
              gap: 8,
              alignItems: "flex-start",
            }}
          >
            <button onClick={() => onComplete(it.id)} title="Mark done">
              ☐
            </button>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 14 }}>{it.text}</div>
              <div style={{ fontSize: 12, color: "#888" }}>
                {it.id} · {it.entry_id || "manual"}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
