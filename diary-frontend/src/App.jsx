import { useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";

const defaultDuration = 30;

export default function App() {
  const [status, setStatus] = useState("ready");
  const [transcript, setTranscript] = useState("");
  const [transcriptData, setTranscriptData] = useState(null);
  const [audioPath, setAudioPath] = useState("");
  const [recordingDuration, setRecordingDuration] = useState(defaultDuration);

  async function handleTranscribe(path) {
    setStatus("transcribing");
    setTranscript("");
    setTranscriptData(null);
    try {
      const result = await invoke("transcribe", { audioPath: path });
      
      if (result.success) {
        const data = JSON.parse(result.output);
        setTranscriptData(data);
        setTranscript(result.output);
        setStatus("done");
      } else {
        setTranscript(
          `Error: ${result.error || "Unknown error"}\n${result.output}`
        );
        setStatus("error");
      }
    } catch (e) {
      setTranscript(`Error: ${e}`);
      setStatus("error");
    }
  }

  async function handlePickFile() {
    try {
      const selected = await open({
        multiple: false,
        filters: [{
          name: "Audio",
          extensions: ["wav", "mp3", "flac", "aac"],
        }],
      });
      if (selected) {
        const path = typeof selected === "string" ? selected : selected[0];
        setAudioPath(path);
        handleTranscribe(path);
      }
    } catch (e) {
      setTranscript(`Error picking file: ${e}`);
      setStatus("error");
    }
  }

  async function handleRecord() {
    setStatus("recording");
    setTranscript("");
    setTranscriptData(null);
    try {
      const result = await invoke("record", { duration: recordingDuration });
      
      if (result.success && result.wav_path) {
        setAudioPath(result.wav_path);
        handleTranscribe(result.wav_path);
      } else {
        setTranscript(`Record error: ${result.error || "Unknown"}`);
        setStatus("error");
      }
    } catch (e) {
      setTranscript(`Record error: ${e}`);
      setStatus("error");
    }
  }

  return (
    <div style={{ padding: 20, fontFamily: "sans-serif", maxWidth: 800, margin: "0 auto" }}>
      <h1>Diary</h1>
      <p>Status: {status}</p>
      
      <div style={{ marginBottom: 12 }}>
        <button onClick={handleRecord} disabled={status === "recording"}>
          {status === "recording" ? "Recording..." : `Record (${recordingDuration}s)`}
        </button>
        
        <button onClick={handlePickFile} disabled={status === "transcribing"}>
          {status === "transcribing" ? "Transcribing..." : "Open File"}
        </button>
        
        <input
          type="number"
          value={recordingDuration}
          onChange={(e) => setRecordingDuration(parseInt(e.target.value) || 1)}
          min={1}
          max={300}
          style={{ width: 50, marginLeft: 8 }}
          title="Recording duration in seconds"
        />
      </div>
      
      {audioPath && (
        <p style={{ color: "#888", marginBottom: 12 }}>
          Current: {audioPath}
        </p>
      )}
      
      {transcriptData && (
        <div style={{ marginTop: 20 }}>
          <h3>Transcript</h3>
          {transcriptData.segments && transcriptData.segments.length > 0 && (
            <table border="1" cellPadding="8" style={{ width: "100%" }}>
              <thead>
                <tr>
                  <th>Speaker</th>
                  <th>Start</th>
                  <th>End</th>
                  <th>Text</th>
                </tr>
              </thead>
              <tbody>
                {transcriptData.segments.map((seg, i) => (
                  <tr key={i}>
                    <td>{seg.speaker}</td>
                    <td>{seg.start}s</td>
                    <td>{seg.end}s</td>
                    <td>{seg.text}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
      <pre style={{ marginTop: 20 }}>{transcript}</pre>
    </div>
  );
}