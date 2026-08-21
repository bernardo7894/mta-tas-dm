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
4. Prepare a local server resource that creates the model-411 vehicle and
   starts the TAS playback. Set the local server `<fpslimit>` to `100` to
   match the reference recording; the previous default `74` changes native
   timer cadence. The validated local server also disabled anti-cheats `4,56`
   because the debug client was rejected by those checks.

The tool's `--prepare-registry`, `--prepare-tas-folder`, `--controls-only-playback`, `--playback-output-name`, and `--use-real-vorbis` options temporarily
point the 32-bit MTA registry location at the debug tree and replace the
`vorbisfile.dll` loader proxy with the local `vorbisfile_real.dll`. Both are
restored in the cleanup path. A local orchestrator script may be passed with
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
`MTA_NATIVE_PROCESSWHEEL_CPP_OUTPUT` is set. Use `--cpp-hook` to select this
route; convert its sibling `.cpp.bin` file with
`infernus-physics/tools/convert_native_processwheel_cpp.py`. The default
Frida route remains available for cross-checking. `--timing-only` runs the
same automated playback without either ProcessWheel hook and reports timer
samples, providing a no-hook timing control. The optional
`--collision-diagnostics` flag adds read-only `ProcessCollision`,
`CheckCollision`, `ProcessControlCollisionCheck`, `ApplyForce`,
`ApplyTurnForce`, and `ApplyCollisionAlt` snapshots to the Frida route; it is
intended for collision/source classification, not the minimal timing capture.
The recommended `--controls-only-playback` mode temporarily disables TAS pose,
velocity, and angular-velocity playback and applies only recorded controls.
Without it, legacy TAS playback imposes recorded state and native rows are
state-forced diagnostics rather than an independent trajectory. For long C++
controls-only runs, `--cpp-no-matrix` isolates matrix-snapshot overhead; the
local C++ matrix read is also SEH-guarded. `--pose-linear-only-playback` is a
separate diagnostic mode that forces recorded position/rotation/linear velocity
while leaving angular velocity native, and must not be treated as an independent
trajectory.

Example:

```powershell
python tools/native_processwheel_capture.py `
  --gta-exe "D:\Users\Bernardo\Documents\mtasa-blue\Bin\gta_sa.exe" `
  --mta-bin "D:\Users\Bernardo\Documents\mtasa-blue\Bin" `
  --server-exe "D:\Users\Bernardo\Documents\mtasa-blue\Bin\server\MTA Server_d.exe" `
  --start-resource tas --start-resource native_capture `
  --orchestrator "C:\Users\berna\mtasa_deobfuscation\mta_bytecode_orchestrator.py" `
  --prepare-registry --prepare-tas-folder --controls-only-playback --playback-output-name native-etnies-auto --use-real-vorbis `
  --output "..\infernus-physics\generated\native-processwheel.jsonl"
```

For the lower-overhead build, add `--cpp-hook`; after playback, convert the
sibling binary stream. Combining `--cpp-hook --collision-diagnostics` also
writes a `.collision.bin` stream from the two verified `ApplyCollisionAlt`
call sites (`0x54C9FA`, `0x54CAC2`); convert it with
`infernus-physics/tools/convert_native_collision_alt_cpp.py` when auditing
GTA's direct collision response.

After playback, convert the wheel sibling binary stream:

```powershell
python ..\infernus-physics\tools\convert_native_processwheel_cpp.py `
  "..\infernus-physics\generated\native-processwheel.jsonl.cpp.bin" `
  "..\infernus-physics\generated\native-processwheel-cpp.jsonl"
```
