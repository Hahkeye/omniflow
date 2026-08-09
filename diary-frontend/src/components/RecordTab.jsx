import { preStyle } from "./styles";
import { segmentStart, segmentEnd } from "./utils";

const HOTKEYS = [
  { keys: "Space", action: "Start / Stop" },
  { keys: "P", action: "Pause / Resume" },
  { keys: "Esc", action: "Cancel recording" },
];

export default function RecordTab({
  status,
  progress,
  recordingDuration,
  setRecordingDuration,
  backend,
  setBackend,
  audioPath,
  segments,
  transcript,
  elapsedS,
  onStart,
  onStop,
  onPause,
  onResume,
  onRecordTimed,
  onPickFile,
  onCancel,
}) {
  const pct =
    progress?.fraction != null ? Math.round(progress.fraction * 100) : null;
  const isRec = status === "recording";
  const isPaused = status === "paused";
  const isTx = status === "transcribing";
  const sessionActive = isRec || isPaused;
  const busy = sessionActive || isTx;

  return (
    <>
      <p>
        Status: <strong>{status}</strong>
        {sessionActive && elapsedS != null ? (
          <span style={{ marginLeft: 8, color: "#3b82f6", fontVariantNumeric: "tabular-nums" }}>
            {formatElapsed(elapsedS)}
          </span>
        ) : null}
        {progress?.message ? (
          <span style={{ color: "#666", marginLeft: 8 }}>
            — {progress.message}
            {pct != null ? ` (${pct}%)` : ""}
          </span>
        ) : null}
      </p>
      <p style={{ fontSize: 12, color: "#888", marginTop: 0 }}>
        Hotkeys (when not typing in a field):{" "}
        {HOTKEYS.map((h, i) => (
          <span key={h.keys}>
            {i > 0 ? " · " : null}
            <kbd style={kbdStyle}>{h.keys}</kbd> {h.action}
          </span>
        ))}
      </p>
      {pct != null && isTx && (
        <div
          style={{
            height: 8,
            background: "#eee",
            borderRadius: 4,
            marginBottom: 12,
            overflow: "hidden",
          }}
        >
          <div
            style={{
              width: `${pct}%`,
              height: "100%",
              background: "#3b82f6",
              transition: "width 0.2s",
            }}
          />
        </div>
      )}
      <div
        style={{
          marginBottom: 12,
          display: "flex",
          gap: 8,
          alignItems: "center",
          flexWrap: "wrap",
        }}
      >
        {!sessionActive ? (
          <button onClick={onStart} disabled={isTx} title="Space">
            ● Start
          </button>
        ) : (
          <button onClick={onStop} disabled={isTx} title="Space">
            ■ Stop
          </button>
        )}
        {isRec && (
          <button onClick={onPause} title="P">
            ⏸ Pause
          </button>
        )}
        {isPaused && (
          <button onClick={onResume} title="P">
            ▶ Resume
          </button>
        )}
        {sessionActive && onCancel && (
          <button onClick={onCancel} style={{ color: "#b00020" }} title="Esc">
            Cancel
          </button>
        )}
        <span style={{ color: "#ccc" }}>|</span>
        <button onClick={onRecordTimed} disabled={busy} title="Fixed-length record then transcribe">
          Timed ({recordingDuration}s)
        </button>
        <button onClick={onPickFile} disabled={busy}>
          {isTx ? "Transcribing..." : "Open File"}
        </button>
        {isTx && onCancel && (
          <button onClick={onCancel} style={{ color: "#b00020" }}>
            Cancel job
          </button>
        )}
        <input
          type="number"
          value={recordingDuration}
          onChange={(e) =>
            setRecordingDuration(parseInt(e.target.value, 10) || 1)
          }
          min={1}
          max={300}
          style={{ width: 50 }}
          disabled={busy}
        />
        <label style={{ marginLeft: 8 }}>
          Backend{" "}
          <select
            value={backend}
            onChange={(e) => setBackend(e.target.value)}
            disabled={busy}
          >
            <option value="moss">moss (recommended)</option>
            <option value="auto">auto</option>
            <option value="whisper">whisper</option>
            <option value="nemo">nemo</option>
          </select>
        </label>
      </div>
      {audioPath && (
        <p style={{ color: "#888", marginBottom: 12 }}>Current: {audioPath}</p>
      )}
      {segments.length > 0 && (
        <div style={{ marginTop: 20 }}>
          <h3>Transcript</h3>
          <table
            border="1"
            cellPadding="8"
            style={{ width: "100%", borderCollapse: "collapse" }}
          >
            <thead>
              <tr>
                <th>Speaker</th>
                <th>Start</th>
                <th>End</th>
                <th>Text</th>
              </tr>
            </thead>
            <tbody>
              {segments.map((seg, i) => (
                <tr key={i}>
                  <td>{seg.speaker}</td>
                  <td>{Number(segmentStart(seg)).toFixed(1)}s</td>
                  <td>{Number(segmentEnd(seg)).toFixed(1)}s</td>
                  <td>{seg.text}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <pre style={preStyle}>{transcript}</pre>
    </>
  );
}

function formatElapsed(s) {
  const n = Math.max(0, Math.floor(Number(s) || 0));
  const m = Math.floor(n / 60);
  const sec = n % 60;
  return `${m}:${String(sec).padStart(2, "0")}`;
}

const kbdStyle = {
  display: "inline-block",
  padding: "1px 6px",
  border: "1px solid #ccc",
  borderRadius: 4,
  background: "#f5f5f5",
  fontSize: 11,
  fontFamily: "system-ui, sans-serif",
};
