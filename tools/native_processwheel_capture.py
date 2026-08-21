#!/usr/bin/env python3
"""Capture GTA's transient pre-ProcessWheel state from the local debug client.

This is intentionally a local instrumentation tool.  It targets the user's
instrumentable ``mtasa-blue`` build, not a production MTA installation.  The
four-wheel TAS/map resource must already be available to the local server; the
server is optional and can be started with ``--server-exe``.

The native hook is installed in the suspended GTA process before it resumes:
``CVehicle::ProcessWheel`` is at VA 0x6D6C00 in the US 1.0 executable, or RVA
0x2D6C00 from the normal 0x400000 image base.  Its entry arguments are read
without changing them.  Every JSONL row is explicitly marked
``gta-native-pre-ProcessWheel``; it is not Lua-derived telemetry.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

try:
    import frida
except ImportError as exc:  # pragma: no cover - environment-dependent
    raise SystemExit("Install frida in the 32-bit-capable Python environment") from exc

try:
    import psutil
except ImportError as exc:  # pragma: no cover - environment-dependent
    raise SystemExit("Install psutil for process cleanup") from exc


PROCESS_WHEEL_RVA = 0x2D6C00
PROCESS_CONTROL_RVA = 0x2B1880
IMAGE_BASE = 0x400000


def _js_string(value: str) -> str:
    return json.dumps(value.replace("\\", "/"))


def _native_script(mta_bin: Path, output_label: str) -> str:
    bin_dir = _js_string(str(mta_bin))
    mta_dir = _js_string(str(mta_bin / "MTA"))
    return f"""
'use strict';
const BIN_DIR = {bin_dir};
const MTA_DIR = {mta_dir};
const OUTPUT_LABEL = {_js_string(output_label)};
let bootstrapDone = false;

Process.setExceptionHandler(function(details) {{
    if (details.type === 'system' || details.type === 'breakpoint' || details.type === 'single-step')
        return true;
    send({{type:'native_exception', exceptionType:details.type, address:String(details.address), pc:String(details.context.pc)}});
    return false;
}});

// Frida's debugger makes OutputDebugString raise DBG_PRINTEXCEPTION_C.  The
// debug MTA build calls it in hot paths, so make the diagnostic channel a
// no-op without touching any physics code.
(function suppressOutputDebugString() {{
    for (const moduleName of ['kernel32.dll', 'kernelbase.dll']) {{
        try {{
            const module = Process.findModuleByName(moduleName);
            if (!module) continue;
            for (const name of ['OutputDebugStringA', 'OutputDebugStringW']) {{
                const address = module.findExportByName(name);
                if (address) Interceptor.replace(address, new NativeCallback(function(_) {{}}, 'void', ['pointer']));
            }}
        }} catch(_) {{}}
    }}
}})();

function exportOf(module, name) {{
    return module.findExportByName(name) || module.getExportByName(name);
}}
function callBootstrap() {{
    if (bootstrapDone) return;
    bootstrapDone = true;
    const k32 = Process.getModuleByName('kernel32.dll');
    const SetDllDirectoryW = new NativeFunction(exportOf(k32, 'SetDllDirectoryW'), 'bool', ['pointer']);
    const LoadLibraryW = new NativeFunction(exportOf(k32, 'LoadLibraryW'), 'pointer', ['pointer']);
    const GetProcAddress = new NativeFunction(exportOf(k32, 'GetProcAddress'), 'pointer', ['pointer','pointer']);
    SetDllDirectoryW(Memory.allocUtf16String(MTA_DIR));
    const netc = LoadLibraryW(Memory.allocUtf16String(MTA_DIR + '/netc_d.dll'));
    if (netc.isNull()) throw new Error('netc_d.dll failed to load');
    const setMta = GetProcAddress(netc, Memory.allocUtf8String('SetMTADirectory'));
    const setGta = GetProcAddress(netc, Memory.allocUtf8String('SetGTADirectory'));
    if (!setMta.isNull()) new NativeFunction(setMta, 'void', ['pointer','size_t'])(Memory.allocUtf16String(BIN_DIR), BIN_DIR.length);
    if (!setGta.isNull()) new NativeFunction(setGta, 'void', ['pointer','size_t'])(Memory.allocUtf16String(BIN_DIR), BIN_DIR.length);
    const initRev = GetProcAddress(netc, Memory.allocUtf8String('InitNetRev'));
    if (!initRev.isNull()) new NativeFunction(initRev, 'void', ['pointer','pointer','pointer'])(
        Memory.allocUtf8String('Software\\\\Multi Theft Auto: San Andreas All'),
        Memory.allocUtf8String('MTA San Andreas All'), Memory.allocUtf8String('1.6.0-9.00000'));
    const check = GetProcAddress(netc, Memory.allocUtf8String('CheckService'));
    if (!check.isNull()) new NativeFunction(check, 'bool', ['uint32'])(7);
    const core = LoadLibraryW(Memory.allocUtf16String(MTA_DIR + '/core_d.dll'));
    if (core.isNull()) throw new Error('core_d.dll failed to load');
    const setMtaCore = GetProcAddress(core, Memory.allocUtf8String('SetMTADirectory'));
    const setGtaCore = GetProcAddress(core, Memory.allocUtf8String('SetGTADirectory'));
    if (!setMtaCore.isNull()) new NativeFunction(setMtaCore, 'void', ['pointer','size_t'])(Memory.allocUtf16String(BIN_DIR), BIN_DIR.length);
    if (!setGtaCore.isNull()) new NativeFunction(setGtaCore, 'void', ['pointer','size_t'])(Memory.allocUtf16String(BIN_DIR), BIN_DIR.length);
    const init = GetProcAddress(core, Memory.allocUtf8String('InitializeCore'));
    if (init.isNull()) throw new Error('InitializeCore export missing');
    send({{type:'native_bootstrap', core:String(core), netc:String(netc)}});
    new NativeFunction(init, 'int32', [])();
}}

