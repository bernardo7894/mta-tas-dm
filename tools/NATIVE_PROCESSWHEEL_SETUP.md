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
   starts the TAS playback. The validated local server disabled anti-cheats
   `4,56` because the debug client was rejected by those checks.

The tool's `--prepare-registry` and `--use-real-vorbis` options temporarily
point the 32-bit MTA registry location at the debug tree and replace the
`vorbisfile.dll` loader proxy with the local `vorbisfile_real.dll`. Both are
restored in the cleanup path. A local orchestrator script may be passed with
`--orchestrator` to reuse its tested Frida survival/bootstrap hooks.

Example:

```powershell
python tools/native_processwheel_capture.py `
  --gta-exe "D:\Users\Bernardo\Documents\mtasa-blue\Bin\gta_sa.exe" `
  --mta-bin "D:\Users\Bernardo\Documents\mtasa-blue\Bin" `
  --server-exe "D:\Users\Bernardo\Documents\mtasa-blue\Bin\server\MTA Server_d.exe" `
  --start-resource tas --start-resource native_capture `
  --orchestrator "C:\Users\berna\mtasa_deobfuscation\mta_bytecode_orchestrator.py" `
  --prepare-registry --use-real-vorbis `
  --output "..\infernus-physics\generated\native-processwheel.jsonl"
```
