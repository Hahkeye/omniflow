import { preStyle } from "./styles";

export default function DigestTab({
  digestDays,
  setDigestDays,
  digestLoading,
  digestMd,
  digestPath,
  onBuild,
}) {
  return (
    <div>
      <p style={{ color: "#666", fontSize: 14 }}>
        Roll up recent sessions into decisions, action items, and summaries.
      </p>
      <div
        style={{
          display: "flex",
          gap: 8,
          alignItems: "center",
          marginBottom: 12,
        }}
      >
        <label>
          Active days{" "}
          <input
            type="number"
            min={1}
            max={60}
            value={digestDays}
            onChange={(e) => setDigestDays(parseInt(e.target.value, 10) || 7)}
            style={{ width: 60 }}
          />
        </label>
        <button onClick={onBuild} disabled={digestLoading}>
          {digestLoading ? "Building…" : "Build digest"}
        </button>
      </div>
      {digestPath && (
        <p style={{ fontSize: 13, color: "#555" }}>Saved: {digestPath}</p>
      )}
      <pre style={{ ...preStyle, maxHeight: 520, overflow: "auto" }}>
        {digestMd || "Click Build digest to generate."}
      </pre>
    </div>
  );
}
