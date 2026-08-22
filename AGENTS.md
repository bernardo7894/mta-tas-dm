# AGENTS.md — mta-tas-dm

## Repository Role

This repository provides the MTA:SA-side reference recorder for the larger `mta-sa-dm-standalone` project.

It is used to record real GTA:SA / MTA:SA vehicle behavior so that a future standalone physics implementation can be measured against it.

Read the parent workspace `AGENTS.md` for the overall project objective and methodology.

## Upstream

This repository is a fork of:

https://github.com/chris1384/mta-tas-dm

Original project: TAS / recording tooling for MTA:SA [DM].

Preserve the upstream project history and MIT license.

Do not unnecessarily rewrite or restructure upstream code. This fork should remain recognizable as an extension of `mta-tas-dm`.

## Physics-Analysis Branch

The standalone-project changes were initially developed on:

`physics-analysis-export`

The main implementation commit was created on top of upstream commit:

`db16023f3ade3f1e81eca37cff66d708d4f66754`

The purpose of these changes is to augment the existing TAS recorder with physics telemetry while preserving the ordinary `.tas` format and existing TAS behavior.

## Added Physics Telemetry

The fork adds a separate physics-analysis export. Format-v3 is backward
compatible with the existing format-v2 reader and adds optional wheel/gear
telemetry; ordinary `.tas` files are unchanged.

Command:

`/savephysics <name>`

Example:

`/savephysics first_dm_run`

Output:

`saves/<name>.physics.jsonl`

The normal TAS recording can still be saved independently with:

`/saver <name>`

The fork also provides `/saveboth <name>` to save both files in one command.

## Physics JSONL Contents

The extended export records information useful for reproducing Infernus dynamics.

Recording-level metadata includes information such as:

- format/version information;
- vehicle model;
- FPS limit;
- initial game speed;
- dimension;
- interior;
- `getVehicleHandling(vehicle)` output.

Per-frame information includes:

- recording tick/time;
- actual `onClientPreRender` delta time;
- derived FPS;
- game speed;
- position;
- Euler rotation;
- full element transform matrix;
- linear velocity;
- angular velocity;
- vehicle health;
- vehicle model;
- nitro state;
- original TAS key information;
- effective GTA control states;
- analog control values;
- all four wheel-on-ground states;
- collision events associated with the frame;
- optional format-v3 `vehicleTelemetry.currentGear`;
- optional explicit wheel identities in MTA order: `front_left`, `rear_left`,
  `front_right`, `rear_right`;
- per-wheel measured `onGround`, `frictionState`, structural `wheelState`,
  component positions, and component rotations in `parent`, `root`, and
  `world` bases when the MTA API returns them;
- explicitly labeled derived contact-point velocity and vehicle-basis
  projections. These are reconstructed from the recorded linear/angular
  velocity and observed point, not claimed to be GTA's private `contactSpeeds[]`;
- a clearly labeled Lua control-based steering estimate. MTA Lua does not
  expose private `m_fRawSteerAngle`/`m_fSteerAngle`, so those estimates are not
  measured internal GTA state.

Collision telemetry includes useful values exposed by MTA such as:

- collision impulse magnitude;
- body part;
- collision position;
- collision normal;
- hit-element force;
- world model ID / hit-element information.

This information is especially important for later wallride and landing analysis.

`onClientVehicleCollision` is an event stream, not a complete contact-manifold
stream. It can omit continuous suspension/ground contact, especially when the
vehicle is already resting on an object when recording begins. The per-frame
`wheelOnGround` values indicate contact but do not identify the world model.
Therefore `worldModel` IDs must not be treated as an exhaustive list of every
track surface used by a run.

## Compatibility Rule

Do not break the original `.tas` save/load format merely to add standalone-project telemetry.

Physics-analysis data should remain a separate export unless there is a strong reason to change this architecture.

Normal TAS usage should continue working.

## Recording Workflow

Typical experiment:

1. Start the MTA server.
2. Start the `tas` resource.
3. Enter an Infernus.
4. Run:

   `/record`

5. Drive the experiment or DM sequence.
6. Run `/record` again to stop.
7. Save both outputs:

   `/saveboth <name>`

   The traditional recording and physics telemetry can also be saved
   independently with `/saver <name>` and `/savephysics <name>`.

The `.tas` recording is useful for MTA playback/debugging. To replay a loaded
`.tas` while capturing fresh per-wheel ground probes, use
`/recordplayback <output-name>`; this writes a new `.physics.jsonl` without
changing the source `.tas` on disk.

The `.physics.jsonl` recording is the primary input for standalone physics analysis.
Format-v3 metadata records the API availability and component bases attempted;
missing APIs/components produce `nil` optional fields rather than dropping the
frame. On the local MTA 1.6.0.24139 installation, the wheel friction, wheel
contact, current-gear, and component position/rotation APIs are present in the
client binary and documented as client-side (wheel structural states are a
shared API).

