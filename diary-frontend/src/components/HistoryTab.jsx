import { convertFileSrc } from "@tauri-apps/api/core";
import { chipStyle, preStyle } from "./styles";
import { formatWhen } from "./utils";

export default function HistoryTab({
  history,
  historyError,
  historyLoading,
  selectedId,
  histTranscript,
  histAnalysis,
  histAudioPath,
  histMeta,
  histSegments,
  activeSegIdx,
  setActiveSegIdx,
  personFilter,
  setPersonFilter,
  renameDraft,
  setRenameDraft,
  rememberDefaults,
  setRememberDefaults,
  renameStatus,
  roster,
  tagDraft,
  setTagDraft,
  noteDraft,
  setNoteDraft,
  exportStatus,
  audioRef,
  onRefresh,
  onOpen,
  onSaveRenames,
  onExport,
  onAnnotate,
  onArchive,
  onDelete,
  seekTo,
}) {
  const audioSrc = histAudioPath ? convertFileSrc(histAudioPath) : null;

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "300px 1fr",
        gap: 16,
      }}
    >
      <div>
        <div
          style={{
            display: "flex",
            gap: 6,
            marginBottom: 8,
            flexWrap: "wrap",
          }}
        >
          <input
            placeholder="Filter by person…"
            value={personFilter}
            onChange={(e) => setPersonFilter(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && onRefresh()}
            style={{ flex: 1, minWidth: 120, padding: 6 }}
          />
          <button onClick={onRefresh} disabled={historyLoading}>
            {historyLoading ? "…" : "Refresh"}
          </button>
        </div>
        {roster.people?.length > 0 && (
          <div style={{ fontSize: 12, color: "#555", marginBottom: 8 }}>
            {roster.people.map((p) => (
              <button
                key={p.id}
                onClick={() => setPersonFilter(p.name)}
                style={chipStyle(personFilter === p.name)}
              >
                {p.name}
              </button>
            ))}
          </div>
        )}
        {historyError && (
          <p style={{ color: "#b00020", fontSize: 13 }}>{historyError}</p>
        )}
        <div
          style={{
            maxHeight: 560,
            overflowY: "auto",
            border: "1px solid #ddd",
            borderRadius: 8,
          }}
        >
          {history.length === 0 && !historyLoading && (
            <p style={{ padding: 12, color: "#888" }}>No history yet.</p>
          )}
          {history.map((e) => (
            <button
              key={e.id}
              onClick={() => onOpen(e.id)}
              style={{
                display: "block",
                width: "100%",
                textAlign: "left",
                padding: "10px 12px",
                border: "none",
                borderBottom: "1px solid #eee",
                background: selectedId === e.id ? "#e8f0fe" : "transparent",
                cursor: "pointer",
              }}
            >
              <div style={{ fontWeight: 600, fontSize: 13 }}>
                {e.starred ? "★ " : ""}
                {e.id}
              </div>
              <div style={{ fontSize: 12, color: "#555" }}>
                {formatWhen(e)}
                {e.duration_s ? ` · ${e.duration_s}s` : ""}
                {e.has_audio || e.audio_path ? " · 🔊" : ""}
              </div>
              <div style={{ fontSize: 12, color: "#3b82f6", marginTop: 2 }}>
                {(e.display_speakers || e.speakers || []).join(", ") || "—"}
              </div>
              <div
                style={{
                  fontSize: 12,
                  color: "#777",
                  marginTop: 4,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {e.preview || e.title || "(no preview)"}
              </div>
            </button>
          ))}
        </div>
      </div>

      <div>
        {!selectedId && (
          <p style={{ color: "#888" }}>
            Select an entry. Click any segment to seek the audio player.
          </p>
        )}
        {selectedId && (
          <>
            <h3 style={{ marginTop: 0 }}>{selectedId}</h3>
            {histMeta && (
              <p style={{ fontSize: 13, color: "#555" }}>
                {histMeta.created_at}
                {histMeta.duration_s != null ? ` · ${histMeta.duration_s}s` : ""}
                <br />
                <strong>
                  {(histMeta.display_speakers || histMeta.speakers || []).join(
                    ", "
                  ) || "—"}
                </strong>
              </p>
            )}

            {audioSrc ? (
              <div style={{ marginBottom: 12 }}>
                <div style={{ fontWeight: 600, marginBottom: 6 }}>
                  Audio — click a segment below to seek
                </div>
                <audio
                  ref={audioRef}
                  key={histAudioPath}
                  controls
                  src={audioSrc}
                  style={{ width: "100%" }}
                />
              </div>
            ) : (
              <p style={{ color: "#888", fontSize: 13 }}>
                No audio for this entry.
              </p>
            )}

            {histSegments.length > 0 && (
              <div style={{ marginBottom: 16 }}>
                <div style={{ fontWeight: 600, marginBottom: 6 }}>
                  Segments (click → seek)
                </div>
                <div
                  style={{
                    maxHeight: 280,
                    overflowY: "auto",
                    border: "1px solid #eee",
                    borderRadius: 8,
                  }}
                >
                  {histSegments.map((s) => (
                    <button
                      key={s.segment_index}
                      onClick={() => {
                        setActiveSegIdx(s.segment_index);
                        seekTo(s.start);
                      }}
                      style={{
                        display: "block",
                        width: "100%",
                        textAlign: "left",
                        padding: "8px 12px",
                        border: "none",
                        borderBottom: "1px solid #f0f0f0",
                        background:
                          activeSegIdx === s.segment_index
                            ? "#fef9c3"
                            : "transparent",
                        cursor: "pointer",
                      }}
                    >
                      <span style={{ color: "#3b82f6", fontWeight: 600 }}>
                        {Number(s.start).toFixed(1)}s–{Number(s.end).toFixed(1)}s
                      </span>{" "}
                      <strong>{s.speaker}</strong>
                      <div style={{ fontSize: 13 }}>{s.text}</div>
                    </button>
                  ))}
                </div>
              </div>
            )}

            <div
              style={{
                border: "1px solid #ddd",
                borderRadius: 8,
                padding: 12,
                marginBottom: 16,
                background: "#fafbff",
              }}
            >
              <div style={{ fontWeight: 600, marginBottom: 8 }}>
                Name speakers
              </div>
              {Object.entries(renameDraft).map(([label, name]) => (
                <div
                  key={label}
                  style={{
                    display: "flex",
                    gap: 8,
                    alignItems: "center",
                    marginBottom: 6,
                  }}
                >
                  <span
                    style={{
                      minWidth: 90,
                      fontSize: 13,
                      fontFamily: "monospace",
                    }}
                  >
                    {label}
                  </span>
                  <span>→</span>
                  <input
                    value={name}
                    placeholder="Display name"
                    list="known-people"
                    onChange={(e) =>
                      setRenameDraft((d) => ({
                        ...d,
                        [label]: e.target.value,
                      }))
                    }
                    style={{ flex: 1, padding: 6 }}
                  />
                </div>
              ))}
              <datalist id="known-people">
                {(roster.people || []).map((p) => (
                  <option key={p.id} value={p.name} />
                ))}
              </datalist>
              <label
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                  fontSize: 13,
                  marginTop: 8,
                }}
              >
                <input
                  type="checkbox"
                  checked={rememberDefaults}
                  onChange={(e) => setRememberDefaults(e.target.checked)}
                />
                Remember as defaults for future sessions
              </label>
              <div
                style={{
                  marginTop: 8,
                  display: "flex",
                  gap: 8,
                  alignItems: "center",
                  flexWrap: "wrap",
                }}
              >
                <button onClick={onSaveRenames}>Save names</button>
                <button onClick={onExport}>Export MD/SRT/TXT/JSON</button>
                <button
                  onClick={() =>
                    onAnnotate({ star: !(histMeta && histMeta.starred) })
                  }
                >
                  {histMeta?.starred ? "☆ Unstar" : "★ Star"}
                </button>
                <button onClick={() => onArchive(false)}>Archive</button>
                <button
                  onClick={() => onDelete(false)}
                  style={{ color: "#b00020" }}
                >
                  Delete
                </button>
                {renameStatus && (
                  <span style={{ fontSize: 13, color: "#555" }}>
                    {renameStatus}
                  </span>
                )}
              </div>
              <div
                style={{
                  marginTop: 8,
                  display: "flex",
                  gap: 6,
                  flexWrap: "wrap",
                }}
              >
                <input
                  placeholder="tags (meeting project-x)"
                  value={tagDraft}
                  onChange={(e) => setTagDraft(e.target.value)}
                  style={{ flex: 1, minWidth: 120, padding: 6 }}
                />
                <button
                  onClick={() => {
                    onAnnotate({ tags: tagDraft });
                    setTagDraft("");
                  }}
                >
                  Add tags
                </button>
              </div>
              <div style={{ marginTop: 6, display: "flex", gap: 6 }}>
                <input
                  placeholder="Append a note…"
                  value={noteDraft}
                  onChange={(e) => setNoteDraft(e.target.value)}
                  style={{ flex: 1, padding: 6 }}
                />
                <button
                  onClick={() => {
                    onAnnotate({ note: noteDraft });
                    setNoteDraft("");
                  }}
                >
                  Note
                </button>
              </div>
              {(histMeta?.tags || []).length > 0 && (
                <p style={{ fontSize: 12, color: "#3b82f6" }}>
                  {(histMeta.tags || []).map((t) => `#${t}`).join(" ")}
                </p>
              )}
              {exportStatus && (
                <pre style={{ ...preStyle, marginTop: 8, fontSize: 12 }}>
                  {exportStatus}
                </pre>
              )}
            </div>

            <div style={{ fontWeight: 600, marginBottom: 6 }}>
              Full transcript
            </div>
            <pre style={{ ...preStyle, maxHeight: 200, overflow: "auto" }}>
              {histTranscript || "(no transcript)"}
            </pre>
            {histAnalysis && (
              <>
                <div style={{ fontWeight: 600, margin: "16px 0 6px" }}>
                  Analysis
                </div>
                <pre style={{ ...preStyle, background: "#f0f4ff" }}>
                  {histAnalysis}
                </pre>
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}
