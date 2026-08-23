# Local `mtasa-blue` native capture setup

`native_processwheel_capture.py` is intended for the user's local permissive
`mtasa-blue` build. It does not bypass or modify a production MTA client.

## Required debug-client setup

1. Build the 32-bit Debug client modules (`core_d.dll`, `game_sa_d.dll`,
   `multiplayer_sa_d.dll`, and `client_d.dll`) from the local `mtasa-blue`
   source.
2. Use the US 1.0 GTA executable. The capture tool verifies the first bytes of
   `CVehicle::ProcessWheel` before installing its hook.
3. The debug `CCore::DoPostFramePulse` harness must request the local capture
   connection only after `m_pNet`, `m_pGame`, `m_pMultiplayer`, and `m_pGUI`
   are initialized. The local source change used for the validated capture is:

   ```cpp
   #if defined(MTA_DEBUG)
   static bool s_nativePhysicsCaptureConnectIssued = false;
   if (!s_nativePhysicsCaptureConnectIssued && m_pNet && m_pGame &&
       m_pMultiplayer && m_pGUI) {
       s_nativePhysicsCaptureConnectIssued = true;
       CCommandFuncs::Connect("127.0.0.1 22003 native");
   }
   #endif
   ```

   This is a harness launch aid only; it does not change GTA vehicle forces.
The native hook filters `m_nModelIndex == 411` before recording, so map
vehicles do not contaminate the Infernus stream.
4. For a synthetic smoke capture, prepare a local server resource that
   creates the model-411 vehicle and starts TAS playback. For continuous Etnies
   evidence, instead use `--reference-map-resource
   race-dm-Skynetv5-EtniesII(fix)` with `--prepare-tas-folder`. That mode stops
   the autostart `play` gamemode, starts the actual `race` gamemode and Etnies
   map resource, including `asd.lua`, `CSM.lua`, `palm2.lua`, and the map's
   race settings, then temporarily turns `native_capture` into a trigger-only
   resource that waits for the race's occupied Infernus. It restores the
   synthetic resource after cleanup. Set the local server `<fpslimit>` to
   `100` to match the reference recording; the previous default `74` changes
   native timer cadence. The validated local server also disabled anti-cheats
   `4,56` because the debug client was rejected by those checks.

The tool's `--prepare-registry`, `--prepare-gta-import`, `--prepare-tas-folder`, `--controls-only-playback`, `--playback-output-name`, and `--use-real-vorbis` options temporarily
point the 32-bit MTA registry location at the debug tree, redirect the
GTA `WINMM.dll` import to the local `mtasa.dll` loader proxy, and replace the
`vorbisfile.dll` loader proxy with the local `vorbisfile_real.dll`. Both
binary changes are restored in the cleanup path. Direct-Frida mode should
leave the GTA import as `WINMM.dll` and uses the self-contained Frida
bootstrap; loader mode uses `--prepare-gta-import` and disables that Frida
bootstrap so the loader and Frida never initialize core twice. For the stable
local-client route, pass `--launcher-exe "...\\Multi Theft Auto_d.exe"` instead:
the normal launcher creates GTA, the harness waits for server `JOIN`, then
attaches only to the new GTA child (both `gta_sa.exe` and the Debug
`gta_sa_d.exe` process names are recognized and stale children are killed).
The C++ hook has already initialized in `multiplayer_sa_d.dll`, so late Frida
attachment does not lose native rows and
does not perturb L3 startup. The server `JOIN` watcher checks both redirected
stdout and `server/mods/deathmatch/logs/server.log`. An interrupted
run is recovered by the next launch's process-kill and side-by-side restore
checks. Without `--prepare-gta-import`, direct spawning of an unpatched
executable can show “MTA: Unable to find winmm.dll import entry” only when a
loader proxy has been invoked in the wrong bootstrap state. Use
`--tas-automation-playback` only for the synthetic resource when the ordinary
`native_capture:start` client event is lost; actual-race mode uses its
trigger-only resource and the real race vehicle. The
`--server-command-after 45 "restart
native_capture"` option can schedule a same-process resource/vehicle restart
from the server console for lifecycle captures; it uses the console's CRLF
protocol and is cancelled during cleanup. A local orchestrator script may be passed with
`--orchestrator` to reuse its tested Frida survival/bootstrap hooks.

## Lower-overhead C++ hook