## Benchmark Philosophy

Recorded state must not later be used to force a standalone vehicle along the same trajectory.

The intended standalone test is:

- initialize from the first recorded state;
- apply recorded controls;
- run independent physics;
- compare resulting state against recorded MTA state.

Position, rotation, velocity, and angular velocity are comparison targets.

## Current Development Focus

The first vehicle of interest is the Infernus.

Do not add complexity for general vehicle compatibility unless it directly helps the current experiments.

Useful initial data includes:

- air control;
- acceleration;
- steering;
- braking;
- wheel contacts;
- collisions;
- wallrides;
- nitro;
- landings.

## Local MTA Resource Deployment

`install-to-mta-server.bat` mirrors the modified `new\tas` resource into the local MTA server so repeated TAS development iterations are quick. It deliberately limits deployment to the server's `resources\tas` directory.

## Automated Reference Capture

The `tas` resource exposes two narrowly scoped, protected server exports:

- `startReferenceCapture(mapName, recordName, outputName, targetPlayer)`;
- `getReferenceCaptureStatus()`.

`tools/mta_reference_capture.py` calls those exports through MTA's authenticated
HTTP interface. The server selects the map and waits for the target race
vehicle; a normal server-to-client event then makes the client load its
private `.tas` file and run `/recordplayback`. No GUI focus, keyboard input, or
server-console interaction is part of this workflow. If controls-only playback
ends with the legacy `vehicle missing` message, the TAS resource also emits a
single diagnostic snapshot into the physics export as
`playbackFailureDiagnostic`; it distinguishes a dead player from a destroyed
or non-controller vehicle element and is mechanism evidence only.

The HTTP credential is an ordinary MTA server account, not a separate account
system. Its ACL group must allow `general.http` and `resource.tas`; keep the
latter limited to accounts intended to control captures. Use
`MTA_HTTP_USER`/`MTA_HTTP_PASSWORD` or the helper's explicit options, for
example:

```powershell
$env:MTA_HTTP_USER = "your-mta-account"
$env:MTA_HTTP_PASSWORD = "your-mta-password"
python tools/mta_reference_capture.py run `
  "DM Skynet v5 Etnies II" previous_record new_telemetry
