# ProcureCabana pipeline monitor

A responsive overview of the current buyer, with connected preparation, negotiation,
closing and memory flows. Model roles and code components have different colors.
Click a component for its responsibility, implementation files and latest output.
There is no fixed “agent count”: four specialist roles and a lead work per supplier
when data is available, alongside two rehearsal roles; analyst and writer calls repeat
through negotiation, and a scored case can produce a debrief.

```sh
cd pitch
npm install
npm run dev
```

**Start test run** plays the bundled local trace. Pause, step, scrub, change speed, or
reset using the footer. Space plays/pauses; arrows step; Home/End jump; F toggles full
screen. Shortcuts defer to focused controls. `?step=N` restores a paused position.
The run log and component inspector only reveal events through that position.

The short demo has three negotiation rounds per supplier. The **live thread** beside
the pipeline adds emails, checked proposals and supplier replies as playback advances.
Offers show their change from the previous price. Switch supplier tabs to follow either
conversation; scroll back to read and use **Jump to latest** to resume automatic following.

**Expand thread & offer history** opens original sent/received emails,
complete recorded term sheets, evidence references, claim-check results, analyst
assessments, code decision records, the evolving price chart and the final selection.
Playback continues in the expanded thread, with its own pause/play control.
Previous/next thread event pauses and moves the global replay to that supplier's next handoff.
Future emails and outcomes stay hidden. The chart tracks unit price; acceptance uses
the full total cost.

## Refresh the test trace

From the repository root:

```sh
uv run python pitch/simulate.py
```

This executes the current `runner.play_case`, research/rehearsal, analyst, policy,
writer, cost engine and debrief against the arena-kit **S02 simulator in process**,
with the demo case's round limit shortened to three. Production policy is unchanged.
Model replies are clearly labelled scripted fixtures, and suppliers use the kit's
script. No HTTP server, API key or hosted practice quota is used. Run logs, research
cache and lessons are isolated; production memory is unchanged. When available,
`data/package` supplies research records and citable facts. Without it, the actual
no-package fallback path runs.

`src/simulation.json` includes the source commit, buyer-source fingerprint, full
recorded event sequence and a sample size of one. Playback is paced for explanation;
it does not claim real execution timings or predictive performance. Research and
rehearsal are presented as consecutive checkpoints, although the lead and supplier
rehearsal roles run concurrently inside research. Debrief is shown for this scored
simulation; final waves disable lesson recording.

The older `export.py` and `src/replay.json` preserve the historical P05 recording and
its original-engine export instructions. They are not used by this monitor.

## Validation

```sh
cd pitch
npm run check
npm run build
# From the repository root:
uv run pytest -q tests/test_pitch_simulation.py
```

The exporter test verifies the offline path, untouched production memory, all pipeline
stages, complete outgoing sheets, progressive disclosure and the accepted total cost.
