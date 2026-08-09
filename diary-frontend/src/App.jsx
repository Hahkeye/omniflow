import { useCallback, useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { open } from "@tauri-apps/plugin-dialog";
import RecordTab from "./components/RecordTab";
import HistoryTab from "./components/HistoryTab";
import SearchTab from "./components/SearchTab";
import DigestTab from "./components/DigestTab";
import ActionsTab from "./components/ActionsTab";
import { tabStyle } from "./components/styles";

const defaultDuration = 30;

export default function App() {
  const [tab, setTab] = useState("record");
  const [status, setStatus] = useState("ready");
  const [progress, setProgress] = useState(null);
  const [transcript, setTranscript] = useState("");
  const [transcriptData, setTranscriptData] = useState(null);
  const [audioPath, setAudioPath] = useState("");
  const [recordingDuration, setRecordingDuration] = useState(defaultDuration);
  const [backend, setBackend] = useState("moss");
  const [recordElapsed, setRecordElapsed] = useState(0);
  const statusRef = useRef(status);
  const tabRef = useRef(tab);

  const [history, setHistory] = useState([]);
  const [historyError, setHistoryError] = useState("");
  const [selectedId, setSelectedId] = useState(null);
  const [histTranscript, setHistTranscript] = useState("");
  const [histAnalysis, setHistAnalysis] = useState("");
  const [histAudioPath, setHistAudioPath] = useState(null);
  const [histMeta, setHistMeta] = useState(null);
  const [histSegments, setHistSegments] = useState([]);
  const [activeSegIdx, setActiveSegIdx] = useState(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [personFilter, setPersonFilter] = useState("");
  const [renameDraft, setRenameDraft] = useState({});
  const [rememberDefaults, setRememberDefaults] = useState(true);
  const [renameStatus, setRenameStatus] = useState("");
  const [roster, setRoster] = useState({ people: [], global_defaults: {} });
  const audioRef = useRef(null);

  const [searchQuery, setSearchQuery] = useState("");
  const [searchPerson, setSearchPerson] = useState("");
  const [searchHits, setSearchHits] = useState([]);
  const [searchStatus, setSearchStatus] = useState("");
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchSelectedId, setSearchSelectedId] = useState(null);
  const [searchHitDetail, setSearchHitDetail] = useState(null);

  const [digestDays, setDigestDays] = useState(7);
  const [digestMd, setDigestMd] = useState("");
  const [digestPath, setDigestPath] = useState("");
  const [digestLoading, setDigestLoading] = useState(false);
  const [exportStatus, setExportStatus] = useState("");
  const [tagDraft, setTagDraft] = useState("");
  const [noteDraft, setNoteDraft] = useState("");
  const [actionsOpen, setActionsOpen] = useState([]);
  const [actionsStatus, setActionsStatus] = useState("");

  useEffect(() => {
    statusRef.current = status;
  }, [status]);
  useEffect(() => {
    tabRef.current = tab;
  }, [tab]);

  useEffect(() => {
    let unlisten;
    listen("diary-progress", (event) => {
      setProgress(event.payload || null);
    }).then((fn) => {
      unlisten = fn;
    });
    return () => {
      if (unlisten) unlisten();
    };
  }, []);

  // Poll elapsed while recording / paused
  useEffect(() => {
    if (status !== "recording" && status !== "paused") return undefined;
    let alive = true;
    const tick = async () => {
      try {
        const result = await invoke("record_control", { action: "status" });
        if (!alive || !result.success) return;
        const data = JSON.parse(result.result_json || "{}");
        if (typeof data.elapsed_s === "number") {
          setRecordElapsed(data.elapsed_s);
        }
        if (data.state === "idle" && (statusRef.current === "recording" || statusRef.current === "paused")) {
          // session ended unexpectedly
          setStatus("ready");
        }
      } catch {
        /* ignore */
      }
    };
    tick();
    const id = setInterval(tick, 500);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [status]);

  const loadRoster = useCallback(async () => {
    try {
      const result = await invoke("speakers_roster");
      if (result.success) {
        setRoster(JSON.parse(result.roster_json || "{}"));
      }
    } catch {
      /* optional */
    }
  }, []);

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    setHistoryError("");
    try {
      const result = await invoke("history_list", {
        limit: 100,
        person: personFilter || null,
      });
      if (!result.success) {
        setHistoryError(result.error || "Failed to load history");
        setHistory([]);
        return;
      }
      const entries = JSON.parse(result.entries_json || "[]");
      setHistory(Array.isArray(entries) ? entries : []);
    } catch (e) {
      setHistoryError(String(e));
      setHistory([]);
    } finally {
      setHistoryLoading(false);
    }
  }, [personFilter]);

  const loadActions = useCallback(async () => {
    try {
      const result = await invoke("actions_inbox", { includeDone: false });
      if (result.success) {
        const data = JSON.parse(result.roster_json || "{}");
        setActionsOpen(data.open || []);
        setActionsStatus(
          `Open: ${data.open_count ?? 0} · synced +${data.synced_new ?? 0}`
        );
      } else {
        setActionsStatus(result.error || "Failed to load actions");
      }
    } catch (e) {
      setActionsStatus(String(e));
    }
  }, []);

  useEffect(() => {
    if (tab === "history") {
      loadHistory();
      loadRoster();
    }
    if (tab === "search") {
      loadRoster();
    }
    if (tab === "actions") {
      loadActions();
    }
  }, [tab, loadHistory, loadRoster, loadActions]);

  function seekTo(seconds) {
    const el = audioRef.current;
    if (!el) return;
    const t = Math.max(0, Number(seconds) || 0);
    const doSeek = () => {
      try {
        el.currentTime = t;
        el.play().catch(() => {});
      } catch {
        /* ignore */
      }
    };
    if (el.readyState >= 1) {
      doSeek();
    } else {
      el.addEventListener("loadedmetadata", doSeek, { once: true });
      el.load?.();
    }
  }

  async function openHistoryEntry(id, seekStart = null) {
    setSelectedId(id);
    setHistTranscript("");
    setHistAnalysis("");
    setHistAudioPath(null);
    setHistMeta(null);
    setHistSegments([]);
    setActiveSegIdx(null);
    setRenameDraft({});
    setRenameStatus("");
    setHistoryLoading(true);
    try {
      const result = await invoke("history_get", { entryId: id });
      if (!result.success) {
        setHistoryError(result.error || "Failed to open entry");
        return;
      }
      setHistTranscript(result.transcript_text || "");
      setHistAnalysis(result.analysis_text || "");
      setHistAudioPath(result.audio_path || null);
      let meta = null;
      try {
        meta = JSON.parse(result.entry_json || "{}");
        setHistMeta(meta);
      } catch {
        setHistMeta(null);
      }
      let segs = [];
      try {
        segs = JSON.parse(result.segments_json || "[]");
        if (!Array.isArray(segs)) segs = [];
      } catch {
        segs = [];
      }
      setHistSegments(segs);

      const raw = meta?.raw_labels || [];
      const smap = meta?.speaker_map || {};
      const draft = {};
      for (const label of raw) {
        draft[label] = smap[label] || "";
      }
      for (const [k, v] of Object.entries(smap)) {
        if (!(k in draft)) draft[k] = v;
      }
      setRenameDraft(draft);

      if (seekStart != null) {
        setTimeout(() => seekTo(seekStart), 100);
      }
    } catch (e) {
      setHistoryError(String(e));
    } finally {
      setHistoryLoading(false);
    }
  }

  async function saveRenames() {
    if (!selectedId) return;
    const mapping = {};
    for (const [k, v] of Object.entries(renameDraft)) {
      if (v && String(v).trim()) mapping[k] = String(v).trim();
    }
    if (Object.keys(mapping).length === 0) {
      setRenameStatus("Enter at least one name.");
      return;
    }
    setRenameStatus("Saving…");
    try {
      const result = await invoke("speakers_rename", {
        entryId: selectedId,
        mappingJson: JSON.stringify(mapping),
        remember: rememberDefaults,
      });
      if (!result.success) {
        setRenameStatus(result.error || "Rename failed");
        return;
      }
      setRenameStatus(
        rememberDefaults
          ? "Saved and remembered for future sessions."
          : "Saved names for this entry."
      );
      await openHistoryEntry(selectedId);
      await loadHistory();
      await loadRoster();
    } catch (e) {
      setRenameStatus(String(e));
    }
  }

  async function runDigest() {
    setDigestLoading(true);
    setDigestMd("");
    setDigestPath("");
    try {
      const result = await invoke("digest_cmd", { days: digestDays });
      if (!result.success) {
        setDigestMd(result.error || "Digest failed");
        return;
      }
      setDigestMd(result.markdown || "");
      setDigestPath(result.path || "");
    } catch (e) {
      setDigestMd(String(e));
    } finally {
      setDigestLoading(false);
    }
  }

  async function exportCurrent() {
    if (!selectedId) {
      setExportStatus("Select an entry first.");
      return;
    }
    setExportStatus("Exporting…");
    try {
      const result = await invoke("export_entry_cmd", {
        entryId: selectedId,
        formats: "md,srt,txt,json",
      });
      if (!result.success) {
        setExportStatus(result.error || "Export failed");
        return;
      }
      const data = JSON.parse(result.result_json || "{}");
      setExportStatus(
        `Exported to ${data.out_dir}\n${(data.files || []).join("\n")}`
      );
    } catch (e) {
      setExportStatus(String(e));
    }
  }

  async function annotateCurrent({ tags, note, star } = {}) {
    if (!selectedId) {
      setExportStatus("Select an entry first.");
      return;
    }
    try {
      const result = await invoke("entry_annotate", {
        entryId: selectedId,
        addTags: tags || null,
        note: note || null,
        star: star === undefined ? null : star,
      });
      if (!result.success) {
        setExportStatus(result.error || "Annotate failed");
        return;
      }
      const e = JSON.parse(result.roster_json || "{}");
      setExportStatus(
        `Updated ${e.id}\ntags: ${(e.tags || []).map((t) => "#" + t).join(" ") || "—"}\nstarred: ${e.starred}\n${e.notes || ""}`
      );
      setHistMeta((m) => (m ? { ...m, ...e } : e));
      loadHistory();
    } catch (err) {
      setExportStatus(String(err));
    }
  }

  async function archiveCurrent() {
    if (!selectedId) return;
    if (!window.confirm(`Archive entry ${selectedId}?`)) return;
    try {
      const result = await invoke("entry_archive", {
        entryId: selectedId,
        unarchive: false,
      });
      if (!result.success) {
        setExportStatus(result.error || "Archive failed");
        return;
      }
      setExportStatus(`Archived ${selectedId}`);
      setSelectedId(null);
      loadHistory();
    } catch (e) {
      setExportStatus(String(e));
    }
  }

  async function deleteCurrent() {
    if (!selectedId) return;
    if (
      !window.confirm(
        `Permanently delete entry ${selectedId}? This cannot be undone.`
      )
    ) {
      return;
    }
    try {
      const result = await invoke("entry_delete", {
        entryId: selectedId,
        deleteAudio: false,
      });
      if (!result.success) {
        setExportStatus(result.error || "Delete failed");
        return;
      }
      setExportStatus(`Deleted ${selectedId}`);
      setSelectedId(null);
      loadHistory();
    } catch (e) {
      setExportStatus(String(e));
    }
  }

  async function completeAction(id) {
    try {
      await invoke("actions_done", { actionId: id, done: true });
      loadActions();
    } catch (e) {
      setActionsStatus(String(e));
    }
  }

  async function runSearch() {
    setSearchLoading(true);
    setSearchStatus("");
    setSearchHits([]);
    setSearchSelectedId(null);
    setSearchHitDetail(null);
    try {
      const result = await invoke("diary_search", {
        query: searchQuery || "",
        person: searchPerson || null,
        limit: 50,
      });
      if (!result.success) {
        setSearchStatus(result.error || "Search failed");
        return;
      }
      const hits = JSON.parse(result.hits_json || "[]");
      setSearchHits(Array.isArray(hits) ? hits : []);
      setSearchStatus(
        hits.length ? `${hits.length} matching entries` : "No matches"
      );
      if (hits.length) {
        setSearchSelectedId(hits[0].entry_id);
        setSearchHitDetail(hits[0]);
      }
    } catch (e) {
      setSearchStatus(String(e));
    } finally {
      setSearchLoading(false);
    }
  }

  function selectSearchHit(hit) {
    setSearchSelectedId(hit.entry_id);
    setSearchHitDetail(hit);
    setActiveSegIdx(null);
  }

  async function openSearchHitInHistory(hit, seg = null) {
    setTab("history");
    await openHistoryEntry(hit.entry_id, seg ? seg.start : null);
    if (seg) {
      setActiveSegIdx(seg.segment_index);
    }
  }

  async function handleCancel() {
    const st = statusRef.current;
    try {
      if (st === "recording" || st === "paused") {
        await invoke("record_control", { action: "cancel" });
        setStatus("ready");
        setRecordElapsed(0);
        setProgress({ phase: "record", message: "Recording cancelled" });
        return;
      }
      await invoke("daemon_cancel");
      setProgress({ phase: "cancel", fraction: null, message: "Cancel requested…" });
    } catch (e) {
      setProgress({ phase: "cancel", message: String(e) });
    }
  }

  async function handleRecordStart() {
    if (statusRef.current === "transcribing") return;
    setTranscript("");
    setTranscriptData(null);
    setRecordElapsed(0);
    setProgress({ phase: "record", message: "Starting…" });
    try {
      const result = await invoke("record_control", { action: "start" });
      if (!result.success) {
        setStatus("error");
        setTranscript(`Record start error: ${result.error || "Unknown"}`);
        return;
      }
      setStatus("recording");
      setProgress({ phase: "record", message: "Recording… (Space = stop, P = pause)" });
    } catch (e) {
      setStatus("error");
      setTranscript(`Record start error: ${e}`);
    }
  }

  async function handleRecordStop() {
    setProgress({ phase: "record", message: "Stopping…" });
    try {
      const result = await invoke("record_control", { action: "stop" });
      if (!result.success) {
        setStatus("error");
        setTranscript(`Record stop error: ${result.error || "Unknown"}`);
        return;
      }
      const data = JSON.parse(result.result_json || "{}");
      setRecordElapsed(data.elapsed_s || 0);
      if (data.wav_path) {
        setAudioPath(data.wav_path);
        setStatus("ready");
        setProgress({ phase: "record", fraction: 1, message: "Saved recording" });
        handleTranscribe(data.wav_path);
      } else {
        setStatus("error");
        setTranscript(`Record stop: ${data.error || "No audio captured"}`);
      }
    } catch (e) {
      setStatus("error");
      setTranscript(`Record stop error: ${e}`);
    }
  }

  async function handleRecordPause() {
    try {
      const result = await invoke("record_control", { action: "pause" });
      if (!result.success) {
        setProgress({ phase: "record", message: result.error || "Pause failed" });
        return;
      }
      setStatus("paused");
      setProgress({ phase: "record", message: "Paused (P = resume, Space = stop)" });
    } catch (e) {
      setProgress({ phase: "record", message: String(e) });
    }
  }

  async function handleRecordResume() {
    try {
      const result = await invoke("record_control", { action: "resume" });
      if (!result.success) {
        setProgress({ phase: "record", message: result.error || "Resume failed" });
        return;
      }
      setStatus("recording");
      setProgress({ phase: "record", message: "Recording… (Space = stop, P = pause)" });
    } catch (e) {
      setProgress({ phase: "record", message: String(e) });
    }
  }

  async function handleTranscribe(path) {
    setStatus("transcribing");
    setProgress({ phase: "transcribe", fraction: 0, message: "Starting…" });
    setTranscript("");
    setTranscriptData(null);
    try {
      const result = await invoke("transcribe", {
        audioPath: path,
        backend: backend || "moss",
      });

      if (result.success) {
        const data = JSON.parse(result.output);
        setTranscriptData(data);
        setTranscript(result.output);
        setStatus("done");
        setProgress({ phase: "transcribe", fraction: 1, message: "Done" });
        loadHistory();
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
        filters: [
          {
            name: "Audio",
            extensions: ["wav", "mp3", "flac", "aac", "m4a", "ogg"],
          },
        ],
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

  /** Fixed-duration record (legacy timed mode). */
  async function handleRecordTimed() {
    setStatus("recording");
    setProgress({ phase: "record", fraction: 0, message: "Recording…" });
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

  // Global hotkeys on Record tab (ignore when typing in inputs)
  useEffect(() => {
    function isTypingTarget(el) {
      if (!el || !el.tagName) return false;
      const tag = el.tagName.toLowerCase();
      if (tag === "input" || tag === "textarea" || tag === "select") return true;
      if (el.isContentEditable) return true;
      return false;
    }

    function onKeyDown(e) {
      if (tabRef.current !== "record") return;
      if (isTypingTarget(e.target)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;

      const st = statusRef.current;
      const key = e.key;

      if (key === " " || key === "Spacebar") {
        e.preventDefault();
        if (st === "ready" || st === "done" || st === "error") {
          handleRecordStart();
        } else if (st === "recording" || st === "paused") {
          handleRecordStop();
        }
        return;
      }
      if (key === "p" || key === "P") {
        e.preventDefault();
        if (st === "recording") handleRecordPause();
        else if (st === "paused") handleRecordResume();
        return;
      }
      if (key === "Escape") {
        if (st === "recording" || st === "paused" || st === "transcribing") {
          e.preventDefault();
          handleCancel();
        }
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const segments =
    transcriptData?.transcript?.segments || transcriptData?.segments || [];

  return (
    <div
      style={{
        padding: 20,
        fontFamily: "system-ui, sans-serif",
        maxWidth: 1100,
        margin: "0 auto",
      }}
    >
      <h1 style={{ marginBottom: 4 }}>Diary</h1>
      <p style={{ color: "#666", fontSize: 14, marginTop: 0 }}>
        STT · history · speakers · search · click-to-seek
      </p>

      <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
        <button onClick={() => setTab("record")} style={tabStyle(tab === "record")}>
          Record / Transcribe
        </button>
        <button onClick={() => setTab("history")} style={tabStyle(tab === "history")}>
          History
        </button>
        <button onClick={() => setTab("search")} style={tabStyle(tab === "search")}>
          Search
        </button>
        <button onClick={() => setTab("digest")} style={tabStyle(tab === "digest")}>
          Digest
        </button>
        <button onClick={() => setTab("actions")} style={tabStyle(tab === "actions")}>
          Actions
        </button>
      </div>

      {tab === "actions" && (
        <ActionsTab
          actionsOpen={actionsOpen}
          actionsStatus={actionsStatus}
          onRefresh={loadActions}
          onComplete={completeAction}
        />
      )}

      {tab === "digest" && (
        <DigestTab
          digestDays={digestDays}
          setDigestDays={setDigestDays}
          digestLoading={digestLoading}
          digestMd={digestMd}
          digestPath={digestPath}
          onBuild={runDigest}
        />
      )}

      {tab === "record" && (
        <RecordTab
          status={status}
          progress={progress}
          recordingDuration={recordingDuration}
          setRecordingDuration={setRecordingDuration}
          backend={backend}
          setBackend={setBackend}
          audioPath={audioPath}
          segments={segments}
          transcript={transcript}
          elapsedS={recordElapsed}
          onStart={handleRecordStart}
          onStop={handleRecordStop}
          onPause={handleRecordPause}
          onResume={handleRecordResume}
          onRecordTimed={handleRecordTimed}
          onPickFile={handlePickFile}
          onCancel={handleCancel}
        />
      )}

      {tab === "search" && (
        <SearchTab
          searchQuery={searchQuery}
          setSearchQuery={setSearchQuery}
          searchPerson={searchPerson}
          setSearchPerson={setSearchPerson}
          searchHits={searchHits}
          searchStatus={searchStatus}
          searchLoading={searchLoading}
          searchSelectedId={searchSelectedId}
          searchHitDetail={searchHitDetail}
          roster={roster}
          activeSegIdx={activeSegIdx}
          setActiveSegIdx={setActiveSegIdx}
          audioRef={audioRef}
          onSearch={runSearch}
          onSelectHit={selectSearchHit}
          onOpenInHistory={openSearchHitInHistory}
          seekTo={seekTo}
        />
      )}

      {tab === "history" && (
        <HistoryTab
          history={history}
          historyError={historyError}
          historyLoading={historyLoading}
          selectedId={selectedId}
          histTranscript={histTranscript}
          histAnalysis={histAnalysis}
          histAudioPath={histAudioPath}
          histMeta={histMeta}
          histSegments={histSegments}
          activeSegIdx={activeSegIdx}
          setActiveSegIdx={setActiveSegIdx}
          personFilter={personFilter}
          setPersonFilter={setPersonFilter}
          renameDraft={renameDraft}
          setRenameDraft={setRenameDraft}
          rememberDefaults={rememberDefaults}
          setRememberDefaults={setRememberDefaults}
          renameStatus={renameStatus}
          roster={roster}
          tagDraft={tagDraft}
          setTagDraft={setTagDraft}
          noteDraft={noteDraft}
          setNoteDraft={setNoteDraft}
          exportStatus={exportStatus}
          audioRef={audioRef}
          onRefresh={loadHistory}
          onOpen={openHistoryEntry}
          onSaveRenames={saveRenames}
          onExport={exportCurrent}
          onAnnotate={annotateCurrent}
          onArchive={archiveCurrent}
          onDelete={deleteCurrent}
          seekTo={seekTo}
        />
      )}
    </div>
  );
}