The local Debug `multiplayer_sa_d.dll` also contains an opt-in C++ wrapper at
the four `ProcessCarWheelPair` call sites (`0x6A567B`, `0x6A56E9`, `0x6A5B49`,
and `0x6A5BB7`). The source changes are in
`Client/multiplayer_sa/native_processwheel_capture.{h,cpp}`, the
`CMultiplayerSA.cpp` include/init call, and the corresponding `Multiplayer SA`
project/filter entries. Build `Multiplayer SA.vcxproj` as `Debug|Win32`. The
wrapper calls the original `0x6D6C00` function unchanged and writes a fixed
binary batch stream only when the environment variable
`MTA_NATIVE_PROCESSWHEEL_CPP_OUTPUT` is set. Non-minimal rows also capture the
private `m_aSuspensionSpringLength[4]`/`m_aSuspensionLineLength[4]` arrays at
`0x878`/`0x888` and the current `m_wheelColPoint` point/normal/surface fields
at `0x724` for line-fraction and collision-point reconstruction. Use `--cpp-hook` to select this
route; convert its sibling `.cpp.bin` file with
`infernus-physics/tools/convert_native_processwheel_cpp.py`; the converter
accepts the current 354-byte rows, the source-tagged 366-byte rows, and the
earlier 294/326-byte row formats. In the local Debug build, the TAS client
optionally calls `setNativeProcessWheelSourceTag(play_frame, frame_tick)` from
its playback render callback after writing that frame's digital/analog controls
and nitro state. Native ProcessWheel scheduling relative to that render
callback remains a separate timing observation and must be audited rather than
inferred from the tag. The C++ capture bridge exports it into each 366-byte row as
`sourceFrameTag`/`sourceTickMsTag`; production MTA clients have no such function
and remain unchanged. This is a diagnostic source-frame label, not a
pose/control injection or a continuous-trajectory correction.
Start both `tas` and `native_capture` explicitly when using this bridge.
The default Frida route remains available for cross-checking. `--timing-only` runs the
same automated playback without either ProcessWheel hook and reports timer
samples, providing a no-hook timing control. For `--cpp-hook` and
`--timing-only`, the harness deliberately uses its small self-contained bootstrap
instead of the optional large orchestrator payload: the latter can leave the
client stalled before TAS playback starts. The optional
`--collision-diagnostics` flag adds read-only `ProcessCollision`,
`ProcessEntityCollision` (`0x6ACE70`), `ProcessSuspension` (`0x6AFB10`),
`CheckCollision`, `ProcessControlCollisionCheck`, `ApplyForce`,
`ApplyTurnForce`, and `ApplyCollisionAlt` snapshots to the Frida route; it is
intended for collision/source classification, not the minimal timing capture.
The suspension snapshots include compression/count arrays and private wheel
collision points before/after the source stage. `--suspension-stage-only` is a
Frida-only reduced mode that installs only the entity-collision and suspension
stage hooks; its metadata records `suspension_stage_only: true`. It is still a
forensic diagnostic and must pass the native timing gate before use.
The recommended `--controls-only-playback` mode temporarily disables TAS pose,
velocity, and angular-velocity playback and applies only recorded controls.
For actual-race startup timing diagnostics, `--playback-load-settle-ms`
optionally waits after the TAS file is loaded and before `recordplayback`; it
is a harness timing control, not a physics-state change. Without it, legacy
TAS playback imposes recorded state and native rows are
state-forced diagnostics rather than an independent trajectory. For long C++
controls-only runs, `--cpp-no-matrix` isolates matrix-snapshot overhead; the
local C++ matrix read is also SEH-guarded. `--pose-linear-only-playback` is a
separate diagnostic mode that forces recorded position/rotation/linear velocity
while leaving angular velocity native, and must not be treated as an independent
trajectory. `--static-skid-diagnostics` (Frida) reads the private
`bAlreadySkidding` global at `0xC1CDAC` for source-semantic verification;
`--cpp-static-skid-diagnostics` enables the equivalent C++ direct read while
ordinary C++ rows use `0xFF` sentinels for those optional bytes. The separate
`--one-tick-config <json>` mode bypasses TAS playback, writes one public
state/control sample, and lets GTA execute naturally; optional `nativeInternal`
values initialize directly known private state before the matching
`ProcessControl` call. The server preparation matches the deployed
`nativeCapture:start` trigger by event signature rather than a stale output-name
literal, so source-tag-smoke and other trigger-only resource variants cannot
silently skip the one-tick event. Native ProcessWheel compression is post-normalized;
therefore `nativeInternal.suspensionCompressionInputConvention` must explicitly
be `raw-line-fraction` or `normalized-post-process-control`. Raw-line input is
normalized by GTA at the source `ProcessControl` boundary. The
For the narrow public-initializer handoff diagnostic, combine
`--frida-processwheel-source-window START END`,
`--frida-state-writer-source-window START END`,
`--frida-state-writer-capture-untagged`, and
`--frida-native-setter-capture-untagged-after-writer`. The last option retains
at most sixteen read-only `CVehicleSA::SetMoveSpeed` calls after the public
velocity/angular writer boundary, records the wrapper pointer and bounded
model-411 candidate scan, and labels untagged rows explicitly. It also enables
the narrow PDB-symbol `CPoolsSA::AddVehicle` hook (named lookup only, never
whole-module symbol enumeration), recording the model-411 client pointer,
returned `CVehicle*`, and returned-wrapper candidate. The v12 accepted audit
shows the AddVehicle client pointer equals the public initializer pointer and
its native candidate equals the later ProcessWheel pointer; the returned
`CVehicle*` to `CVehicleSA` method adjustment is source-backed virtual-base
conversion. The same bounded route also resolves the named
`CPhysicalSA::SetTurnSpeed` symbol during the public angular writer and records
an exact native private before/after snapshot. In accepted v15 evidence, only
angular velocity changes; compression, previous compression, counts, wheel
collision points, wheel states, flags, and transmission fields remain
unchanged. This remains a cache/Create/setter handoff observation only; it
never feeds a native pointer or private state to the simulator. Reject rows outside
the `.45..55` timer window or without a valid server `JOIN`, and reject the
broad runtime symbol-enumeration experiment because it stalls script load.