// GTA calls this on its main thread during startup.  Keeping bootstrap here,
// rather than in a Frida timer, preserves the game's thread/order semantics.
try {{
    const gv = Process.getModuleByName('kernel32.dll').findExportByName('GetVersionExA');
    Interceptor.attach(gv, {{ onEnter() {{
        if (!bootstrapDone) {{ try {{ callBootstrap(); }} catch(e) {{ send({{type:'native_bootstrap_error', message:String(e)}}); }} }}
    }} }});
}} catch(e) {{ send({{type:'native_bootstrap_error', message:String(e)}}); }}

(function installNativeWheelHook() {{
    const main = Process.mainModule;
    const processWheel = main.base.add({PROCESS_WHEEL_RVA});
    const processControl = main.base.add({PROCESS_CONTROL_RVA});
    const gameFrameCounter = main.base.add(0x77CB4C);
    const gameTimeMs = main.base.add(0x77CB84);
    let frame = 0, processCalls = 0, wheelCalls = 0, batch = [];
    const f = p => {{ try {{ return p.readFloat(); }} catch(_) {{ return null; }} }};
    const u8 = p => {{ try {{ return p.readU8(); }} catch(_) {{ return null; }} }};
    const s32 = p => {{ try {{ return p.readS32(); }} catch(_) {{ return null; }} }};
    const vec = p => {{ try {{ return [p.readFloat(),p.add(4).readFloat(),p.add(8).readFloat()]; }} catch(_) {{ return null; }} }};
    const array4 = p => [0,1,2,3].map(i => f(p.add(i * 4)));
    const dot = (a,b) => a && b ? a[0]*b[0]+a[1]*b[1]+a[2]*b[2] : null;
    const delta = (a,b) => a && b ? a.map((v,i) => v-b[i]) : null;
    const expectedWheelEntry = [0x83,0xec,0x48,0xd9,0x05];
    for (let i=0; i<expectedWheelEntry.length; i++)
        if (processWheel.add(i).readU8() !== expectedWheelEntry[i])
            throw new Error('ProcessWheel signature mismatch at '+processWheel+'; refusing hardcoded hook');
    function flush() {{ if (batch.length) {{ send({{type:'native_batch', label:OUTPUT_LABEL, records:batch}}); batch=[]; }} }}
    try {{
        Interceptor.attach(processControl, {{ onEnter() {{
            const vehicle = this.context.ecx;
            try {{ if (vehicle.add(0x22).readU16() === 411) {{ frame++; processCalls++; }} }} catch(_) {{}}
        }} }});
        Interceptor.attach(processWheel, {{
            onEnter() {{
                const vehicle = this.context.ecx;
                try {{ if (vehicle.add(0x22).readU16() !== 411) return; }} catch(_) {{ return; }}
                const sp = this.context.esp;
                const fwdPtr=sp.add(4).readPointer(), rightPtr=sp.add(8).readPointer();
                const speedPtr=sp.add(12).readPointer(), pointPtr=sp.add(16).readPointer();
                const wheelSpeedPtr=sp.add(40).readPointer(), wheelStatePtr=sp.add(44).readPointer();
                const fwd=vec(fwdPtr), right=vec(rightPtr), speed=vec(speedPtr);
                const beforeLinear=vec(vehicle.add(0x44)), beforeAngular=vec(vehicle.add(0x50));
                this.nativeVehicle=vehicle; this.nativeState=wheelStatePtr;
                this.nativeRecord={{
                    source:'gta-native-pre-ProcessWheel', label:OUTPUT_LABEL, frame,
                    gameFrame:(()=>{{try{{return gameFrameCounter.readU32()}}catch(_){{return null}}}})(),
                    gameTimeMs:(()=>{{try{{return gameTimeMs.readU32()}}catch(_){{return null}}}})(),
                    vehicle:vehicle.toString(), wheelId:s32(sp.add(36)), wheelsOnGround:s32(sp.add(20)),
                    thrust:f(sp.add(24)), brake:f(sp.add(28)), adhesion:f(sp.add(32)),
                    wheelStatus:(()=>{{try{{return sp.add(48).readU16()}}catch(_){{return null}}}})(),
                    wheelFwd:fwd, wheelRight:right, contactSpeedRaw:speed,
                    contactSpeedFwd:dot(fwd,speed), contactSpeedRight:dot(right,speed),
                    contactPointRelative:vec(pointPtr),
                    placeablePosition:vec(vehicle.add(4)),
                    matrix:(()=>{{try{{const q=vehicle.add(0x14).readPointer();return [vec(q),vec(q.add(0x10)),vec(q.add(0x20)),vec(q.add(0x30))]}}catch(_){{return null}}}})(),
                    wheelSpeed:(()=>{{try{{return wheelSpeedPtr.readFloat()}}catch(_){{return null}}}})(),
                    wheelStateBefore:(()=>{{try{{return wheelStatePtr.readU32()}}catch(_){{return null}}}})(),
                    suspensionCompression:array4(vehicle.add(0x7D4)),
                    suspensionCompressionPrev:array4(vehicle.add(0x7E4)), wheelCounts:array4(vehicle.add(0x7F4)),
                    steerAngle:f(vehicle.add(0x494)), rawSteerAngle:f(vehicle.add(0x58C)),
                    gasPedal:f(vehicle.add(0x49C)), brakePedal:f(vehicle.add(0x4A0)),
                    contactWheels:u8(vehicle.add(0x960)), driveWheels:u8(vehicle.add(0x961)),
                    linearVelocityBefore:beforeLinear, angularVelocityBefore:beforeAngular
                }};
                wheelCalls++;
            }},
            onLeave() {{
                const record=this.nativeRecord, vehicle=this.nativeVehicle;
                if (!record || !vehicle) return;
                const afterLinear=vec(vehicle.add(0x44)), afterAngular=vec(vehicle.add(0x50));
                record.linearVelocityAfter=afterLinear; record.angularVelocityAfter=afterAngular;
                record.linearVelocityDelta=delta(afterLinear,record.linearVelocityBefore);
                record.angularVelocityDelta=delta(afterAngular,record.angularVelocityBefore);
                try {{ record.wheelStateAfter=this.nativeState.readU32(); }} catch(_) {{ record.wheelStateAfter=null; }}
                batch.push(record); if (batch.length >= 32) flush();
            }}
        }});
    }} catch(e) {{ send({{type:'native_hook_error', message:String(e)}}); }}
    setInterval(flush,100); setInterval(() => send({{type:'native_counts', processCalls, wheelCalls, frame}}),3000);
}})();
"""


def _kill_targets() -> None:
    for process in psutil.process_iter(["name"]):
        if (process.info["name"] or "").lower() in {
            "gta_sa.exe", "mta server_d.exe", "mta server.exe", "multi theft auto_d.exe"
        }:
            try:
                process.kill()
            except psutil.Error:
                pass


def _start_server(path: Path, commands: list[str]) -> tuple[subprocess.Popen[str], threading.Thread]:
    process = subprocess.Popen(
        [str(path)], cwd=str(path.parent), stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
    )
    def drain() -> None:
        if process.stdout is None:
            return
        for line in process.stdout:
            if any(token in line for token in ("Server started", "CONNECT:", "JOIN:", "KICK:", "ERROR:")):
                print(f"[server] {line.rstrip()}")
    thread = threading.Thread(target=drain, daemon=True)
    thread.start()
    # The debug server's stdout is not consistently flushed through the
    # redirected pipe on Windows.  Keep a bounded startup delay rather than
    # depending on that diagnostic stream for synchronization.
    time.sleep(15)
    for command in commands:
        if process.stdin is not None:
            process.stdin.write(command + "\n")
            process.stdin.flush()
        time.sleep(2)
    return process, thread


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gta-exe", type=Path, default=Path(os.environ.get("MTA_GTA_EXE", "gta_sa.exe")))
    parser.add_argument("--mta-bin", type=Path, default=Path(os.environ.get("MTA_BIN", ".")))
    parser.add_argument("--server-exe", type=Path)
    parser.add_argument("--start-resource", action="append", default=[])
    parser.add_argument(
        "--orchestrator",
        type=Path,
        help=(
            "optional local mtasa_deobfuscation/mta_bytecode_orchestrator.py; "
            "its proven Frida-native bootstrap/survival hooks are used when supplied"
        ),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--duration", type=float, default=240.0)
    parser.add_argument("--label", default="native-processwheel")
    args = parser.parse_args()
    _kill_targets()
    os.environ["MTA_BIN"] = str(args.mta_bin.resolve())
    server = None
    if args.server_exe:
        server, _ = _start_server(
            args.server_exe.resolve(),
            ["refresh", *[f"start {name}" for name in args.start_resource]],
        )

    device = frida.get_local_device()
    gta = args.gta_exe.resolve()
    pid = device.spawn(str(gta), argv=[str(gta)], cwd=str(gta.parent))
    session = device.attach(pid)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "format": "gta-native-pre-processwheel-capture",
        "format_version": 1,
        "label": args.label,
        "gta_executable": str(gta),
        "mta_bin": str(args.mta_bin.resolve()),
        "process_wheel_va": hex(IMAGE_BASE + PROCESS_WHEEL_RVA),
        "process_wheel_rva": hex(PROCESS_WHEEL_RVA - IMAGE_BASE),
        "direct_observable": "CVehicle::ProcessWheel entry arguments and vehicle state",
    }
    meta_path = args.output.with_suffix(args.output.suffix + ".meta.json")
    meta_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    def on_message(message: dict[str, Any], data: bytes | None) -> None:
        if message.get("type") != "send":
            if message.get("type") == "error":
                print(f"[frida-error] {message}")
            return
        payload = message.get("payload") or {}
        if not isinstance(payload, dict):
            return
        kind = payload.get("type")
        if kind == "native_batch":
            with args.output.open("a", encoding="utf-8") as stream:
                for row in payload.get("records", []):
                    stream.write(json.dumps(row, separators=(",", ":")) + "\n")
        elif kind in {"native_bootstrap", "native_bootstrap_error", "native_hook_error", "native_exception"}:
            print(f"[frida] {payload}")
        elif kind == "native_counts":
            print(f"[native] process={payload.get('processCalls')} wheel={payload.get('wheelCalls')} frame={payload.get('frame')}")

    native_script = _native_script(args.mta_bin.resolve(), args.label)
    if args.orchestrator:
        if not args.orchestrator.exists():
            parser.error(f"orchestrator does not exist: {args.orchestrator}")
        spec = importlib.util.spec_from_file_location("mta_native_bootstrap", args.orchestrator)
        if spec is None or spec.loader is None:
            parser.error(f"could not load orchestrator: {args.orchestrator}")
        bootstrap_module = importlib.util.module_from_spec(spec)
        sys.modules["mta_native_bootstrap"] = bootstrap_module
        spec.loader.exec_module(bootstrap_module)
        marker = "(function installNativeWheelHook()"
        native_only = "const OUTPUT_LABEL = " + json.dumps(args.label) + ";\n" + native_script[native_script.index(marker):]
        native_script = bootstrap_module.build_frida_script(args.label) + "\n" + native_only

    script = session.create_script(native_script)
    script.on("message", on_message)
    script.load()
    device.resume(pid)
    try:
        time.sleep(max(0.0, args.duration))
    finally:
        # Kill first: a Frida session with a busy callback queue can block
        # indefinitely while detaching from the debug client.
        try:
            device.kill(pid)
        except Exception:
            pass
        try:
            session.detach()
        except Exception:
            pass
        if server is not None and server.poll() is None:
            try:
                if server.stdin is not None:
                    server.stdin.write("shutdown\n")
                    server.stdin.flush()
                server.wait(timeout=10)
            except Exception:
                server.kill()
    print(f"native capture written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
