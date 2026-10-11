import { useCallback, useEffect, useState } from "react";
import {
  events,
  eventDelay,
  initialStep,
  replay,
  playbackSeconds,
  type Stage,
} from "./replay";
import { Icon, Progress, Schematic } from "./Schematic";
import {
  Activity,
  Inspector,
  RunLog,
  RunPanel,
  ThreadInspector,
  DealSummary,
} from "./views";

export default function App() {
  const [index, setIndex] = useState(() => initialStep(location.search));
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [tab, setTab] = useState<"pipeline" | "log">("pipeline");
  const [selected, setSelected] = useState<Stage | null>(null);
  const [thread, setThread] = useState<string | null>(null);
  const [fullscreenError, setFullscreenError] = useState("");
  const complete = index === events.length;
  const jump = useCallback((value: number) => {
    setPlaying(false);
    setIndex(Math.max(0, Math.min(events.length, value)));
  }, []);
  const toggle = useCallback(() => {
    if (index === events.length) setIndex(0);
    setPlaying((value) => !value);
  }, [index]);
  const inspect = (id: Stage) => {
    setPlaying(false);
    setThread(null);
    setSelected(id);
  };
  const fullscreen = useCallback(async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await document.documentElement.requestFullscreen();
      setFullscreenError("");
    } catch {
      setFullscreenError("Full screen is unavailable in this browser.");
    }
  }, []);

  useEffect(() => {
    if (!playing || complete || selected) return;
    const timer = window.setTimeout(
      () => setIndex((value) => Math.min(events.length, value + 1)),
      eventDelay(events[index - 1]) / speed,
    );
    return () => window.clearTimeout(timer);
  }, [playing, complete, selected, index, speed]);
  useEffect(() => {
    if (complete) setPlaying(false);
  }, [complete]);
  useEffect(() => {
    const url = new URL(location.href);
    if (index) url.searchParams.set("step", String(index));
    else url.searchParams.delete("step");
    history.replaceState(null, "", url);
  }, [index]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (
        selected ||
        thread ||
        e.altKey ||
        e.ctrlKey ||
        e.metaKey ||
        (e.target instanceof HTMLElement &&
          e.target.closest(
            "input, select, textarea, button, a, [contenteditable]",
          ))
      )
        return;
      if (
        [
          " ",
          "ArrowRight",
          "ArrowLeft",
          "Home",
          "End",
          "PageDown",
          "PageUp",
        ].includes(e.key)
      )
        e.preventDefault();
      if (e.key === " ") toggle();
      if (["ArrowRight", "PageDown"].includes(e.key)) jump(index + 1);
      if (["ArrowLeft", "PageUp"].includes(e.key)) jump(index - 1);
      if (e.key === "Home") jump(0);
      if (e.key === "End") jump(events.length);
      if (e.key.toLowerCase() === "f") void fullscreen();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [index, jump, selected, thread, toggle, fullscreen]);

  return (
    <div className="app-shell">
      <header className="topbar">
        <a href="./" className="brand" aria-label="ProcureCabana home">
          <span className="brand-mark">
            <span />
            <span />
            <span />
            <span />
          </span>
          <span>
            <strong>
              ProcureCabana<span className="brand-period">.</span>
            </strong>
            <small>HOLLERAU PUMPENWERKE</small>
          </span>
        </a>
        <div className="header-right">
          <span className="environment">
            <span className="status-dot" /> Local test environment
          </span>
          <span className="header-divider" />
          <button
            className="icon-button"
            onClick={() => void fullscreen()}
            aria-label="Toggle full screen"
            title="Full screen (F)"
          >
            <Icon name="expand" />
          </button>
        </div>
      </header>
      <main>
        <h1 className="sr-only">ProcureCabana negotiation monitor</h1>
        <DealSummary index={index} />
        <div className="workspace workspace-live">
          <section
            className="pipeline-panel"
            aria-label="Agent architecture and test playback"
          >
            <div className="board-toolbar">
              <div
                className="view-tabs"
                role="tablist"
                aria-label="Monitor view"
              >
                <button
                  id="pipeline-tab"
                  role="tab"
                  aria-selected={tab === "pipeline"}
                  aria-controls="monitor-content"
                  tabIndex={tab === "pipeline" ? 0 : -1}
                  className={tab === "pipeline" ? "selected" : ""}
                  onClick={() => setTab("pipeline")}
                  onKeyDown={(e) => {
                    if (e.key === "ArrowRight") {
                      setTab("log");
                      document.getElementById("log-tab")?.focus();
                    }
                  }}
                >
                  Pipeline
                </button>
                <button
                  id="log-tab"
                  role="tab"
                  aria-selected={tab === "log"}
                  aria-controls="monitor-content"
                  tabIndex={tab === "log" ? 0 : -1}
                  className={tab === "log" ? "selected" : ""}
                  onClick={() => setTab("log")}
                  onKeyDown={(e) => {
                    if (e.key === "ArrowLeft") {
                      setTab("pipeline");
                      document.getElementById("pipeline-tab")?.focus();
                    }
                  }}
                >
                  Run log <span>{index}</span>
                </button>
              </div>
              <span
                className={`run-status ${playing ? "is-running" : complete ? "is-complete" : ""}`}
              >
                <span className="status-dot" />
                {complete
                  ? "Complete"
                  : playing
                    ? "Running"
                    : index
                      ? "Paused"
                      : "Ready to run"}
              </span>
            </div>
            <div
              id="monitor-content"
              role="tabpanel"
              aria-labelledby={tab === "pipeline" ? "pipeline-tab" : "log-tab"}
            >
              {tab === "pipeline" ? (
                <Schematic index={index} playing={playing} onSelect={inspect} />
              ) : (
                <RunLog index={index} onJump={jump} />
              )}
            </div>
            <Activity index={index} onInspect={inspect} />
          </section>
          <RunPanel
            index={index}
            playing={playing}
            onOpenThread={(sid) => {
              setSelected(null);
              setThread(sid);
            }}
          />
        </div>
        <div className="workspace-caption">
          <span>
            <Icon name="close" size={14} /> Bounded model output. Deterministic
            fallback at every stage.
          </span>
          <span>
            Test trace <code>{replay.id}</code>
          </span>
        </div>
      </main>
      <footer className="playback">
        <Progress index={index} />
        <div className="playback-inner">
          <div className="playback-primary">
            <button className="play-button" onClick={toggle}>
              <Icon
                name={playing ? "pause" : complete ? "reset" : "play"}
                size={17}
              />
              {playing
                ? "Pause run"
                : complete
                  ? "Replay test"
                  : index
                    ? "Resume run"
                    : "Start test run"}
            </button>
            <button
              className="icon-button reset-button"
              aria-label="Reset test run"
              title="Reset test run"
              onClick={() => jump(0)}
              disabled={index === 0 && !playing}
            >
              <Icon name="reset" size={19} />
            </button>
          </div>
          <div className="playback-position">
            <div className="playback-label">
              <strong>
                {complete
                  ? "Test run complete"
                  : index
                    ? events[index - 1].title
                    : `${replay.case.round_limit} rounds · about ${playbackSeconds} seconds`}
              </strong>
              <span>
                {String(index).padStart(2, "0")} / {events.length} steps
              </span>
            </div>
            <input
              type="range"
              min="0"
              max={events.length}
              value={index}
              aria-label="Test run step"
              aria-valuetext={
                index
                  ? `Step ${index}: ${events[index - 1].title}`
                  : "Ready to run"
              }
              onChange={(e) => jump(Number(e.target.value))}
            />
          </div>
          <div className="playback-secondary">
            <button
              className="icon-button"
              aria-label="Previous step"
              title="Previous step (←)"
              disabled={index === 0}
              onClick={() => jump(index - 1)}
            >
              <Icon name="back" size={18} />
            </button>
            <button
              className="icon-button"
              aria-label="Next step"
              title="Next step (→)"
              disabled={complete}
              onClick={() => jump(index + 1)}
            >
              <Icon name="next" size={18} />
            </button>
            <span className="control-divider" />
            <label className="speed-label">
              <span className="sr-only">Playback speed</span>
              <select
                aria-label="Playback speed"
                value={speed}
                onChange={(e) => setSpeed(Number(e.target.value))}
              >
                <option value={0.5}>0.5× speed</option>
                <option value={1}>1× speed</option>
                <option value={2}>2× speed</option>
                <option value={4}>4× speed</option>
              </select>
            </label>
            <span className="keyboard-hint">
              <kbd>Space</kbd> to play
            </span>
          </div>
        </div>
        {fullscreenError && (
          <p className="fullscreen-error" role="status">
            {fullscreenError}
          </p>
        )}
      </footer>
      {thread && (
        <ThreadInspector
          sid={thread}
          index={index}
          playing={playing}
          onToggle={toggle}
          onClose={() => setThread(null)}
          onJump={jump}
        />
      )}
      {selected && (
        <Inspector
          selected={selected}
          index={index}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  );
}