For a same-run public-angular-to-ProcessControl startup join, use the Frida
stage route with `--suspension-stage-only --collision-diagnostics
--frida-stage-source-window START END`, plus the bounded state-writer window
and `--frida-state-writer-capture-untagged`. The stage window limits serialized
ProcessControl rows to exact source tags while the named SetTurnSpeed hook
retains the untagged public-initializer handoff. The v16 audit joins the exact
model-411 pointer: the public setter/native setter is accepted at `gameTimeMs`
33743, accepted stage tags 1/2 are at 34014/34024, and tag 3 (`0.6175`) is
rejected. The first accepted stage entry differs from the setter output, while
tag-2 entry inherits tag-1 exit exactly. The intervening rejected/untagged
startup history is provenance only and cannot be replayed or injected.

To test whether the heavy ProcessControlCollisionCheck/ProcessCollision
observers themselves perturb this startup boundary, add
`--frida-stage-no-processcollision` together with
`--suspension-stage-only --frida-stage-source-window START END`. This is an
explicit lightweight stage route: it retains exact ProcessControl stage rows,
the named public/nested setter diagnostics, direct timer values, and matrices,
but omits the heavy collision-boundary observers. It remains diagnostic only;
private suspension/contact equivalence is not asserted by that route. The v18
controls-only repeat retained accepted tags 1--3 and the same approximately
`0.000578` rad/s setter-to-tag-1 entry difference, so heavy collision observer
overhead is not a sufficient explanation. The missing untagged/rejected
interval remains excluded from continuous acceptance.

The `bVehicleColProcessed` bit is byte `0x42B`, bit 0. The hook records
`CTimer::GetTimeStep` at `0x77CB5C`; pass that observed multiplier to
`tools/run_one_tick_simulator.py --native-timer-step`, and pass the same config
with `--native-internal-config` for a same-hidden-state local comparison. The
optional config field `oneTickDelayMs` delays the public state event so a
one-tick experiment can be run after client startup has warmed; this is
required when measuring a stable `0.5` timestep rather than launch-time
stalls. For a state-input target whose first post-teleport tick is irregular,
`oneTickWarmHoldMs` reapplies the public target state for a bounded diagnostic
window and `nativeInternal.requireStableTimerStep=true` makes the Frida hidden-
state write wait until `timerStep` is explicitly inside `.45..55`; audit the
target selection separately from surrounding rejected timer samples.
`nativeInternal.wheelStates` uses native order `FL,RL,FR,RR` and is
written at the source-backed `CAutomobile::m_WheelStates` offset `0x968`.
Compare its `controlEntry`/`controlExit` rows with the simulator's pre-step
diagnostic; it is state-input evidence, not a continuous trajectory benchmark.
The comparator maps native wheel order `FL,RL,FR,RR` to simulator ray order
`FL,FR,RL,RR` explicitly.