```

The server and client must already be running and the player must be
connected. Use `--target-player` when more than one player is connected.
Detailed export fields and ACL notes are in `new\tas\PHYSICS_EXPORT.md`.

## Testing Changes

At minimum, ensure edited Lua remains syntactically valid.

For `client.lua`, run `luac -p` where a compatible Lua compiler is available.
The repository also has a Lua-stub telemetry harness under `tests/` covering
stable wheel ordering, measured fields, and unavailable component/friction
observables. The Python tests cover format-v2 parsing and format-v3 diagnostic
joining.

## Local native ProcessWheel capture

For the missing transient GTA observable, `tools/native_processwheel_capture.py`
uses the user's permissive `mtasa-blue` debug client and a pre-resume Frida
hook on US 1.0 `CVehicle::ProcessWheel` (VA `0x6D6C00`, RVA `0x2D6C00`). A
lower-overhead alternative in the local Debug `multiplayer_sa_d.dll` wraps the
four `ProcessCarWheelPair` call sites and calls the original function unchanged.
Both routes record direct entry arguments and clearly labeled private-state
fields without changing the captured function arguments. `contactSpeeds[4]`
are the `wheelContactSpeed` argument at ProcessWheel entry, after the preceding
GTA suspension pass. The capture tool's recommended `--controls-only-playback`
mode temporarily disables legacy TAS pose/velocity writes; without it, the TAS
resource imposes recorded state and the native rows are state-forced diagnostics.
`--pose-linear-only-playback` is a separate diagnostic mode that writes recorded
position/rotation/linear velocity but leaves angular velocity native; it is not
an independent trajectory. `--static-skid-diagnostics` reads the private
`bAlreadySkidding` global at `0xC1CDAC` on the Frida route; the C++ route has the
opt-in equivalent `--cpp-static-skid-diagnostics` and otherwise emits `0xFF`
sentinels for that optional field. `--collision-diagnostics` additionally
snapshots the native `aAutomobileColPoints` candidate buffer at RVA
`0x81BFF8`, `ProcessEntityCollision` output points, and ProcessSuspension
before/after state; these are direct collision-stage diagnostics and do not
make `m_wheelColPoint` a guaranteed fresh ray result. `--playback-start-delay-ms`
can warm the native timer before source playback, and `--capture-from-first-gas`
buffers Frida rows until the first nonzero pedal; both values are recorded in
metadata. `--suspension-stage-only` is a Frida-only reduced collision mode
that installs only the entity-collision and ProcessSuspension stage hooks;
its metadata must retain `suspension_stage_only=true`. In the local Debug
build, the stage observer reads exact TAS source tags through the non-mutating
`GetNativeProcessWheelSourceTagBridge` export; this replaces a render-clock
join but remains diagnostic because the observer can still perturb cadence and
stale tags after playback failure must be rejected. The timing probe emits
`timerOldStep`, `timerStepNonClipped`, and `timerStep` alongside game time.
`--one-tick-config` is a separate
state-input diagnostic that writes one public state/control sample and captures
native `ProcessControl` entry/exit; it is not continuous independent evidence.
Frida rows additionally snapshot the runtime handling engine acceleration,
engine inertia, max velocity, and physical velocity-frequency fields from the
vehicle's handling pointer; these are direct native diagnostics, not Lua
metadata. Narrow captures may lack `controlExit` even when the enclosing
`ApplyTurnForces` trace is present, so downstream oracle reports must preserve
that provenance explicitly.
`--cpp-no-matrix` isolates matrix-snapshot overhead,
and the C++ matrix snapshot is guarded in the local debug source for robust long
runs. With `--cpp-hook --collision-diagnostics`, the C++ route also records direct
`ApplyCollisionAlt` outputs at call sites `0x54C9FA` and `0x54CAC2`. The C++ route emits a binary batch stream converted by
`infernus-physics/tools/convert_native_processwheel_cpp.py`. The corresponding
alignment/report tool is `infernus-physics/tools/align_native_processwheel.py`.
A paired fps-limit-100 no-hook/C++ timing control matched at about
`995.003` versus `994.081` game-ms/s.

The local debug build currently needs its matching private capture server and
resource setup. The server harness uses `<fpslimit>100</fpslimit>` to match the
reference recording's 100 Hz cadence, and disables anti-cheats `4,56` because
the instrumented debug client is otherwise rejected; neither setting is part
of ordinary MTA recordings. `native_processwheel_capture.py --prepare-tas-folder`
temporarily switches the local TAS resource to its public `saves` folder so
large automated playback inputs are available without manual copying, then
restores the file. `--playback-output-name` selects a unique output name and
`--controls-only-playback` restores independent control replay. In
`--reference-map-resource` actual-race mode, the harness starts `race` and the
real map only after the server reports the client `JOIN`; `--duration` is the
post-JOIN retention budget, so a slow loader cannot consume the complete TAS
playback window before the map exists. For a normal local Debug client launch,
`--launcher-exe "...\\Multi Theft Auto_d.exe"` starts the real launcher and
attaches the observer to its new `gta_sa.exe` child only after server `JOIN`,
which avoids perturbing the launcher's L3 startup. The C++ ProcessWheel hook
is already active in inherited `multiplayer_sa_d.dll` before that late attach.
`--cpp-processcontrol-boundary` enables the matching direct
`CAutomobile::ProcessControl` entry/exit stream (`.control.bin`), and
`--cpp-processcontrol-source-window START END` limits it to a source-tagged
window; convert it with
`infernus-physics/tools/convert_native_processcontrol_cpp.py` and audit it
with `infernus-physics/tools/audit_native_processcontrol_boundary.py`. This
observer is diagnostic only because its extra reads can perturb render/source
cadence and later vehicle/resource addresses must be treated as contamination.
The server `JOIN` event is watched both on stdout and the server log because
redirected Debug-server stdout is not consistently flushed. Keep native rows separate from Lua
`vehicleTelemetry` fields and preserve their provenance when merging diagnostic
artifacts. The Debug C++ route also supports
`--cpp-processsuspension-boundary`, which hooks the US 1.0
`CAutomobile::ProcessSuspension` entry (`0x6AFB10`) through a copied-prologue
trampoline and writes a fixed `.suspension.bin` stream; convert and audit it
with the matching `infernus-physics` tools. This is a timing-filtered
boundary diagnostic, never hidden-state injection or continuous trajectory
evidence. A `*** NETWORK TROUBLE ***` overlay invalidates a
capture: `CNetAPI::DoPulse` raises it after a recent puresync enqueue and 10
seconds without processed return-sync, then freezes controls and vehicle
move/turn state. It is client recovery behavior, not a physics result; apply
the timing gate and reject the affected stream.

Also inspect the actual Git diff before committing. This upstream file historically uses CRLF line endings; avoid creating enormous diffs consisting only of line-ending normalization.

## Proprietary Assets

This repository does not need and should not contain Rockstar game assets.

Do not commit DFF, TXD, COL, or other extracted GTA:SA data here.

This repository's responsibility is MTA telemetry capture.

Map/GTA asset import belongs elsewhere in the workspace.

## Repository-Specific Persistent Notes

If a coding agent establishes a durable fact specific to this repository, it may update this `AGENTS.md`.

Examples:

- a new telemetry field;
- an export-format version change;
- an MTA API quirk important to recordings;
- a changed deployment workflow.

Project-wide architectural notes belong in the parent workspace `AGENTS.md`, not here.

Do not record transient debugging history in this file.
