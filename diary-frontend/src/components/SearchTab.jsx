import { convertFileSrc } from "@tauri-apps/api/core";
import { chipStyle, preStyle } from "./styles";
import { highlightSnippet } from "./utils";

export default function SearchTab({
  searchQuery,
  setSearchQuery,
  searchPerson,
  setSearchPerson,
  searchHits,
  searchStatus,
  searchLoading,
  searchSelectedId,
  searchHitDetail,
  roster,
  activeSegIdx,
  setActiveSegIdx,
  audioRef,
  onSearch,
  onSelectHit,
  onOpenInHistory,
  seekTo,
}) {
  const searchAudioSrc =
    searchHitDetail?.audio_path || searchHitDetail?.has_audio
      ? searchHitDetail.audio_path
        ? convertFileSrc(searchHitDetail.audio_path)
        : null
      : null;
  const searchSegs = searchHitDetail?.segments || [];

  return (
    <div>
      <div
        style={{
          display: "flex",
          gap: 8,
          marginBottom: 12,
          flexWrap: "wrap",
          alignItems: "center",
        }}
      >
        <input
          placeholder='Search… e.g. budget or "next week"'
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && onSearch()}
          style={{ flex: 2, minWidth: 180, padding: 8 }}
        />
        <input
          placeholder="Person filter"
          value={searchPerson}
          onChange={(e) => setSearchPerson(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && onSearch()}
          style={{ flex: 1, minWidth: 100, padding: 8 }}
        />
        <button onClick={onSearch} disabled={searchLoading}>
          {searchLoading ? "Searching…" : "Search"}
        </button>
      </div>
      {roster.people?.length > 0 && (
        <div style={{ fontSize: 12, marginBottom: 8 }}>
          {roster.people.map((p) => (
            <button
              key={p.id}
              onClick={() => setSearchPerson(p.name)}
              style={chipStyle(searchPerson === p.name)}
            >
              {p.name}
            </button>
          ))}
        </div>
      )}
      <p style={{ color: "#666", fontSize: 13 }}>{searchStatus}</p>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "300px 1fr",
          gap: 16,
        }}
      >
        <div
          style={{
            maxHeight: 560,
            overflowY: "auto",
            border: "1px solid #ddd",
            borderRadius: 8,
          }}
        >
          {searchHits.map((h) => (
            <button
              key={h.entry_id}
              onClick={() => onSelectHit(h)}
              style={{
                display: "block",
                width: "100%",
                textAlign: "left",
                padding: "10px 12px",
                border: "none",
                borderBottom: "1px solid #eee",
                background:
                  searchSelectedId === h.entry_id ? "#e8f0fe" : "transparent",
                cursor: "pointer",
              }}
            >
              <div style={{ fontWeight: 600, fontSize: 13 }}>{h.entry_id}</div>
              <div style={{ fontSize: 12, color: "#555" }}>
                score {h.score?.toFixed?.(1) ?? h.score} ·{" "}
                {(h.speakers || []).join(", ") || "—"}
                {h.has_audio ? " · 🔊" : ""}
              </div>
              <div style={{ fontSize: 12, color: "#777", marginTop: 4 }}>
                {(h.title || h.preview || "").slice(0, 80)}
              </div>
            </button>
          ))}
          {!searchHits.length && !searchLoading && (
            <p style={{ padding: 12, color: "#888" }}>
              Enter a query and press Search.
            </p>
          )}
        </div>

        <div>
          {!searchHitDetail && (
            <p style={{ color: "#888" }}>Select a match to see segments.</p>
          )}
          {searchHitDetail && (
            <>
              <h3 style={{ marginTop: 0 }}>{searchHitDetail.entry_id}</h3>
              <p style={{ fontSize: 13, color: "#555" }}>
                {searchHitDetail.created_at} · matched:{" "}
                {(searchHitDetail.match_fields || []).join(", ")}
                <br />
                {(searchHitDetail.speakers || []).join(", ")}
              </p>

              {searchAudioSrc && (
                <audio
                  ref={audioRef}
                  key={searchHitDetail.audio_path}
                  controls
                  src={searchAudioSrc}
                  style={{ width: "100%", marginBottom: 12 }}
                />
              )}

              <div style={{ fontWeight: 600, marginBottom: 6 }}>
                Matching segments — click to seek
              </div>
              <div
                style={{
                  maxHeight: 360,
                  overflowY: "auto",
                  border: "1px solid #eee",
                  borderRadius: 8,
                }}
              >
                {(searchSegs.length ? searchSegs : []).map((s, i) => (
                  <button
                    key={i}
                    onClick={() => {
                      setActiveSegIdx(s.segment_index ?? i);
                      seekTo(s.start);
                    }}
                    style={{
                      display: "block",
                      width: "100%",
                      textAlign: "left",
                      padding: "10px 12px",
                      border: "none",
                      borderBottom: "1px solid #f0f0f0",
                      background:
                        activeSegIdx === (s.segment_index ?? i)
                          ? "#fef9c3"
                          : "transparent",
                      cursor: "pointer",
                    }}
                  >
                    <span style={{ color: "#3b82f6", fontWeight: 600 }}>
                      {Number(s.start).toFixed(1)}s
                    </span>{" "}
                    <span style={{ fontWeight: 600 }}>{s.speaker}</span>
                    <div style={{ fontSize: 13, marginTop: 2 }}>
                      {highlightSnippet(s.snippet || s.text)}
                    </div>
                  </button>
                ))}
                {!searchSegs.length && (
                  <p style={{ padding: 12, color: "#888", fontSize: 13 }}>
                    No segment-level hits (matched title/analysis only).{" "}
                    <button onClick={() => onOpenInHistory(searchHitDetail)}>
                      Open in History
                    </button>{" "}
                    to browse all segments.
                  </p>
                )}
              </div>
              <button
                style={{ marginTop: 12 }}
                onClick={() => onOpenInHistory(searchHitDetail)}
              >
                Open full entry in History
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