Example:

```powershell
python tools/native_processwheel_capture.py `
  --gta-exe "D:\Users\Bernardo\Documents\mtasa-blue\Bin\gta_sa.exe" `
  --mta-bin "D:\Users\Bernardo\Documents\mtasa-blue\Bin" `
  --server-exe "D:\Users\Bernardo\Documents\mtasa-blue\Bin\server\MTA Server_d.exe" `
  --start-resource tas --start-resource native_capture `
  --tas-automation-playback `
  --orchestrator "C:\Users\berna\mtasa_deobfuscation\mta_bytecode_orchestrator.py" `
  --prepare-registry --prepare-tas-folder --controls-only-playback --playback-output-name native-etnies-auto --use-real-vorbis `
  --output "..\infernus-physics\generated\native-processwheel.jsonl"
```

For a real Etnies run, use a duration that retains the complete 17,781-frame
playback; the harness rejects a shorter duration in actual-race mode:

```powershell
python tools/native_processwheel_capture.py `
  --gta-exe "D:\Users\Bernardo\Documents\mtasa-blue\Bin\gta_sa.exe" `
  --mta-bin "D:\Users\Bernardo\Documents\mtasa-blue\Bin" `
  --server-exe "D:\Users\Bernardo\Documents\mtasa-blue\Bin\server\MTA Server_d.exe" `
  --reference-map-resource "race-dm-Skynetv5-EtniesII(fix)" `
  --reference-record-name etnies-native `
  --prepare-registry --prepare-gta-import --prepare-tas-folder `
  --playback-start-delay-ms 30000 --duration 300 `
  --cpp-hook --playback-output-name actual-race `
  --output "..\infernus-physics\generated\actual-race.jsonl"
```

For the lower-overhead build, add `--cpp-hook`; after playback, convert the
sibling binary stream. To obtain the direct launch-boundary diagnostic with
the lower-overhead wheel route, add
`--cpp-minimal --cpp-processsuspension-boundary`. The `.suspension.bin`
sibling is converted and audited separately from the wheel stream. `--cpp-processcontrol-boundary` additionally writes a
`.control.bin` stream of direct `CAutomobile::ProcessControl` entry/exit
state; limit it with `--cpp-processcontrol-source-window START END` when
investigating a bounded source window. Convert it with
`infernus-physics/tools/convert_native_processcontrol_cpp.py` and audit it
with `infernus-physics/tools/audit_native_processcontrol_boundary.py`. This
stream is diagnostic only: its observer can perturb render/source cadence,
so it must not be used as continuous trajectory evidence.

`--cpp-processsuspension-boundary` additionally writes a `.suspension.bin`
stream from a direct entry trampoline at `CAutomobile::ProcessSuspension`
(`0x6AFB10`). The trampoline copies the verified original prologue and calls
that original body unchanged; it records before/after private compression,
previous compression, wheel counts, collision points/normals, wheel states,
pedals, latch byte, source tags, and the three native timer values. Convert it
with `infernus-physics/tools/convert_native_processsuspension_cpp.py` and audit
it with `infernus-physics/tools/audit_native_processsuspension_boundary.py`.
The stream is a timing-filtered forensic boundary diagnostic, not hidden-state
injection or continuous trajectory evidence. A valid target window does not
waive the complete real-resource controls-only requirement; map-restart
vehicle addresses and rejected timer rows remain contamination. A launcher
attempt without a server `JOIN`, or a stream whose native `gameTimeMs` remains
at startup values (for example `0` with `timerStep=1`), is rejected outright;
those rows are bootstrap/observer provenance rather than native physics
comparison evidence.

Combining
`--cpp-hook --collision-diagnostics` also writes a `.collision.bin` stream from the two verified `ApplyCollisionAlt`
call sites (`0x54C9FA`, `0x54CAC2`). The harness automatically enables the
diagnostic `MTA_NATIVE_COLLISION_ALT_CPP_FLUSH_EVERY=1` mode so a final partial
batch is persisted; metadata records `cpp_collision_flush_every=true`. Convert
it with `infernus-physics/tools/convert_native_collision_alt_cpp.py` when
auditing GTA's direct collision response.

After playback, convert the wheel sibling binary stream:

```powershell
python ..\infernus-physics\tools\convert_native_processwheel_cpp.py `
  "..\infernus-physics\generated\native-processwheel.jsonl.cpp.bin" `
  "..\infernus-physics\generated\native-processwheel-cpp.jsonl"
```
