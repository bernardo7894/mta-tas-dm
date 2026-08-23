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


def _native_script(
    mta_bin: Path,
    output_label: str,
    *,
    install_wheel_hook: bool = True,
    collision_diagnostics: bool = False,
    suspension_stage_only: bool = False,
    stage_force_diagnostics: bool = False,
    stage_force_events: bool = False,
    stage_force_source_window: tuple[int, int] | None = None,
    static_skid_diagnostics: bool = False,
    capture_from_first_gas: bool = False,
    one_tick_config: dict[str, Any] | None = None,
    skip_frida_bootstrap: bool = False,
    processwheel_source_window: tuple[int, int] | None = None,
    paired_processsuspension: bool = False,
    processcollision_source_window: tuple[int, int] | None = None,
    processsuspension_source_window: tuple[int, int] | None = None,
    writer_diagnostics: bool = True,
    transmission_diagnostics: bool = True,
    state_writer_source_window: tuple[int, int] | None = None,
    capture_untagged_state_writers: bool = False,
    source_tag_order_diagnostics: bool = False,
) -> str:
    bin_dir = _js_string(str(mta_bin))
    mta_dir = _js_string(str(mta_bin / "MTA"))
    return f"""
'use strict';
const BIN_DIR = {bin_dir};
const MTA_DIR = {mta_dir};
const OUTPUT_LABEL = {_js_string(output_label)};
const INSTALL_NATIVE_WHEEL_HOOK = {str(install_wheel_hook).lower()};
const INSTALL_COLLISION_DIAGNOSTICS = {str(collision_diagnostics).lower()};
const INSTALL_PAIRED_SUSPENSION = {str(paired_processsuspension).lower()};
const SUSPENSION_STAGE_ONLY = {str(suspension_stage_only).lower()};
const STAGE_FORCE_DIAGNOSTICS = {str(stage_force_diagnostics).lower()};
const STAGE_FORCE_EVENTS = {str(stage_force_events).lower()};
const STAGE_FORCE_SOURCE_WINDOW = {json.dumps(list(stage_force_source_window) if stage_force_source_window else None)};
const INSTALL_STATIC_SKID_DIAGNOSTICS = {str(static_skid_diagnostics).lower()};
const CAPTURE_FROM_FIRST_GAS = {str(capture_from_first_gas).lower()};
const PROCESSWHEEL_SOURCE_WINDOW = {json.dumps(list(processwheel_source_window) if processwheel_source_window else None)};
const PROCESSCOLLISION_SOURCE_WINDOW = {json.dumps(list(processcollision_source_window) if processcollision_source_window else None)};
const PROCESSSUSPENSION_SOURCE_WINDOW = {json.dumps(list(processsuspension_source_window) if processsuspension_source_window else None)};
const STATE_WRITER_SOURCE_WINDOW = {json.dumps(list(state_writer_source_window) if state_writer_source_window else None)};
const CAPTURE_UNTAGGED_STATE_WRITERS = {str(capture_untagged_state_writers).lower()};
const INSTALL_SOURCE_TAG_ORDER_DIAGNOSTICS = {str(source_tag_order_diagnostics).lower()};
const INSTALL_STATE_WRITER_DIAGNOSTICS = {str(writer_diagnostics).lower()};
const INSTALL_TRANSMISSION_DIAGNOSTICS = {str(transmission_diagnostics).lower()};
const ONE_TICK_CONFIG = {json.dumps(one_tick_config or {}, separators=(",", ":"))};
let bootstrapDone = false;

Process.setExceptionHandler(function(details) {{
    if (details.type === 'system' || details.type === 'breakpoint' || details.type === 'single-step') {{
        send({{type:'native_exception', exceptionType:details.type, address:String(details.address), pc:String(details.context.pc)}});
        return true;
    }}
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
    // A Frida-spawned GTA process has frida-helper32.exe as its parent.  The
    // unmodified core derives its MTA root from that parent before consulting
    // the prepared registry value.  Block only OpenProcess calls originating
    // from core_d.dll so the source path-resolution behavior falls back to the
    // deliberately prepared local registry entry; do not globally alter GTA.
    try {{
        let coreOpenProcessBlocked = false;
        for (const moduleName of ['kernel32.dll', 'kernelbase.dll']) {{
            const module = Process.findModuleByName(moduleName);
            const address = module && module.findExportByName('OpenProcess');
            if (!address) continue;
            Interceptor.attach(address, {{
                onEnter() {{
                    const caller = this.returnAddress;
                    this.blockCoreCall = !coreOpenProcessBlocked
                        && caller.compare(core.base) >= 0
                        && caller.compare(core.base.add(core.size)) < 0;
                }},
                onLeave(retval) {{
                    if (this.blockCoreCall) {{
                        coreOpenProcessBlocked = true;
                        retval.replace(ptr(0));
                    }}
                }},
            }});
        }}
    }} catch (_) {{}}
    // Debug CCore construction can expose an uninitialized m_pXML field at
    // CreateXML.  Guard only the known constructor path: a nonzero value that
    // is not a loaded module is heap garbage, not a valid XML interface.
    try {{
        const matches = Memory.scanSync(
            core.base, core.size,
            '55 8B EC 56 8B F1 8B 46 04 85 C0 75'
        );
        if (matches.length) {{
            Interceptor.attach(matches[0].address, {{
                onEnter() {{
                    const object = this.context.ecx;
                    const value = object.add(4).readU32();
                    if (value !== 0 && !Process.findModuleByAddress(ptr(value)))
                        object.add(4).writeU32(0);
                }},
            }});
        }}
    }} catch (_) {{}}
    const init = GetProcAddress(core, Memory.allocUtf8String('InitializeCore'));
    if (init.isNull()) throw new Error('InitializeCore export missing');
    send({{type:'native_bootstrap_stage', stage:'libraries-loaded'}});
    send({{type:'native_bootstrap', core:String(core), netc:String(netc)}});
    send({{type:'native_bootstrap_stage', stage:'before-InitializeCore'}});
    const initResult = new NativeFunction(init, 'int32', [])();
    send({{type:'native_bootstrap_stage', stage:'after-InitializeCore', result:initResult}});
}}

// GTA calls this on its main thread during startup.  Keeping bootstrap here,
// rather than in a Frida timer, preserves the game's thread/order semantics.
// In loader mode the patched mtasa.dll owns this step; attaching a second
// Frida bootstrap would create mixed/double core initialization.
if (!{str(skip_frida_bootstrap).lower()}) {{
try {{
    const gv = Process.getModuleByName('kernel32.dll').findExportByName('GetVersionExA');
    Interceptor.attach(gv, {{ onEnter() {{
        if (!bootstrapDone) {{ try {{ callBootstrap(); }} catch(e) {{ send({{type:'native_bootstrap_error', message:String(e)}}); }} }}
    }} }});
}} catch(e) {{ send({{type:'native_bootstrap_error', message:String(e)}}); }}
}}

if (INSTALL_NATIVE_WHEEL_HOOK || INSTALL_COLLISION_DIAGNOSTICS
    || INSTALL_SOURCE_TAG_ORDER_DIAGNOSTICS
    || Array.isArray(PROCESSWHEEL_SOURCE_WINDOW)
    || Array.isArray(PROCESSSUSPENSION_SOURCE_WINDOW)
    || Array.isArray(STATE_WRITER_SOURCE_WINDOW)) {{
(function installNativeWheelHook() {{
    const main = Process.mainModule;
    const processWheel = main.base.add({PROCESS_WHEEL_RVA});
    const processControl = main.base.add({PROCESS_CONTROL_RVA});
    const setMoveSpeedRva = 0x15BD10;
    const vehicleSetMoveSpeedRva = 0x1DE7B0;
    const staticSetElementVelocityRva = 0x7B0010;
    // CStaticFunctionDefinitions::SetElementAngularVelocity in the local
    // Debug client_d.dll.  This is a read-only writer diagnostic: it records
    // the public TAS setter call and never changes its arguments or return.
    const staticSetElementAngularVelocityRva = 0x7AE0B0;
    const processControlCollisionCheck = main.base.add(0x2A29C0);
    const processEntityCollision = main.base.add(0x2ACE70);
    const automobileCollisionPoints = main.base.add(0x81BFF8);
    const processSuspension = main.base.add(0x2AFB10);
    const processCollision = main.base.add(0x14DFB0);
    const checkCollision = main.base.add(0x14D920);
    const applyForce = main.base.add(0x142B50);
    const applyTurnForce = main.base.add(0x142A50);
    const applyCollisionAlt = main.base.add(0x144D50);
    const processFriction = main.base.add(0x1483D0);
    const calculateDriveAcceleration = main.base.add(0x2D05E0);
    const applyFrictionForce = main.base.add(0x143220);
    const gameFrameCounter = main.base.add(0x77CB4C);
    const timerOldStep = main.base.add(0x77CB54);
    const timerStepNonClipped = main.base.add(0x77CB58);
    const timerStep = main.base.add(0x77CB5C);
    const gameTimeMs = main.base.add(0x77CB84);
    const staticAlreadySkidding = main.base.add(0x81CDAC);
    let frame = 0, processCalls = 0, wheelCalls = 0, batch = [];
    let sourceTagBridgeEvents = [];
    let captureActive = !CAPTURE_FROM_FIRST_GAS;
    const preCaptureRecords = [];
    const maxPreCaptureRecords = 512;
    let oneTickInjected = false;
    const controlStates = new Map();
    let activeControlKey = null;
    let activeSuspensionControlKey = null;
    let activeSuspensionForceContext = null;
    const pendingCollisions = new Map();
    const f = p => {{ try {{ return p.readFloat(); }} catch(_) {{ return null; }} }};
    const u8 = p => {{ try {{ return p.readU8(); }} catch(_) {{ return null; }} }};
    const s32 = p => {{ try {{ return p.readS32(); }} catch(_) {{ return null; }} }};
    const vec = p => {{ try {{ return [p.readFloat(),p.add(4).readFloat(),p.add(8).readFloat()]; }} catch(_) {{ return null; }} }};
    const array4 = p => [0,1,2,3].map(i => f(p.add(i * 4)));
    const u32Array4 = p => [0,1,2,3].map(i => {{ try {{ return p.add(i * 4).readU32(); }} catch(_) {{ return null; }} }});
    let nativeSourceTagGetter = null;
    const readNativeSourceTag = () => {{
        try {{
            if (!nativeSourceTagGetter) {{
                const multiplayer = Process.findModuleByName('multiplayer_sa_d.dll');
                const address = multiplayer && multiplayer.findExportByName('GetNativeProcessWheelSourceTagBridge');
                if (!address) return {{frame:null, tick:null}};
                nativeSourceTagGetter = new NativeFunction(address, 'void', ['pointer', 'pointer']);
            }}
            const frame = Memory.alloc(4), tick = Memory.alloc(4);
            nativeSourceTagGetter(frame, tick);
            return {{frame:frame.readS32(), tick:tick.readS32()}};
        }} catch (_) {{
            nativeSourceTagGetter = null;
            return {{frame:null, tick:null}};
        }}
    }};
    const dot = (a,b) => a && b ? a[0]*b[0]+a[1]*b[1]+a[2]*b[2] : null;
    const delta = (a,b) => a && b ? a.map((v,i) => v-b[i]) : null;
    const suspensionSnapshot = vehicle => ({{
        compression:array4(vehicle.add(0x7D4)),
        compressionPrevious:array4(vehicle.add(0x7E4)),
        wheelCounts:array4(vehicle.add(0x7F4)),
        collisionPoints:[0,1,2,3].map(i => vec(vehicle.add(0x724 + i * 0x2C))),
        collisionNormals:[0,1,2,3].map(i => vec(vehicle.add(0x724 + i * 0x2C + 0x10))),
    }});
    const colPointSnapshot = point => ({{
        point:vec(point), fieldC:f(point.add(0x0C)), normal:vec(point.add(0x10)),
        field1C:f(point.add(0x1C)), surfaceA:u8(point.add(0x20)),
        pieceA:u8(point.add(0x21)), lightingA:u8(point.add(0x22)),
        surfaceB:u8(point.add(0x23)), pieceB:u8(point.add(0x24)),
        lightingB:u8(point.add(0x25)), depth:f(point.add(0x28)),
    }});
    const colPointArray = (base, count) => {{
        if (!base || base.isNull()) return null;
        const result = [];
        for (let i = 0; i < count; i++) {{
            try {{ result.push(colPointSnapshot(base.add(i * 0x2C))); }}
            catch (_) {{ result.push(null); }}
        }}
        return result;
    }};
    const handlingSnapshot = vehicle => {{
        try {{
            const handling = vehicle.add(0x384).readPointer();
            return {{
                pointer:handling.toString(),
                engineAcceleration:f(handling.add(0x7C)),
                engineInertia:f(handling.add(0x80)),
                maxVelocity:f(handling.add(0x84)),
                velocityFrequency:f(vehicle.add(0x94)),
            }};
        }} catch(_) {{ return null; }}
    }};
    const transmissionSnapshot = vehicle => ({{
        currentGear:u8(vehicle.add(0x4B4)),
        gearChangeCount:f(vehicle.add(0x4B8)),
        inertiaValue1:f(vehicle.add(0x808)),
        inertiaValue2:f(vehicle.add(0x80C)),
        timerStep:f(timerStep),
    }});
    const matrixSnapshot = vehicle => {{
        try {{
            const q = vehicle.add(0x14).readPointer();
            return [vec(q), vec(q.add(0x10)), vec(q.add(0x20)), vec(q.add(0x30))];
        }} catch (_) {{
            return null;
        }}
    }};
    const physicalSnapshot = vehicle => ({{
        linearVelocity:vec(vehicle.add(0x44)),
        angularVelocity:vec(vehicle.add(0x50)),
        frictionMoveVelocity:vec(vehicle.add(0x5C)),
        frictionAngularVelocity:vec(vehicle.add(0x68)),
        force:vec(vehicle.add(0x74)),
        torque:vec(vehicle.add(0x80)),
        position:vec(vehicle.add(0x04)),
        collisionPosition:vec(vehicle.add(0xEC)),
        collisionImpactVelocity:vec(vehicle.add(0xE0)),
        damageImpulse:f(vehicle.add(0xD8)),
        collidedEntity:(()=>{{try{{return vehicle.add(0xDC).readPointer().toString()}}catch(_){{return null}}}})(),
        transmission:transmissionSnapshot(vehicle),
    }});
    const snapshotChanged = (before, after) => {{
        if (!before || !after) return false;
        const lv = delta(after.linearVelocity, before.linearVelocity) || [];
        const av = delta(after.angularVelocity, before.angularVelocity) || [];
        const fav = delta(after.frictionAngularVelocity, before.frictionAngularVelocity) || [];
        const fmv = delta(after.frictionMoveVelocity, before.frictionMoveVelocity) || [];
        return Math.sqrt(lv.reduce((s,v) => s + v*v, 0)) > 1e-7
            || Math.sqrt(av.reduce((s,v) => s + v*v, 0)) > 1e-7
            || Math.sqrt(fav.reduce((s,v) => s + v*v, 0)) > 1e-7
            || Math.sqrt(fmv.reduce((s,v) => s + v*v, 0)) > 1e-7
            || after.damageImpulse !== before.damageImpulse
            || after.collidedEntity !== before.collidedEntity;
    }};
    const expectedWheelEntry = [0x83,0xec,0x48,0xd9,0x05];
    for (let i=0; i<expectedWheelEntry.length; i++)
        if (processWheel.add(i).readU8() !== expectedWheelEntry[i])
            throw new Error('ProcessWheel signature mismatch at '+processWheel+'; refusing hardcoded hook');
    function flush() {{
        if (batch.length && captureActive) {{
            send({{type:'native_batch', label:OUTPUT_LABEL, records:batch}});
            batch=[];
        }}
        if (sourceTagBridgeEvents.length && captureActive) {{
            send({{type:'native_source_tag_bridge_batch', label:OUTPUT_LABEL, records:sourceTagBridgeEvents}});
            sourceTagBridgeEvents=[];
        }}
    }}
    if (INSTALL_SOURCE_TAG_ORDER_DIAGNOSTICS) {{
        try {{
            const multiplayer = Process.findModuleByName('multiplayer_sa_d.dll');
            const sourceTagBridge = multiplayer && multiplayer.findExportByName('SetNativeProcessWheelSourceTagBridge');
            if (!sourceTagBridge)
                throw new Error('SetNativeProcessWheelSourceTagBridge export not found');
            Interceptor.attach(sourceTagBridge, {{
                onEnter(args) {{
                    if (!captureActive) return;
                    try {{
                        this.sourceTagBridgeEvent = {{
                            source:'gta-native-source-tag-bridge',
                            label:OUTPUT_LABEL,
                            requestedSourceFrameTag:args[0].toInt32(),
                            requestedSourceTickMsTag:args[1].toInt32(),
                            gameFrame:(()=>{{try{{return gameFrameCounter.readU32()}}catch(_){{return null}}}})(),
                            gameTimeMs:(()=>{{try{{return gameTimeMs.readU32()}}catch(_){{return null}}}})(),
                            timerStep:f(timerStep),
                            processCalls,
                            processOrdinal:frame,
                        }};
                    }} catch (_) {{ this.sourceTagBridgeEvent = null; }}
                }},
                onLeave() {{
                    if (this.sourceTagBridgeEvent && captureActive)
                        sourceTagBridgeEvents.push(this.sourceTagBridgeEvent);
                }},
            }});
        }} catch (error) {{
            send({{type:'native_hook_error', message:'SetNativeProcessWheelSourceTagBridge: ' + String(error)}});
        }}
    }}
    try {{
        Interceptor.attach(processControl, {{
            onEnter() {{
                const vehicle = this.context.ecx;
                if (CAPTURE_FROM_FIRST_GAS && !captureActive) {{
                    try {{
                        const gas = f(vehicle.add(0x49C)) || 0;
                        const brake = f(vehicle.add(0x4A0)) || 0;
                        if (Math.abs(gas) <= 1e-6 && Math.abs(brake) <= 1e-6) return;
                        captureActive = true;
                        batch = preCaptureRecords.splice(0);
                    }} catch (_) {{ return; }}
                }}
                try {{
                    if (vehicle.add(0x22).readU16() === 411) {{
                        if (!oneTickInjected && ONE_TICK_CONFIG.nativeInternal && ONE_TICK_CONFIG.position) {{
                            const internal = ONE_TICK_CONFIG.nativeInternal;
                            const target = ONE_TICK_CONFIG.position;
                            const velocityTarget = ONE_TICK_CONFIG.velocity;
                            const angularTarget = ONE_TICK_CONFIG.angularVelocity;
                            const current = vec(vehicle.add(0x04));
                            const currentVelocity = vec(vehicle.add(0x44));
                            const currentAngular = vec(vehicle.add(0x50));
                            const distance = current && target
                                ? Math.sqrt((current[0] - target[0]) ** 2 + (current[1] - target[1]) ** 2 + (current[2] - target[2]) ** 2)
                                : Infinity;
                            const velocityDistance = currentVelocity && velocityTarget
                                ? Math.sqrt((currentVelocity[0] - velocityTarget[0]) ** 2 + (currentVelocity[1] - velocityTarget[1]) ** 2 + (currentVelocity[2] - velocityTarget[2]) ** 2)
                                : 0;
                            const angularDistance = currentAngular && angularTarget
                                ? Math.sqrt((currentAngular[0] - angularTarget[0]) ** 2 + (currentAngular[1] - angularTarget[1]) ** 2 + (currentAngular[2] - angularTarget[2]) ** 2)
                                : 0;
                            const requireStableTimerStep = internal.requireStableTimerStep === true;
                            const stableTimerStep = f(timerStep);
                            if (distance < 0.01 && velocityDistance < 0.02 && angularDistance < 0.02
                                && (!requireStableTimerStep
                                    || (stableTimerStep !== null
                                        && stableTimerStep >= 0.45
                                        && stableTimerStep <= 0.55))) {{
                                const writeArray = (offset, values) => {{
                                    if (!Array.isArray(values)) return;
                                    for (let i = 0; i < Math.min(4, values.length); i++)
                                        vehicle.add(offset + i * 4).writeFloat(Number(values[i]));
                                }};
                                const writeU32Array = (offset, values) => {{
                                    if (!Array.isArray(values)) return;
                                    for (let i = 0; i < Math.min(4, values.length); i++)
                                        vehicle.add(offset + i * 4).writeU32(Number(values[i]));
                                }};
                                const writeVector = (pointer, value) => {{
                                    if (!Array.isArray(value) || value.length < 3) return;
                                    pointer.writeFloat(Number(value[0]));
                                    pointer.add(4).writeFloat(Number(value[1]));
                                    pointer.add(8).writeFloat(Number(value[2]));
                                }};
                                try {{
                                    let compressionInput = internal.suspensionCompression;
                                    const compressionConvention = String(
                                        internal.suspensionCompressionInputConvention || 'raw'
                                    ).toLowerCase();
                                    if (Array.isArray(compressionInput)
                                        && compressionConvention.indexOf('normalized') >= 0) {{
                                        const springLength = Number(internal.suspensionSpringLength || 0.35);
                                        const lineLength = Number(internal.suspensionLineLength || 0.70);
                                        const wheelRadius = 1.0 - springLength / lineLength;
                                        compressionInput = compressionInput.map(value =>
                                            wheelRadius + (1.0 - wheelRadius) * Number(value));
                                    }}
                                    writeArray(0x7D4, compressionInput);
                                    writeArray(0x7E4, internal.suspensionCompressionPrevious);
                                    writeArray(0x7F4, internal.wheelCounts);
                                    writeU32Array(0x968, internal.wheelStates);
                                    if (Array.isArray(internal.wheelCollisionPoints))
                                        for (let i = 0; i < Math.min(4, internal.wheelCollisionPoints.length); i++)
                                            writeVector(vehicle.add(0x724 + i * 0x2C), internal.wheelCollisionPoints[i]);
                                    if (Array.isArray(internal.wheelCollisionNormals))
                                        for (let i = 0; i < Math.min(4, internal.wheelCollisionNormals.length); i++)
                                            writeVector(vehicle.add(0x724 + i * 0x2C + 0x10), internal.wheelCollisionNormals[i]);
                                    if (internal.rawSteerAngle !== undefined)
                                        vehicle.add(0x58C).writeFloat(Number(internal.rawSteerAngle));
                                    if (internal.steerAngle !== undefined)
                                        vehicle.add(0x494).writeFloat(Number(internal.steerAngle));
                                    if (internal.currentGear !== undefined)
                                        vehicle.add(0x4B4).writeU8(Number(internal.currentGear));
                                    if (internal.gearChangeCount !== undefined)
                                        vehicle.add(0x4B8).writeFloat(Number(internal.gearChangeCount));
                                    if (internal.inertiaValue1 !== undefined)
                                        vehicle.add(0x808).writeFloat(Number(internal.inertiaValue1));
                                    if (internal.inertiaValue2 !== undefined)
                                        vehicle.add(0x80C).writeFloat(Number(internal.inertiaValue2));
                                    if (internal.vehicleColProcessed === false)
                                        vehicle.add(0x42B).writeU8(vehicle.add(0x42B).readU8() & 0xFE);
                                    else if (internal.vehicleColProcessed === true)
                                        vehicle.add(0x42B).writeU8(vehicle.add(0x42B).readU8() | 0x01);
                                    if (internal.staticAlreadySkidding !== undefined)
                                        staticAlreadySkidding.writeU8(Number(internal.staticAlreadySkidding));
                                    oneTickInjected = true;
                                }} catch (_) {{}}
                            }}
                        }}
                        frame++; processCalls++;
                        const key = vehicle.toString();
                        const sourceTagEntry = readNativeSourceTag();
                        controlStates.set(key, {{
                            gameFrame:(()=>{{try{{return gameFrameCounter.readU32()}}catch(_){{return null}}}})(),
                            gameTimeMs:(()=>{{try{{return gameTimeMs.readU32()}}catch(_){{return null}}}})(),
                            sourceFrameTagEntry:sourceTagEntry.frame,
                            sourceTickMsTagEntry:sourceTagEntry.tick,
                            timerOldStep:f(timerOldStep),
                            timerStepNonClipped:f(timerStepNonClipped),
                            timerStep:f(timerStep),
                            currentGear:u8(vehicle.add(0x4B4)),
                            gearChangeCount:f(vehicle.add(0x4B8)),
                            inertiaValue1:f(vehicle.add(0x808)),
                            inertiaValue2:f(vehicle.add(0x80C)),
                            rawSteerAngle:f(vehicle.add(0x58C)),
                            steerAngle:f(vehicle.add(0x494)),
                            position:vec(vehicle.add(0x04)),
                            linearVelocity:vec(vehicle.add(0x44)),
                            angularVelocity:vec(vehicle.add(0x50)),
                            frictionMoveVelocity:vec(vehicle.add(0x5C)),
                            frictionAngularVelocity:vec(vehicle.add(0x68)),
                            force:vec(vehicle.add(0x74)),
                            torque:vec(vehicle.add(0x80)),
                            vtable:(()=>{{try{{return vehicle.readPointer().toString()}}catch(_){{return null}}}})(),
                            vtableCollisionCheck:(()=>{{try{{return vehicle.readPointer().add(0x5C).readPointer().toString()}}catch(_){{return null}}}})(),
                            vehicleFlagsByte3:u8(vehicle.add(0x42B)),
                            wheelStateMemory:u32Array4(vehicle.add(0x968)),
                            audioChangingGear:((u8(vehicle.add(0x42B)) || 0) & 0x20) !== 0,
                            handling:handlingSnapshot(vehicle),
                            transmission:transmissionSnapshot(vehicle),
                            collisionProcess:pendingCollisions.get(key) || null,
                            entityCollisionProcess:null,
                            gasPedalBefore:f(vehicle.add(0x49C)),
                            brakePedalBefore:f(vehicle.add(0x4A0)),
                            suspensionAtProcessControlEntry:INSTALL_COLLISION_DIAGNOSTICS ? suspensionSnapshot(vehicle) : null,
                            matrix:SUSPENSION_STAGE_ONLY ? matrixSnapshot(vehicle) : null,
                            suspensionProcess:null,
                            suspensionForceEvents:[],
                            frictionProcess:null,
                            frictionForceEvents:[],
                            applyForces:[],
                            applyTurnForces:[],
                            collisionAlternates:[],
                            processCollisionBoundaries:[],
                            activeRows:[],
                            transmissionCalls:[],
                            vehicle:vehicle,
                        }});
                        pendingCollisions.delete(key);
                        activeControlKey = key;
                        this.nativeControlKey = key;
                        this.nativeControlVehicle = vehicle;
                    }}
                }} catch(_) {{}}
            }},
            onLeave() {{
                const key = this.nativeControlKey;
                if (!key) return;
                try {{
                    const control = controlStates.get(key);
                    if (!control) return;
                    const exit = physicalSnapshot(this.nativeControlVehicle || this.context.ecx);
                    if (SUSPENSION_STAGE_ONLY)
                        exit.matrix = matrixSnapshot(this.nativeControlVehicle || this.context.ecx);
                    const sourceTagExit = readNativeSourceTag();
                    control.sourceFrameTagExit = sourceTagExit.frame;
                    control.sourceTickMsTagExit = sourceTagExit.tick;
                    control.controlExit = exit;
                    for (const record of control.activeRows || []) record.controlExit = exit;
                    if (SUSPENSION_STAGE_ONLY && captureActive) {{
                        const stageVehicle = this.nativeControlVehicle || this.context.ecx;
                        batch.push({{
                            source:'gta-native-process-stage', label:OUTPUT_LABEL,
                            processOrdinal:frame,
                            sourceFrameTagEntry:control.sourceFrameTagEntry,
                            sourceTickMsTagEntry:control.sourceTickMsTagEntry,
                            sourceFrameTagExit:control.sourceFrameTagExit,
                            sourceTickMsTagExit:control.sourceTickMsTagExit,
                            gameFrame:control.gameFrame, gameTimeMs:control.gameTimeMs,
                            vehicle:key,
                            timerOldStep:control.timerOldStep,
                            timerStepNonClipped:control.timerStepNonClipped,
                            timerStep:control.timerStep,
                            controlEntry:{{
                                position:control.position,
                                linearVelocity:control.linearVelocity,
                                angularVelocity:control.angularVelocity,
                                frictionMoveVelocity:control.frictionMoveVelocity,
                                frictionAngularVelocity:control.frictionAngularVelocity,
                                force:control.force,
                                torque:control.torque,
                                rawSteerAngle:control.rawSteerAngle,
                                steerAngle:control.steerAngle,
                                gasPedalBefore:control.gasPedalBefore,
                                brakePedalBefore:control.brakePedalBefore,
                                gasPedalAfter:f(stageVehicle.add(0x49C)),
                                brakePedalAfter:f(stageVehicle.add(0x4A0)),
                                suspensionAtProcessControlEntry:control.suspensionAtProcessControlEntry,
                                matrix:control.matrix,
                                transmission:control.transmission,
                                transmissionCalls:control.transmissionCalls,
                            }},
                            controlExit:exit,
                            entityCollisionProcess:control.entityCollisionProcess,
                            collisionCheck:control.collisionCheck,
                            processCollisionBoundaries:control.processCollisionBoundaries,
                            suspensionProcess:control.suspensionProcess,
                            applyForces:STAGE_FORCE_DIAGNOSTICS ? control.applyForces : null,
                            applyTurnForces:STAGE_FORCE_DIAGNOSTICS ? control.applyTurnForces : null,
                        }});
                        if (batch.length >= 4) flush();
                    }}
                }} catch(_) {{}}
                if (activeControlKey === key) activeControlKey = null;
            }},
        }});
        if (INSTALL_TRANSMISSION_DIAGNOSTICS) {{
        Interceptor.attach(calculateDriveAcceleration, {{
            onEnter() {{
                const key = activeControlKey;
                const control = key ? controlStates.get(key) : null;
                const vehicle = control && control.vehicle;
                if (!control || !vehicle) return;
                try {{
                    this.transmissionControl = control;
                    this.transmissionVehicle = vehicle;
                    this.transmissionBefore = {{
                        gameFrame:gameFrameCounter.readU32(),
                        gameTimeMs:gameTimeMs.readU32(),
                        sourceTag:readNativeSourceTag(),
                        timerStep:f(timerStep),
                        gasPedal:f(vehicle.add(0x49C)),
                        velocity:vec(vehicle.add(0x44)),
                        currentGear:u8(vehicle.add(0x4B4)),
                        gearChangeCount:f(vehicle.add(0x4B8)),
                        inertiaValue1:f(vehicle.add(0x808)),
                        inertiaValue2:f(vehicle.add(0x80C)),
                    }};
                }} catch(_) {{
                    this.transmissionControl = null;
                }}
            }},
            onLeave(returnValue) {{
                const control = this.transmissionControl;
                const vehicle = this.transmissionVehicle;
                const before = this.transmissionBefore;
                if (!control || !vehicle || !before) return;
                try {{
                    const tag = readNativeSourceTag();
                    control.transmissionCalls.push({{
                        gameFrame:before.gameFrame,
                        gameTimeMs:before.gameTimeMs,
                        sourceFrameTagEntry:before.sourceTag.frame,
                        sourceTickMsTagEntry:before.sourceTag.tick,
                        sourceFrameTagExit:tag.frame,
                        sourceTickMsTagExit:tag.tick,
                        timerStep:before.timerStep,
                        gasPedal:before.gasPedal,
                        velocityBefore:before.velocity,
                        currentGearBefore:before.currentGear,
                        gearChangeCountBefore:before.gearChangeCount,
                        inertiaValue1Before:before.inertiaValue1,
                        inertiaValue2Before:before.inertiaValue2,
                        returnValue:f(returnValue),
                        currentGearAfter:u8(vehicle.add(0x4B4)),
                        gearChangeCountAfter:f(vehicle.add(0x4B8)),
                        inertiaValue1After:f(vehicle.add(0x808)),
                        inertiaValue2After:f(vehicle.add(0x80C)),
                    }});
                }} catch(_) {{}}
            }},
        }});
        }}
        if (INSTALL_COLLISION_DIAGNOSTICS) {{
        Interceptor.attach(processEntityCollision, {{
            onEnter() {{
                if (CAPTURE_FROM_FIRST_GAS && !captureActive) return;
                const vehicle = this.context.ecx;
                try {{
                    if (vehicle.add(0x22).readU16() !== 411) return;
                    this.nativeEntityCollisionKey = vehicle.toString();
                    this.nativeEntityCollisionVehicle = vehicle;
                    this.nativeEntityCollisionBefore = suspensionSnapshot(vehicle);
                    this.nativeEntityCollisionEntity = null;
                    this.nativeEntityCollisionOutput = null;
                    try {{
                        this.nativeEntityCollisionEntity = this.context.esp.add(4).readPointer();
                        this.nativeEntityCollisionOutput = this.context.esp.add(8).readPointer();
                    }} catch (_) {{}}
                }} catch(_) {{}}
            }},
            onLeave(returnValue) {{
                if (!this.nativeEntityCollisionKey) return;
                try {{
                    const control = controlStates.get(this.nativeEntityCollisionKey);
                    if (control) control.entityCollisionProcess = {{
                        result:returnValue.toInt32(),
                        entity:this.nativeEntityCollisionEntity ? this.nativeEntityCollisionEntity.toString() : null,
                        before:this.nativeEntityCollisionBefore,
                        after:suspensionSnapshot(this.nativeEntityCollisionVehicle),
                        automobileCollisionPoints:SUSPENSION_STAGE_ONLY
                            ? null : colPointArray(automobileCollisionPoints, 12),
                        outputCollisionPoints:SUSPENSION_STAGE_ONLY
                            ? null : colPointArray(this.nativeEntityCollisionOutput, 32),
                    }};
                }} catch(_) {{}}
            }}
        }});
        Interceptor.attach(processSuspension, {{
            onEnter() {{
                if (CAPTURE_FROM_FIRST_GAS && !captureActive) return;
                const vehicle = this.context.ecx;
                try {{
                    if (vehicle.add(0x22).readU16() !== 411) return;
                    this.nativeSuspensionKey = vehicle.toString();
                    this.nativeSuspensionVehicle = vehicle;
                    this.nativeSuspensionBefore = suspensionSnapshot(vehicle);
                    this.nativeSuspensionPhysicalBefore = STAGE_FORCE_DIAGNOSTICS
                        ? physicalSnapshot(vehicle) : null;
                    this.nativeSuspensionCandidatesBefore = colPointArray(automobileCollisionPoints, 12);
                    activeSuspensionControlKey = this.nativeSuspensionKey;
                    const activeControl = controlStates.get(this.nativeSuspensionKey);
                    if (activeControl) activeControl.suspensionForceEvents = [];
                    const tag = readNativeSourceTag();
                    const inForceWindow = STAGE_FORCE_EVENTS
                        && Array.isArray(STAGE_FORCE_SOURCE_WINDOW)
                        && tag.frame !== null
                        && tag.frame >= STAGE_FORCE_SOURCE_WINDOW[0]
                        && tag.frame <= STAGE_FORCE_SOURCE_WINDOW[1];
                    activeSuspensionForceContext = inForceWindow
                        ? {{ key:this.nativeSuspensionKey,
                            sourceFrameTag:tag.frame,
                            sourceTickMsTag:tag.tick,
                            events:activeControl ? activeControl.suspensionForceEvents : [] }}
                        : null;
                }} catch(_) {{}}
            }},
            onLeave() {{
                if (!this.nativeSuspensionKey) return;
                try {{
                    const control = controlStates.get(this.nativeSuspensionKey);
                    if (control) control.suspensionProcess = {{
                        before:this.nativeSuspensionBefore,
                        after:suspensionSnapshot(this.nativeSuspensionVehicle),
                        automobileCollisionPointsBefore:this.nativeSuspensionCandidatesBefore,
                        automobileCollisionPointsAfter:colPointArray(automobileCollisionPoints, 12),
                        physicalBefore:this.nativeSuspensionPhysicalBefore,
                        physicalAfter:STAGE_FORCE_DIAGNOSTICS
                            ? physicalSnapshot(this.nativeSuspensionVehicle) : null,
                        forceEvents:(STAGE_FORCE_DIAGNOSTICS || STAGE_FORCE_EVENTS)
                            ? (control.suspensionForceEvents || []) : null,
                    }};
                }} catch(_) {{}}
                if (activeSuspensionForceContext
                    && activeSuspensionForceContext.key === this.nativeSuspensionKey)
                    activeSuspensionForceContext = null;
                if (activeSuspensionControlKey === this.nativeSuspensionKey)
                    activeSuspensionControlKey = null;
            }}
        }});
        if (STAGE_FORCE_EVENTS) {{
        Interceptor.attach(applyForce, {{
            onEnter() {{
                const context = activeSuspensionForceContext;
                if (!context) return;
                const vehicle = this.context.ecx;
                if (context.key !== vehicle.toString()) return;
                try {{
                    this.nativeStageForceEventContext = context;
                    this.nativeStageForceEventVehicle = vehicle;
                    const sp = this.context.esp;
                    this.nativeStageForceEventForce = [f(sp.add(4)), f(sp.add(8)), f(sp.add(12))];
                    this.nativeStageForceEventPoint = [f(sp.add(16)), f(sp.add(20)), f(sp.add(24))];
                    this.nativeStageForceEventBeforeLinear = vec(vehicle.add(0x44));
                    this.nativeStageForceEventBeforeAngular = vec(vehicle.add(0x50));
                    this.nativeStageForceEventReturnAddress = this.returnAddress.toString();
                }} catch (_) {{
                    this.nativeStageForceEventContext = null;
                }}
            }},
            onLeave() {{
                const context = this.nativeStageForceEventContext;
                if (!context) return;
                try {{
                    const afterLinear = vec(this.nativeStageForceEventVehicle.add(0x44));
                    const afterAngular = vec(this.nativeStageForceEventVehicle.add(0x50));
                    context.events.push({{
                        source:'gta-native-processsuspension-ApplyForce',
                        sourceFrameTag:context.sourceFrameTag,
                        sourceTickMsTag:context.sourceTickMsTag,
                        force:this.nativeStageForceEventForce,
                        point:this.nativeStageForceEventPoint,
                        linearVelocityBefore:this.nativeStageForceEventBeforeLinear,
                        linearVelocityAfter:afterLinear,
                        angularVelocityBefore:this.nativeStageForceEventBeforeAngular,
                        angularVelocityAfter:afterAngular,
                        linearVelocityDelta:delta(afterLinear, this.nativeStageForceEventBeforeLinear),
                        angularVelocityDelta:delta(afterAngular, this.nativeStageForceEventBeforeAngular),
                        returnAddress:this.nativeStageForceEventReturnAddress,
                    }});
                }} catch (_) {{}}
                this.nativeStageForceEventContext = null;
            }},
        }});
        }}
        if (!SUSPENSION_STAGE_ONLY) {{
        Interceptor.attach(processFriction, {{
            onEnter() {{
                const vehicle = this.context.ecx;
                try {{
                    if (vehicle.add(0x22).readU16() !== 411) return;
                    this.nativeFrictionKey = vehicle.toString();
                    this.nativeFrictionVehicle = vehicle;
                    this.nativeFrictionBefore = physicalSnapshot(vehicle);
                }} catch(_) {{}}
            }},
            onLeave() {{
                if (!this.nativeFrictionKey) return;
                try {{
                    const control = controlStates.get(this.nativeFrictionKey);
                    if (control) control.frictionProcess = {{
                        before:this.nativeFrictionBefore,
                        after:physicalSnapshot(this.nativeFrictionVehicle),
                    }};
                }} catch(_) {{}}
            }}
        }});
        Interceptor.attach(applyFrictionForce, {{
            onEnter() {{
                const vehicle = this.context.ecx;
                try {{
                    if (vehicle.add(0x22).readU16() !== 411) return;
                    this.nativeFrictionForceKey = vehicle.toString();
                    this.nativeFrictionForceVehicle = vehicle;
                    this.nativeFrictionForceBefore = physicalSnapshot(vehicle);
                    this.nativeFrictionForce = [
                        f(this.context.esp.add(4)),
                        f(this.context.esp.add(8)),
                        f(this.context.esp.add(12)),
                    ];
                    this.nativeFrictionPoint = [
                        f(this.context.esp.add(16)),
                        f(this.context.esp.add(20)),
                        f(this.context.esp.add(24)),
                    ];
                }} catch(_) {{}}
            }},
            onLeave() {{
                if (!this.nativeFrictionForceKey) return;
                try {{
                    const control = controlStates.get(this.nativeFrictionForceKey);
                    if (control) control.frictionForceEvents.push({{
                        force:this.nativeFrictionForce,
                        point:this.nativeFrictionPoint,
                        before:this.nativeFrictionForceBefore,
                        after:physicalSnapshot(this.nativeFrictionForceVehicle),
                    }});
                }} catch(_) {{}}
            }}
        }});
        Interceptor.attach(processCollision, {{
            onEnter() {{
                const vehicle = this.context.ecx;
                try {{
                    if (vehicle.add(0x22).readU16() !== 411) return;
                    this.nativeCollisionKey = vehicle.toString();
                    this.nativeCollisionVehicle = vehicle;
                    this.nativeCollisionBefore = physicalSnapshot(vehicle);
                    this.nativeCollisionSuspensionBefore = suspensionSnapshot(vehicle);
                }} catch(_) {{}}
            }},
            onLeave() {{
                if (!this.nativeCollisionKey) return;
                try {{
                    const after = physicalSnapshot(this.nativeCollisionVehicle);
                    const suspensionAfter = suspensionSnapshot(this.nativeCollisionVehicle);
                    const suspensionChanged = JSON.stringify(this.nativeCollisionSuspensionBefore)
                        !== JSON.stringify(suspensionAfter);
                    if (snapshotChanged(this.nativeCollisionBefore, after) || suspensionChanged)
                        pendingCollisions.set(this.nativeCollisionKey, {{
                            before:this.nativeCollisionBefore,
                            after:after,
                            suspensionBefore:this.nativeCollisionSuspensionBefore,
                            suspensionAfter:suspensionAfter,
                            suspensionChanged:suspensionChanged,
                        }});
                }} catch(_) {{}}
            }}
        }});
        Interceptor.attach(applyForce, {{
            onEnter() {{
                const vehicle = this.context.ecx;
                try {{
                    if (vehicle.add(0x22).readU16() !== 411) return;
                    this.nativeForceKey = vehicle.toString();
                    this.nativeForceVehicle = vehicle;
                    this.nativeForceBefore = physicalSnapshot(vehicle);
                    const sp = this.context.esp;
                    this.nativeForceVector = [f(sp.add(4)), f(sp.add(8)), f(sp.add(12))];
                    this.nativeForcePoint = [f(sp.add(16)), f(sp.add(20)), f(sp.add(24))];
                    this.nativeForceDuringSuspension = STAGE_FORCE_DIAGNOSTICS
                        && activeSuspensionControlKey === this.nativeForceKey;
                    this.nativeForceReturnAddress = this.returnAddress.toString();
                }} catch(_) {{}}
            }},
            onLeave() {{
                if (!this.nativeForceKey) return;
                try {{
                    const control = controlStates.get(this.nativeForceKey);
                    const after = physicalSnapshot(this.nativeForceVehicle);
                    if (control && snapshotChanged(this.nativeForceBefore, after)) {{
                        const event = {{
                            force:this.nativeForceVector,
                            point:this.nativeForcePoint,
                            before:this.nativeForceBefore,
                            after:after,
                            returnAddress:this.nativeForceReturnAddress,
                        }};
                        control.applyForces.push(event);
                        if (this.nativeForceDuringSuspension)
                            control.suspensionForceEvents.push(event);
                    }}
                }} catch(_) {{}}
            }}
        }});
        Interceptor.attach(applyTurnForce, {{
            onEnter() {{
                const vehicle = this.context.ecx;
                try {{
                    if (vehicle.add(0x22).readU16() !== 411) return;
                    this.nativeTurnForceKey = vehicle.toString();
                    this.nativeTurnForceVehicle = vehicle;
                    this.nativeTurnForceBefore = physicalSnapshot(vehicle);
                    this.nativeTurnForceVector = [f(this.context.esp.add(4)), f(this.context.esp.add(8)), f(this.context.esp.add(12))];
                    this.nativeTurnForcePoint = [f(this.context.esp.add(16)), f(this.context.esp.add(20)), f(this.context.esp.add(24))];
                    this.nativeTurnForceReturnAddress = this.returnAddress.toString();
                }} catch(_) {{}}
            }},
            onLeave() {{
                if (!this.nativeTurnForceKey) return;
                try {{
                    const control = controlStates.get(this.nativeTurnForceKey);
                    const after = physicalSnapshot(this.nativeTurnForceVehicle);
                    if (control && snapshotChanged(this.nativeTurnForceBefore, after))
                        control.applyTurnForces.push({{
                            force:this.nativeTurnForceVector,
                            point:this.nativeTurnForcePoint,
                            returnAddress:this.nativeTurnForceReturnAddress,
                            before:this.nativeTurnForceBefore,
                            after:after,
                        }});
                }} catch(_) {{}}
            }}
        }});
        Interceptor.attach(applyCollisionAlt, {{
            onEnter() {{
                const vehicle = this.context.ecx;
                try {{
                    if (vehicle.add(0x22).readU16() !== 411) return;
                    const sp = this.context.esp;
                    this.nativeCollisionAltKey = vehicle.toString();
                    this.nativeCollisionAltPoint = sp.add(8).readPointer();
                    this.nativeCollisionAltMove = sp.add(16).readPointer();
                    this.nativeCollisionAltTurn = sp.add(20).readPointer();
                    this.nativeCollisionAltDamage = sp.add(12).readPointer();
                    this.nativeCollisionAltBefore = physicalSnapshot(vehicle);
                    this.nativeCollisionAltReturnAddress = this.returnAddress.toString();
                }} catch(_) {{}}
            }},
            onLeave(returnValue) {{
                if (!this.nativeCollisionAltKey) return;
                try {{
                    const control = controlStates.get(this.nativeCollisionAltKey);
                    if (!control) return;
                    const cp = this.nativeCollisionAltPoint;
                    control.collisionAlternates.push({{
                        returnAddress:this.nativeCollisionAltReturnAddress,
                        result:returnValue.toInt32(),
                        point:vec(cp),
                        normal:vec(cp.add(16)),
                        surfaceA:u8(cp.add(32)),
                        pieceA:u8(cp.add(33)),
                        surfaceB:u8(cp.add(35)),
                        pieceB:u8(cp.add(36)),
                        depth:f(cp.add(40)),
                        damageBefore:f(this.nativeCollisionAltDamage),
                        moveBefore:vec(this.nativeCollisionAltMove),
                        turnBefore:vec(this.nativeCollisionAltTurn),
                        damageAfter:f(this.nativeCollisionAltDamage),
                        moveAfter:vec(this.nativeCollisionAltMove),
                        turnAfter:vec(this.nativeCollisionAltTurn),
                    }});
                }} catch(_) {{}}
            }}
        }});
        Interceptor.attach(checkCollision, {{
            onEnter() {{
                const vehicle = this.context.ecx;
                try {{
                    if (vehicle.add(0x22).readU16() !== 411) return;
                    this.nativeCollisionKey = vehicle.toString();
                    this.nativeCollisionVehicle = vehicle;
                    this.nativeCollisionBefore = physicalSnapshot(vehicle);
                }} catch(_) {{}}
            }},
            onLeave(returnValue) {{
                if (!this.nativeCollisionKey) return;
                try {{
                    const control = controlStates.get(this.nativeCollisionKey);
                    if (control) control.collisionCheckInner = {{
                        before:this.nativeCollisionBefore,
                        after:physicalSnapshot(this.nativeCollisionVehicle),
                        result:returnValue.toInt32(),
                    }};
                }} catch(_) {{}}
            }}
        }});
        Interceptor.attach(processControlCollisionCheck, {{
            onEnter() {{
                const vehicle = this.context.ecx;
                try {{
                    if (vehicle.add(0x22).readU16() !== 411) return;
                    this.nativeCollisionKey = vehicle.toString();
                    this.nativeCollisionVehicle = vehicle;
                    this.nativeCollisionBefore = physicalSnapshot(vehicle);
                    this.nativeCollisionApplySpeed = this.context.esp.add(4).readU8();
                }} catch(_) {{}}
            }},
            onLeave() {{
                if (!this.nativeCollisionKey) return;
                const control = controlStates.get(this.nativeCollisionKey);
                if (!control) return;
                try {{
                    const vehicle = this.nativeCollisionVehicle;
                    const after = physicalSnapshot(vehicle);
                    control.collisionCheck = {{
                        applySpeed:this.nativeCollisionApplySpeed,
                        before:this.nativeCollisionBefore,
                        after:after,
                    }};
                }} catch(_) {{}}
            }}
        }});
        }}
        }}
        // Narrow source-window-only ProcessSuspension boundary. This avoids
        // the full collision-diagnostics hook set while exposing the private
        // compression/contact state immediately around the wheel stack.
        if (Array.isArray(PROCESSSUSPENSION_SOURCE_WINDOW) && !INSTALL_COLLISION_DIAGNOSTICS) {{
        Interceptor.attach(processSuspension, {{
            onEnter() {{
                const sourceTag = readNativeSourceTag();
                if (sourceTag.frame === null
                    || sourceTag.frame < PROCESSSUSPENSION_SOURCE_WINDOW[0]
                    || sourceTag.frame > PROCESSSUSPENSION_SOURCE_WINDOW[1]) return;
                if (CAPTURE_FROM_FIRST_GAS && !captureActive) return;
                const vehicle = this.context.ecx;
                try {{
                    if (vehicle.add(0x22).readU16() !== 411) return;
                    this.nativeNarrowSuspensionKey = vehicle.toString();
                    this.nativeNarrowSuspensionVehicle = vehicle;
                    this.nativeNarrowSuspensionBefore = suspensionSnapshot(vehicle);
                    this.nativeNarrowSuspensionTagEntry = sourceTag.frame;
                    this.nativeNarrowSuspensionTickEntry = sourceTag.tick;
                }} catch (_) {{}}
            }},
            onLeave() {{
                const key = this.nativeNarrowSuspensionKey;
                if (!key) return;
                try {{
                    const tag = readNativeSourceTag();
                    const boundary = {{
                        sourceFrameTagEntry:this.nativeNarrowSuspensionTagEntry,
                        sourceTickMsTagEntry:this.nativeNarrowSuspensionTickEntry,
                        sourceFrameTagExit:tag.frame,
                        sourceTickMsTagExit:tag.tick,
                        before:this.nativeNarrowSuspensionBefore,
                        after:suspensionSnapshot(this.nativeNarrowSuspensionVehicle),
                    }};
                    if (captureActive) {{
                        batch.push({{
                            source:'gta-native-process-suspension-boundary', label:OUTPUT_LABEL,
                            processOrdinal:frame,
                            sourceFrameTagEntry:boundary.sourceFrameTagEntry,
                            sourceTickMsTagEntry:boundary.sourceTickMsTagEntry,
                            sourceFrameTagExit:boundary.sourceFrameTagExit,
                            sourceTickMsTagExit:boundary.sourceTickMsTagExit,
                            gameFrame:gameFrameCounter.readU32(),
                            gameTimeMs:gameTimeMs.readU32(),
                            vehicle:key,
                            timerStep:f(timerStep),
                            processSuspension:boundary,
                        }});
                        if (batch.length >= 4) flush();
                    }}
                }} catch (_) {{}}
                this.nativeNarrowSuspensionKey = null;
            }}
        }});
        }}
        // Reduced stage mode keeps only this narrow read-only boundary probe
        // in addition to ProcessEntityCollision/ProcessSuspension.  It shows
        // whether GTA advances the incoming motion before the wheel stack.
        if (SUSPENSION_STAGE_ONLY) {{
        Interceptor.attach(processControlCollisionCheck, {{
            onEnter() {{
                const vehicle = this.context.ecx;
                try {{
                    if (vehicle.add(0x22).readU16() !== 411) return;
                    this.nativeStageCollisionKey = vehicle.toString();
                    this.nativeStageCollisionVehicle = vehicle;
                    this.nativeStageCollisionBefore = physicalSnapshot(vehicle);
                    this.nativeStageCollisionApplySpeed = this.context.esp.add(4).readU8();
                }} catch (_) {{}}
            }},
            onLeave(returnValue) {{
                const key = this.nativeStageCollisionKey;
                if (!key) return;
                try {{
                    const control = controlStates.get(key);
                    if (control) control.collisionCheck = {{
                        applySpeed:this.nativeStageCollisionApplySpeed,
                        before:this.nativeStageCollisionBefore,
                        after:physicalSnapshot(this.nativeStageCollisionVehicle),
                        result:returnValue.toInt32(),
                    }};
                }} catch (_) {{}}
                this.nativeStageCollisionKey = null;
            }}
        }});
        }}
        // ProcessCollision is the narrow post-ProcessControl boundary where
        // GTA applies the accumulated move/turn speed before collision tests.
        // The reduced stage route observes it without installing force or
        // ProcessWheel hooks, so reference-frame integration can be separated
        // from the ProcessControl exit state.
        if (SUSPENSION_STAGE_ONLY || Array.isArray(PROCESSCOLLISION_SOURCE_WINDOW)) {{
        Interceptor.attach(processCollision, {{
            onEnter() {{
                const sourceTag = readNativeSourceTag();
                if (Array.isArray(PROCESSCOLLISION_SOURCE_WINDOW)
                    && (sourceTag.frame === null
                        || sourceTag.frame < PROCESSCOLLISION_SOURCE_WINDOW[0]
                        || sourceTag.frame > PROCESSCOLLISION_SOURCE_WINDOW[1])) return;
                if (CAPTURE_FROM_FIRST_GAS && !captureActive) return;
                const vehicle = this.context.ecx;
                try {{
                    if (vehicle.add(0x22).readU16() !== 411) return;
                    this.nativeStageProcessCollisionKey = vehicle.toString();
                    this.nativeStageProcessCollisionVehicle = vehicle;
                    this.nativeStageProcessCollisionBefore = physicalSnapshot(vehicle);
                    this.nativeStageProcessCollisionBefore.matrix = matrixSnapshot(vehicle);
                    const tag = sourceTag;
                    this.nativeStageProcessCollisionTagEntry = tag.frame;
                    this.nativeStageProcessCollisionTickEntry = tag.tick;
                }} catch (_) {{}}
            }},
            onLeave() {{
                const key = this.nativeStageProcessCollisionKey;
                if (!key) return;
                try {{
                    const control = controlStates.get(key);
                    if (control) {{
                        const after = physicalSnapshot(this.nativeStageProcessCollisionVehicle);
                        after.matrix = matrixSnapshot(this.nativeStageProcessCollisionVehicle);
                        const tag = readNativeSourceTag();
                        const boundary = {{
                            sourceFrameTagEntry:this.nativeStageProcessCollisionTagEntry,
                            sourceTickMsTagEntry:this.nativeStageProcessCollisionTickEntry,
                            sourceFrameTagExit:tag.frame,
                            sourceTickMsTagExit:tag.tick,
                            before:this.nativeStageProcessCollisionBefore,
                            after:after,
                        }};
                        control.processCollisionBoundaries.push(boundary);
                        // ProcessCollision runs after ProcessControl has
                        // already emitted its stage row. Publish a separate
                        // boundary record rather than pretending it is part
                        // of the earlier ProcessControl exit.
                        if (captureActive) {{
                            batch.push({{
                                source:'gta-native-process-collision-boundary', label:OUTPUT_LABEL,
                                processOrdinal:frame,
                                sourceFrameTagEntry:boundary.sourceFrameTagEntry,
                                sourceTickMsTagEntry:boundary.sourceTickMsTagEntry,
                                sourceFrameTagExit:boundary.sourceFrameTagExit,
                                sourceTickMsTagExit:boundary.sourceTickMsTagExit,
                                gameFrame:gameFrameCounter.readU32(),
                                gameTimeMs:gameTimeMs.readU32(),
                                vehicle:key,
                                timerStep:f(timerStep),
                                processCollision:boundary,
                            }});
                            if (batch.length >= 4) flush();
                        }}
                    }}
                }} catch (_) {{}}
                this.nativeStageProcessCollisionKey = null;
            }}
        }});
        }}
        // Lightweight paired ProcessSuspension boundary.  Unlike
        // INSTALL_COLLISION_DIAGNOSTICS this does not install the broad
        // collision/force observer set; it is intended to answer the
        // startup ProcessSuspension-versus-ProcessWheel question without
        // destroying the native timer cadence.
        if (INSTALL_PAIRED_SUSPENSION && !INSTALL_COLLISION_DIAGNOSTICS) {{
        Interceptor.attach(processSuspension, {{
            onEnter() {{
                const tag = readNativeSourceTag();
                if (!Array.isArray(PROCESSWHEEL_SOURCE_WINDOW)
                    || tag.frame === null
                    || tag.frame < PROCESSWHEEL_SOURCE_WINDOW[0]
                    || tag.frame > PROCESSWHEEL_SOURCE_WINDOW[1]) return;
                const vehicle = this.context.ecx;
                try {{
                    if (vehicle.add(0x22).readU16() !== 411) return;
                    this.nativePairedSuspensionKey = vehicle.toString();
                    this.nativePairedSuspensionVehicle = vehicle;
                    this.nativePairedSuspensionBefore = suspensionSnapshot(vehicle);
                    this.nativePairedSuspensionPhysicalBefore = physicalSnapshot(vehicle);
                    this.nativePairedSuspensionTag = tag;
                    this.nativePairedSuspensionTimerStep = f(timerStep);
                }} catch (_) {{}}
            }},
            onLeave() {{
                const key = this.nativePairedSuspensionKey;
                if (!key) return;
                try {{
                    const control = controlStates.get(key);
                    if (control) control.suspensionProcess = {{
                        source:'gta-native-paired-process-suspension',
                        sourceFrameTagEntry:this.nativePairedSuspensionTag.frame,
                        sourceTickMsTagEntry:this.nativePairedSuspensionTag.tick,
                        timerStep:this.nativePairedSuspensionTimerStep,
                        before:this.nativePairedSuspensionBefore,
                        after:suspensionSnapshot(this.nativePairedSuspensionVehicle),
                        physicalBefore:this.nativePairedSuspensionPhysicalBefore,
                        physicalAfter:physicalSnapshot(this.nativePairedSuspensionVehicle),
                    }};
                }} catch (_) {{}}
                this.nativePairedSuspensionKey = null;
            }}
        }});
        }}
        if (INSTALL_NATIVE_WHEEL_HOOK) {{
        Interceptor.attach(processWheel, {{
            onEnter() {{
                const vehicle = this.context.ecx;
                try {{ if (vehicle.add(0x22).readU16() !== 411) return; }} catch(_) {{ return; }}
                const sourceTag = readNativeSourceTag();
                if (Array.isArray(PROCESSWHEEL_SOURCE_WINDOW)) {{
                    if (sourceTag.frame === null
                        || sourceTag.frame < PROCESSWHEEL_SOURCE_WINDOW[0]
                        || sourceTag.frame > PROCESSWHEEL_SOURCE_WINDOW[1]) return;
                }}
                const sp = this.context.esp;
                const fwdPtr=sp.add(4).readPointer(), rightPtr=sp.add(8).readPointer();
                const speedPtr=sp.add(12).readPointer(), pointPtr=sp.add(16).readPointer();
                const wheelSpeedPtr=sp.add(40).readPointer(), wheelStatePtr=sp.add(44).readPointer();
                const fwd=vec(fwdPtr), right=vec(rightPtr), speed=vec(speedPtr);
                const beforeLinear=vec(vehicle.add(0x44)), beforeAngular=vec(vehicle.add(0x50));
                this.nativeVehicle=vehicle; this.nativeState=wheelStatePtr;
                this.nativeRecord={{
                    source:'gta-native-pre-ProcessWheel', label:OUTPUT_LABEL, frame,
                    sourceFrameTag:sourceTag.frame, sourceTickMsTag:sourceTag.tick,
                    gameFrame:(()=>{{try{{return gameFrameCounter.readU32()}}catch(_){{return null}}}})(),
                    gameTimeMs:(()=>{{try{{return gameTimeMs.readU32()}}catch(_){{return null}}}})(),
                    timerStep:f(timerStep),
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
                    currentGear:u8(vehicle.add(0x4B4)), gearChangeCount:f(vehicle.add(0x4B8)),
                    inertiaValue1:f(vehicle.add(0x808)), inertiaValue2:f(vehicle.add(0x80C)),
                    gasPedal:f(vehicle.add(0x49C)), brakePedal:f(vehicle.add(0x4A0)),
                    contactWheels:u8(vehicle.add(0x960)), driveWheels:u8(vehicle.add(0x961)),
                    mass:f(vehicle.add(0x8C)), turnMass:f(vehicle.add(0x90)), centerOfMass:vec(vehicle.add(0xA4)),
                    handling:(()=>{{const c=controlStates.get(vehicle.toString());return c ? c.handling : handlingSnapshot(vehicle);}})(),
                    controlEntry:(()=>{{const c=controlStates.get(vehicle.toString());return c ? {{gameFrame:c.gameFrame,gameTimeMs:c.gameTimeMs,timerOldStep:c.timerOldStep,timerStepNonClipped:c.timerStepNonClipped,timerStep:c.timerStep,currentGear:c.currentGear,gearChangeCount:c.gearChangeCount,inertiaValue1:c.inertiaValue1,inertiaValue2:c.inertiaValue2,rawSteerAngle:c.rawSteerAngle,steerAngle:c.steerAngle,linearVelocity:c.linearVelocity,angularVelocity:c.angularVelocity,frictionMoveVelocity:c.frictionMoveVelocity,frictionAngularVelocity:c.frictionAngularVelocity,vtable:c.vtable,vtableCollisionCheck:c.vtableCollisionCheck,vehicleFlagsByte3:c.vehicleFlagsByte3,wheelStateMemory:c.wheelStateMemory,audioChangingGear:c.audioChangingGear,handling:c.handling,collisionProcess:c.collisionProcess,entityCollisionProcess:c.entityCollisionProcess,suspensionAtProcessControlEntry:c.suspensionAtProcessControlEntry,transmissionCalls:c.transmissionCalls,suspensionProcess:c.suspensionProcess,frictionProcess:c.frictionProcess,frictionForceEvents:c.frictionForceEvents,collisionCheck:c.collisionCheck,collisionCheckInner:c.collisionCheckInner,applyForces:c.applyForces,applyTurnForces:c.applyTurnForces,collisionAlternates:c.collisionAlternates}} : null;}})(),
                    controlExit:null,
                    linearVelocityBefore:beforeLinear, angularVelocityBefore:beforeAngular,
                    staticAlreadySkiddingBefore:INSTALL_STATIC_SKID_DIAGNOSTICS ? u8(staticAlreadySkidding) : null
                }};
                const control = controlStates.get(vehicle.toString());
                if (control) control.activeRows.push(this.nativeRecord);
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
                if (INSTALL_STATIC_SKID_DIAGNOSTICS)
                    record.staticAlreadySkiddingAfter = u8(staticAlreadySkidding);
                if (CAPTURE_FROM_FIRST_GAS && !captureActive) {{
                    preCaptureRecords.push(record);
                    if (preCaptureRecords.length > maxPreCaptureRecords)
                        preCaptureRecords.shift();
                    if ((record.gasPedal || 0) > 0.5 || (record.brakePedal || 0) < -0.5) {{
                        captureActive = true;
                        batch = preCaptureRecords.splice(0);
                    }} else {{
                        return;
                    }}
                }} else {{
                    batch.push(record);
                }}
                if (batch.length >= 32) flush();
            }}
        }});
        }}
        if (INSTALL_STATE_WRITER_DIAGNOSTICS && Array.isArray(PROCESSWHEEL_SOURCE_WINDOW)) {{
            const gameSa = Process.findModuleByName('game_sa_d.dll');
            if (gameSa) {{
                const setMoveSpeedTargets = [
                    ['CPhysicalSA::SetMoveSpeed', gameSa.base.add(setMoveSpeedRva)],
                    ['CVehicleSA::SetMoveSpeed', gameSa.base.add(vehicleSetMoveSpeedRva)],
                ];
                for (const target of setMoveSpeedTargets) {{
                    try {{
                        Interceptor.attach(target[1], {{
                            onEnter() {{
                                try {{
                                    const sourceTag = readNativeSourceTag();
                                    if (sourceTag.frame === null
                                        || sourceTag.frame < PROCESSWHEEL_SOURCE_WINDOW[0]
                                        || sourceTag.frame > PROCESSWHEEL_SOURCE_WINDOW[1]) return;
                                    const speedPtr = this.context.esp.add(4).readPointer();
                                    this.nativeSetMoveSpeedRecord = {{
                                        target:target[0],
                                        sourceFrameTag:sourceTag.frame,
                                        sourceTickMsTag:sourceTag.tick,
                                        gameFrame:(()=>{{try{{return gameFrameCounter.readU32()}}catch(_){{return null}}}})(),
                                        gameTimeMs:(()=>{{try{{return gameTimeMs.readU32()}}catch(_){{return null}}}})(),
                                        timerStep:f(timerStep),
                                        wrapper:this.context.ecx.toString(),
                                        speed:vec(speedPtr),
                                        returnAddress:this.returnAddress.toString(),
                                    }};
                                }} catch (_) {{}}
                            }},
                            onLeave() {{
                                const record = this.nativeSetMoveSpeedRecord;
                                if (!record || !captureActive) return;
                                batch.push({{
                                    source:'gta-native-set-move-speed', label:OUTPUT_LABEL,
                                    ...record,
                                }});
                                if (batch.length >= 32) flush();
                            }},
                        }});
                    }} catch (_) {{}}
                }}
            }}
        }}
        const clientDll = Process.findModuleByName('client_d.dll');
        if (clientDll) {{
            try {{
                Interceptor.attach(clientDll.base.add(staticSetElementVelocityRva), {{
                    onEnter() {{
                        try {{
                            const sourceTag = readNativeSourceTag();
                            if (sourceTag.frame === null
                                || sourceTag.frame < PROCESSWHEEL_SOURCE_WINDOW[0]
                                || sourceTag.frame > PROCESSWHEEL_SOURCE_WINDOW[1]) return;
                            const entityPtr = this.context.esp.add(4).readPointer();
                            const speedPtr = this.context.esp.add(8).readPointer();
                            this.nativeSetElementVelocity = {{
                                sourceFrameTag:sourceTag.frame,
                                sourceTickMsTag:sourceTag.tick,
                                gameFrame:(()=>{{try{{return gameFrameCounter.readU32()}}catch(_){{return null}}}})(),
                                gameTimeMs:(()=>{{try{{return gameTimeMs.readU32()}}catch(_){{return null}}}})(),
                                timerStep:f(timerStep),
                                clientEntity:entityPtr.toString(),
                                speed:vec(speedPtr),
                                returnAddress:this.returnAddress.toString(),
                            }};
                        }} catch (_) {{}}
                    }},
                    onLeave() {{
                        const record = this.nativeSetElementVelocity;
                        if (!record || !captureActive) return;
                        batch.push({{
                            source:'gta-native-set-element-velocity',
                            label:OUTPUT_LABEL,
                            ...record,
                        }});
                        if (batch.length >= 32) flush();
                    }},
                }});
            }} catch (_) {{}}
            try {{
                const angularSetter = clientDll.base.add(staticSetElementAngularVelocityRva);
                const entryBytes = [0x55, 0x8b, 0xec];
                for (let i = 0; i < entryBytes.length; i++)
                    if (angularSetter.add(i).readU8() !== entryBytes[i])
                        throw new Error('SetElementAngularVelocity signature mismatch at ' + angularSetter);
                const writerWindow = Array.isArray(STATE_WRITER_SOURCE_WINDOW)
                    ? STATE_WRITER_SOURCE_WINDOW : PROCESSWHEEL_SOURCE_WINDOW;
                const writerTagAccepted = sourceTag => {{
                    if (!Array.isArray(writerWindow)) return false;
                    if (sourceTag.frame === null || sourceTag.frame < 1)
                        return CAPTURE_UNTAGGED_STATE_WRITERS;
                    return sourceTag.frame >= writerWindow[0] && sourceTag.frame <= writerWindow[1];
                }};
                Interceptor.attach(angularSetter, {{
                    onEnter() {{
                        try {{
                            const sourceTag = readNativeSourceTag();
                            if (!writerTagAccepted(sourceTag)) return;
                            const entityPtr = this.context.esp.add(4).readPointer();
                            const turnVelocityPtr = this.context.esp.add(8).readPointer();
                            this.nativeSetElementAngularVelocity = {{
                                sourceFrameTag:sourceTag.frame,
                                sourceTickMsTag:sourceTag.tick,
                                sourceTagWasPublished:sourceTag.frame !== null && sourceTag.frame >= 1,
                                gameFrame:(()=>{{try{{return gameFrameCounter.readU32()}}catch(_){{return null}}}})(),
                                gameTimeMs:(()=>{{try{{return gameTimeMs.readU32()}}catch(_){{return null}}}})(),
                                timerStep:f(timerStep),
                                clientEntity:entityPtr.toString(),
                                angularVelocity:vec(turnVelocityPtr),
                                returnAddress:this.returnAddress.toString(),
                                callerModule:(()=>{{
                                    try {{
                                        const module = Process.findModuleByAddress(this.returnAddress);
                                        return module ? {{
                                            name:module.name,
                                            base:module.base.toString(),
                                            size:module.size,
                                        }} : null;
                                    }} catch (_) {{ return null; }}
                                }})(),
                                callerSymbol:(()=>{{
                                    try {{ return DebugSymbol.fromAddress(this.returnAddress).toString(); }}
                                    catch (_) {{ return null; }}
                                }})(),
                                callerBacktrace:(()=>{{
                                    try {{
                                        return Thread.backtrace(this.context, Backtracer.ACCURATE)
                                            .slice(1, 9).map(address => {{
                                                try {{ return DebugSymbol.fromAddress(address).toString(); }}
                                                catch (_) {{ return address.toString(); }}
                                            }});
                                    }} catch (_) {{ return []; }}
                                }})(),
                                clientDllBase:clientDll.base.toString(),
                            }};
                        }} catch (_) {{}}
                    }},
                    onLeave() {{
                        const record = this.nativeSetElementAngularVelocity;
                        if (!record || !captureActive) return;
                        batch.push({{
                            source:'gta-native-set-element-angular-velocity',
                            label:OUTPUT_LABEL,
                            ...record,
                        }});
                        if (batch.length >= 32) flush();
                    }},
                }});
            }} catch (error) {{
                send({{type:'native_hook_error', message:'SetElementAngularVelocity: ' + String(error)}});
            }}
        }}
    }} catch(e) {{ send({{type:'native_hook_error', message:String(e)}}); }}
    setInterval(flush,100); setInterval(() => send({{type:'native_counts', processCalls, wheelCalls, frame}}),3000);
}})();
}}
"""


def _timing_probe_script() -> str:
    return """
(function installNativeTimingProbe() {
    const main = Process.mainModule;
    const gameFrame = main.base.add(0x77CB4C);
    const timerOldStep = main.base.add(0x77CB54);
    const timerStepNonClipped = main.base.add(0x77CB58);
    const timerStep = main.base.add(0x77CB5C);
    const gameTimeMs = main.base.add(0x77CB84);
    setInterval(function() {
        try {
            send({type:'native_timing', wallMs:Date.now(), gameFrame:gameFrame.readU32(), gameTimeMs:gameTimeMs.readU32(), timerOldStep:timerOldStep.readFloat(), timerStepNonClipped:timerStepNonClipped.readFloat(), timerStep:timerStep.readFloat()});
        } catch (_) {}
    }, 1000);
})();
"""


def _kill_targets() -> None:
    for process in psutil.process_iter(["name"]):
        if (process.info["name"] or "").lower() in {
            "gta_sa.exe", "gta-sa.exe", "mta server_d.exe", "mta server.exe",
            "multi theft auto_d.exe", "multi theft auto.exe", "mtasa.exe",
            "frida-helper32.exe", "frida-helper.exe"
        }:
            try:
                process.kill()
            except psutil.Error:
                pass


def _prepare_gta_import(gta_exe: Path) -> Any:
    """Temporarily redirect GTA's WINMM import to the local MTA loader proxy.

    The Debug capture launches ``gta_sa.exe`` directly.  The MTA loader proxy
    expects the executable's import descriptor to be renamed from
    ``WINMM.dll`` to ``mtasa.dll``; the normal launcher normally performs this
    patch, but a direct Frida spawn does not.  The original bytes are restored
    in the cleanup path and a side-by-side backup is kept for interrupted runs.
    """
    if not gta_exe.exists():
        return lambda: None
    original = gta_exe.read_bytes()
    before = b"WINMM.dll"
    after = b"mtasa.dll"
    if before in original:
        # The US 1.0 executable also contains the literal in its PDB/debug
        # string.  The first occurrence is the import-descriptor name, which
        # is the same entry selected by mtasa-blue's LibraryRedirectionPatch.
        backup = gta_exe.with_name(gta_exe.name + ".native-capture-original")
        if not backup.exists():
            backup.write_bytes(original)
        offset = original.find(before)
        patched = original[:offset] + after + original[offset + len(before):]
        gta_exe.write_bytes(patched)
    elif after in original:
        # Recover a patch left behind by an interrupted loader-mode run before
        # deciding whether this invocation needs to patch anything.
        backup = gta_exe.with_name(gta_exe.name + ".native-capture-original")
        if backup.exists():
            backup_bytes = backup.read_bytes()
            if before in backup_bytes:
                gta_exe.write_bytes(backup_bytes)
        return lambda: None
    else:
        return lambda: None

    def restore() -> None:
        gta_exe.write_bytes(original)

    return restore


def _prepare_registry(mta_bin: Path) -> Any:
    """Temporarily point the 32-bit MTA registry path at the debug tree."""
    import winreg

    key_path = r"SOFTWARE\WOW6432Node\Multi Theft Auto: San Andreas All\1.6"
    key = winreg.OpenKey(
        winreg.HKEY_LOCAL_MACHINE,
        key_path,
        0,
        winreg.KEY_READ | winreg.KEY_WRITE,
    )
    try:
        old_value, old_type = winreg.QueryValueEx(key, "Last Run Location")
    except FileNotFoundError:
        old_value, old_type = None, winreg.REG_SZ
    winreg.SetValueEx(key, "Last Run Location", 0, winreg.REG_SZ, str(mta_bin))
    winreg.CloseKey(key)

    def restore() -> None:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            key_path,
            0,
            winreg.KEY_SET_VALUE,
        ) as restore_key:
            if old_value is None:
                try:
                    winreg.DeleteValue(restore_key, "Last Run Location")
                except FileNotFoundError:
                    pass
            else:
                winreg.SetValueEx(restore_key, "Last Run Location", 0, old_type, old_value)

    return restore


def _prepare_playback_load_settle(mta_bin: Path, settle_ms: int) -> Any:
    """Temporarily let the loaded TAS settle before starting playback.

    Loading a large actual-race TAS immediately before ``recordplayback`` can
    make the first native ProcessControl timestep a startup outlier.  This is
    a capture-harness timing control only; it does not change TAS controls or
    physics state.
    """
    client = (
        mta_bin / "server" / "mods" / "deathmatch" / "resources"
        / "tas" / "client.lua"
    )
    if not client.exists():
        raise RuntimeError(f"TAS resource is missing: {client}")
    original = client.read_bytes()
    marker = b"\ttas.var.automation.playbackTimer = setTimer(tas.automation_start_playback, 250, 1)"
    if original.count(marker) != 1:
        raise RuntimeError(
            "playback-load-settle preparation could not find the automation playback timer"
        )
    replacement = marker.replace(b", 250, 1)", f", {int(settle_ms)}, 1)".encode("ascii"))
    client.write_bytes(original.replace(marker, replacement, 1))

    def restore() -> None:
        client.write_bytes(original)

    return restore


def _prepare_pose_only_playback(mta_bin: Path) -> Any:
    """Temporarily force recorded pose but leave native linear/angular velocity free."""
    client = (
        mta_bin / "server" / "mods" / "deathmatch" / "resources"
        / "tas" / "client.lua"
    )
    if not client.exists():
        return lambda: None
    original = client.read_bytes()
    markers = (
        (
            b"setElementVelocity(vehicle, vx, vy, vz)",
            b"-- native-capture pose-only: do not impose linear velocity\n\t\t\t-- setElementVelocity(vehicle, vx, vy, vz)",
        ),
        (
            b"setElementAngularVelocity(vehicle, rvx, rvy, rvz)",
            b"-- native-capture pose-only: do not impose angular velocity\n\t\t\t-- setElementAngularVelocity(vehicle, rvx, rvy, rvz)",
        ),
    )
    patched = original
    for old, new in markers:
        if patched.count(old) != 1:
            return lambda: None
        patched = patched.replace(old, new, 1)
    client.write_bytes(patched)

    def restore() -> None:
        client.write_bytes(original)

    return restore


def _prepare_pose_linear_only_playback(mta_bin: Path) -> Any:
    """Force recorded position/rotation/linear velocity, but not angular velocity."""
    client = (
        mta_bin / "server" / "mods" / "deathmatch" / "resources"
        / "tas" / "client.lua"
    )
    if not client.exists():
        return lambda: None
    original = client.read_bytes()
    markers = (
        (
            b"setElementAngularVelocity(vehicle, rvx, rvy, rvz)",
            b"-- native-capture pose-linear-only: do not impose angular velocity\n\t\t\t-- setElementAngularVelocity(vehicle, rvx, rvy, rvz)",
        ),
        (b"playbackInterpolation = true", b"playbackInterpolation = false"),
    )
    patched = original
    for old, new in markers:
        if patched.count(old) != 1:
            return lambda: None
        patched = patched.replace(old, new, 1)
    client.write_bytes(patched)

    def restore() -> None:
        client.write_bytes(original)

    return restore


def _prepare_controls_only_playback(mta_bin: Path) -> Any:
    """Temporarily make TAS playback apply only recorded controls/state inputs."""
    client = (
        mta_bin / "server" / "mods" / "deathmatch" / "resources"
        / "tas" / "client.lua"
    )
    if not client.exists():
        raise RuntimeError(f"controls-only TAS resource is missing: {client}")
    original = client.read_bytes()
    markers = (
        (b"useOnlyBinds = false", b"useOnlyBinds = true"),
        (b"playbackInterpolation = true", b"playbackInterpolation = false"),
    )
    patched = original
    # The deployed Debug TAS resource may already have interpolation disabled;
    # that is compatible with controls-only playback.  Do not abort the whole
    # preparation merely because that default differs from the repository copy.
    use_only_old, use_only_new = markers[0]
    if use_only_old not in patched:
        raise RuntimeError("controls-only TAS preparation could not find useOnlyBinds=false")
    patched = patched.replace(use_only_old, use_only_new, 1)
    interpolation_old, interpolation_new = markers[1]
    if interpolation_old in patched:
        patched = patched.replace(interpolation_old, interpolation_new, 1)
    elif interpolation_new not in patched:
        raise RuntimeError("controls-only TAS preparation could not find playbackInterpolation setting")
    # The TAS user config is loaded after the defaults above and can silently
    # restore useOnlyBinds=false.  Force the diagnostic mode after that load;
    # this is temporary and the exact original file is restored below.
    anchor = b"\tlocal cachedWarpsLoaded = false"
    if patched.count(anchor) != 1:
        raise RuntimeError("controls-only TAS preparation could not find post-config anchor")
    newline = b"\r\n" if b"\r\n" in patched else b"\n"
    override = newline.join(
        (
            b"\t-- native-capture controls-only: override user config after load",
            b"\ttas.settings.useOnlyBinds = true",
            b"\ttas.settings.playbackInterpolation = false",
            anchor,
        )
    )
    patched = patched.replace(anchor, override, 1)
    state_guard = b"if not tas.settings.useOnlyBinds then"
    if patched.count(state_guard) != 2:
        raise RuntimeError("controls-only TAS preparation found an unexpected playback branch count")
    # Belt-and-suspenders diagnostic guard: the setting override above covers
    # user config, while this first branch guard makes the playback state-write
    # boundary unambiguous even if a future config path changes the setting.
    patched = patched.replace(
        state_guard,
        b"if false then -- native-capture controls-only state writes disabled",
        1,
    )
    client.write_bytes(patched)

    def restore() -> None:
        client.write_bytes(original)

    return restore


def _prepare_playback_pre_render(mta_bin: Path) -> Any:
    """Temporarily schedule TAS playback from onClientPreRender."""
    client = (
        mta_bin / "server" / "mods" / "deathmatch" / "resources"
        / "tas" / "client.lua"
    )
    if not client.exists():
        return lambda: None
    original = client.read_bytes()
    marker = b"playbackPreRender = false"
    if original.count(marker) != 1:
        return lambda: None
    patched = original.replace(marker, b"playbackPreRender = true", 1)
    # User config is loaded after the defaults.  If the controls-only prep has
    # already inserted its post-config anchor, add this override there too;
    # otherwise keep the small fixture/standalone prep reversible as before.
    config_anchor = b"\ttas.settings.playbackInterpolation = false"
    if config_anchor in patched:
        newline = b"\r\n" if b"\r\n" in patched else b"\n"
        patched = patched.replace(
            config_anchor,
            config_anchor + newline + b"\ttas.settings.playbackPreRender = true",
            1,
        )
    else:
        anchor = b"\tlocal cachedWarpsLoaded = false"
        if patched.count(anchor) == 1:
            newline = b"\r\n" if b"\r\n" in patched else b"\n"
            patched = patched.replace(
                anchor,
                b"\ttas.settings.playbackPreRender = true" + newline + anchor,
                1,
            )
    client.write_bytes(patched)

    def restore() -> None:
        client.write_bytes(original)

    return restore


def _prepare_public_tas_folder(mta_bin: Path) -> Any:
    """Temporarily make the local TAS resource use its public saves folder."""
    client = mta_bin / "server" / "mods" / "deathmatch" / "resources" / "tas" / "client.lua"
    if not client.exists():
        return lambda: None
    original = client.read_bytes()
    marker = b"usePrivateFolder = true"
    if marker not in original:
        return lambda: None
    client.write_bytes(original.replace(marker, b"usePrivateFolder = false", 1))

    def restore() -> None:
        client.write_bytes(original)

    return restore


def _prepare_native_capture_output(mta_bin: Path, output_name: str) -> Any:
    """Temporarily select a unique Lua playback-output name in native_capture."""
    resource = (
        mta_bin / "server" / "mods" / "deathmatch" / "resources"
        / "native_capture" / "server.lua"
    )
    if not resource.exists():
        return lambda: None
    original = resource.read_bytes()
    marker = b'"etnies-native", "native-etnies"'
    replacement = f'"etnies-native", "{output_name}"'.encode("ascii")
    if marker not in original:
        return lambda: None
    resource.write_bytes(original.replace(marker, replacement, 1))

    def restore() -> None:
        resource.write_bytes(original)

    return restore


def _prepare_actual_race_capture(
    mta_bin: Path, record_name: str, output_name: str, delay_ms: int = 0
) -> Any:
    """Turn ``native_capture`` into a race-vehicle playback trigger.

    The real Etnies resource must own the map, vehicle, scripts, and race
    settings.  The normal native_capture resource also declares a duplicate
    map and creates its own vehicle, so actual-race mode temporarily removes
    that map/client declaration and uses the resource only to poll for the
    occupied race Infernus before triggering TAS playback.
    """
    resource = (
        mta_bin / "server" / "mods" / "deathmatch" / "resources" / "native_capture"
    )
    meta = resource / "meta.xml"
    server = resource / "server.lua"
    if not meta.exists() or not server.exists():
        raise RuntimeError(f"actual-race trigger resource is incomplete: {resource}")
    meta_backup = meta.with_name(meta.name + ".native-capture-original")
    server_backup = server.with_name(server.name + ".native-capture-original")
    current_meta = meta.read_bytes()
    current_server = server.read_bytes()
    if b"Native race capture trigger" in current_meta and meta_backup.exists():
        meta.write_bytes(meta_backup.read_bytes())
        current_meta = meta.read_bytes()
    if b"local timers = {}" in current_server and server_backup.exists():
        server.write_bytes(server_backup.read_bytes())
        current_server = server.read_bytes()
    original_meta = current_meta
    original_server = current_server
    if not meta_backup.exists():
        meta_backup.write_bytes(original_meta)
    if not server_backup.exists():
        server_backup.write_bytes(original_server)
    newline = "\r\n" if b"\r\n" in original_meta else "\n"
    record_literal = json.dumps(record_name)
    output_literal = json.dumps(output_name)
    trigger_server = f'''local timers = {{}}
local sent = {{}}

local function stopPoll(player)
    local timer = timers[player]
    if timer and isTimer(timer) then killTimer(timer) end
    timers[player] = nil
end

local function poll(player)
    if not isElement(player) then stopPoll(player) return end
    if sent[player] then stopPoll(player) return end
    local vehicle = getPedOccupiedVehicle(player)
    if not vehicle or getElementModel(vehicle) ~= 411 then return end
    local tasResource = getResourceFromName("tas")
    if not tasResource or getResourceState(tasResource) ~= "running" then return end
    sent[player] = true
    stopPoll(player)
    setTimer(function()
        if isElement(player) then
            triggerClientEvent(player, "tas:automationStart", getResourceRootElement(tasResource),
                1, {record_literal}, {output_literal})
        end
    end, {int(delay_ms)}, 1)
end

local function arm(player)
    if isElement(player) and not timers[player] and not sent[player] then
        timers[player] = setTimer(poll, 250, 0, player)
    end
end

addEventHandler("onPlayerJoin", root, function() arm(source) end)
addEventHandler("onResourceStart", resourceRoot, function()
    for _, player in ipairs(getElementsByType("player")) do arm(player) end
end)
addEventHandler("onPlayerQuit", root, function()
    stopPoll(source)
    sent[source] = nil
end)
'''.replace("\n", newline)
    trigger_meta = (
        '<meta>\n'
        '  <info name="Native race capture trigger" type="script" />\n'
        '  <script src="server.lua" type="server" />\n'
        '</meta>\n'
    ).replace("\n", newline)
    meta.write_bytes(trigger_meta.encode("utf-8"))
    server.write_bytes(trigger_server.encode("utf-8"))

    def restore() -> None:
        meta.write_bytes(original_meta)
        server.write_bytes(original_server)
        # Successful cleanup no longer needs the recovery copies. They remain
        # available only if preparation is interrupted before this callback.
        for backup in (meta_backup, server_backup):
            try:
                backup.unlink()
            except FileNotFoundError:
                pass

    return restore


def _prepare_tas_automation_playback(mta_bin: Path, output_name: str) -> Any:
    """Trigger TAS playback from native_capture without changing its vehicle.

    This legacy mode is retained for the synthetic native_capture map.  It
    replaces whichever nativeCapture event line is currently deployed rather
    than requiring a particular stale output-name literal.
    """
    server = (
        mta_bin / "server" / "mods" / "deathmatch" / "resources"
        / "native_capture" / "server.lua"
    )
    if not server.exists():
        return lambda: None
    original = server.read_bytes()
    text = original.decode("utf-8")
    lines = text.splitlines(keepends=True)
    matches = [
        index for index, line in enumerate(lines)
        if 'triggerClientEvent(player, "nativeCapture:start", resourceRoot,' in line
    ]
    if len(matches) != 1:
        return lambda: None
    index = matches[0]
    line = lines[index]
    line_ending = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
    indent = line[:len(line) - len(line.lstrip())]
    replacement = (
        f'{indent}local tasResource = getResourceFromName("tas"){line_ending}'
        f'{indent}if tasResource and getResourceState(tasResource) == "running" then{line_ending}'
        f'{indent}    triggerClientEvent(player, "tas:automationStart", '
        f'getResourceRootElement(tasResource), 1, "etnies-native", '
        f'{json.dumps(output_name)}){line_ending}'
        f'{indent}end{line_ending}'
    )
    lines[index] = replacement
    server.write_bytes("".join(lines).encode("utf-8"))

    def restore() -> None:
        server.write_bytes(original)

    return restore


def _prepare_native_capture_start_delay(mta_bin: Path, delay_ms: int) -> Any:
    """Temporarily delay source playback so the native timer can warm up."""
    client = (
        mta_bin / "server" / "mods" / "deathmatch" / "resources"
        / "native_capture" / "client.lua"
    )
    if not client.exists():
        return lambda: None
    original = client.read_bytes()
    newline = b"\r\n" if b"\r\n" in original else b"\n"
    marker_lines = [
        b"    setTimer(function()",
        b"        executeCommandHandler(\"loadr\", recordName)",
        b"        setTimer(function()",
        b"            executeCommandHandler(\"recordplayback\", outputName)",
        b"        end, 1000, 1)",
        b"    end, 1000, 1)",
    ]
    marker = newline.join(marker_lines)
    if original.count(marker) != 1:
        return lambda: None
    replacement = newline.join(marker_lines[:-1] + [f"    end, {int(delay_ms)}, 1)".encode("ascii")])
    client.write_bytes(original.replace(marker, replacement, 1))

    def restore() -> None:
        client.write_bytes(original)

    return restore


def _lua_literal(value: Any) -> str:
    if value is None:
        return "nil"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, list):
        return "{" + ",".join(_lua_literal(item) for item in value) + "}"
    if isinstance(value, dict):
        return "{" + ",".join(
            "[" + _lua_literal(str(key)) + "]=" + _lua_literal(item)
            for key, item in value.items()
        ) + "}"
    raise TypeError(f"unsupported one-tick Lua value: {type(value)!r}")


def _prepare_one_tick_resource(mta_bin: Path, config: dict[str, Any]) -> Any:
    """Temporarily make native_capture initialize one public GTA state once.

    This deliberately bypasses TAS playback.  The client writes the supplied
    state and controls once, then leaves GTA to process naturally.  The native
    stream is therefore a one-tick state-input diagnostic, not a continuous
    trajectory.
    """
    resource = mta_bin / "server" / "mods" / "deathmatch" / "resources" / "native_capture"
    server_path = resource / "server.lua"
    client_path = resource / "client.lua"
    if not server_path.exists() or not client_path.exists():
        return lambda: None
    original_server = server_path.read_bytes()
    original_client = client_path.read_bytes()
    encoded = _lua_literal(config)
    server = original_server.decode("utf-8")
    client = original_client.decode("utf-8")
    lines = server.splitlines(keepends=True)
    matches = [
        index for index, line in enumerate(lines)
        if 'triggerClientEvent(player, "nativeCapture:start", resourceRoot,' in line
    ]
    if len(matches) != 1:
        return lambda: None
    try:
        one_tick_delay_ms = max(0, int(config.get("oneTickDelayMs", 1000)))
    except (AttributeError, TypeError, ValueError):
        one_tick_delay_ms = 1000
    index = matches[0]
    line = lines[index]
    line_ending = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
    indent = line[:len(line) - len(line.lstrip())]
    replacement = (
        f"{indent}setTimer(function(){line_ending}"
        f"{indent}    if isElement(player) then{line_ending}"
        f"{indent}        triggerClientEvent(player, \"nativeCapture:oneTick\", resourceRoot, oneTickConfig){line_ending}"
        f"{indent}    end{line_ending}"
        f"{indent}end, {one_tick_delay_ms}, 1){line_ending}"
    )
    lines[index] = replacement
    server = "local oneTickConfig = " + encoded + line_ending + "".join(lines)
    client += r'''

local oneTickPending = nil
local oneTickActive = nil
local oneTickHoldUntil = 0
local function applyOneTickState()
    local vehicle = getPedOccupiedVehicle(localPlayer)
    if not vehicle then return end
    if oneTickActive == nil and type(oneTickPending) == "table" then
        oneTickActive = oneTickPending
        oneTickPending = nil
        oneTickHoldUntil = getTickCount() + math.max(0, tonumber(oneTickActive.oneTickWarmHoldMs) or 0)
    end
    local config = oneTickActive
    if type(config) ~= "table" then
        removeEventHandler("onClientPreRender", root, applyOneTickState)
        return
    end
    local function vec(value)
        return type(value) == "table" and value[1] and value[2] and value[3]
    end
    if vec(config.position) then
        setElementPosition(vehicle, config.position[1], config.position[2], config.position[3])
    end
    if vec(config.rotation) then
        setElementRotation(vehicle, config.rotation[1], config.rotation[2], config.rotation[3])
    end
    if vec(config.velocity) then
        setElementVelocity(vehicle, config.velocity[1], config.velocity[2], config.velocity[3])
    end
    if vec(config.angularVelocity) then
        setElementAngularVelocity(vehicle, config.angularVelocity[1], config.angularVelocity[2], config.angularVelocity[3])
    end
    local controls = config.controls or {}
    local names = {"accelerate", "brake_reverse", "vehicle_left", "vehicle_right", "handbrake", "steer_forward", "steer_back", "vehicle_fire", "vehicle_secondary_fire"}
    for _, name in ipairs(names) do
        setPedControlState(localPlayer, name, controls[name] == true)
    end
    local analog = config.analogControls or {}
    for _, name in ipairs({"vehicle_left", "vehicle_right", "steer_forward", "steer_back"}) do
        local value = tonumber(analog[name]) or 0
        setAnalogControlState(name, value, value ~= 0)
    end
    if config.nitro then
        if getVehicleUpgradeOnSlot(vehicle, 8) == 0 then addVehicleUpgrade(vehicle, 1010) end
        setVehicleNitroCount(vehicle, tonumber(config.nitro.count) or 100)
        setVehicleNitroLevel(vehicle, tonumber(config.nitro.level) or 1)
        setVehicleNitroActivated(vehicle, config.nitro.active == true)
    end
    if getTickCount() >= oneTickHoldUntil then
        oneTickActive = nil
        removeEventHandler("onClientPreRender", root, applyOneTickState)
    end
end
addEvent("nativeCapture:oneTick", true)
addEventHandler("nativeCapture:oneTick", resourceRoot, function(config)
    oneTickPending = config
    removeEventHandler("onClientPreRender", root, applyOneTickState)
    addEventHandler("onClientPreRender", root, applyOneTickState, true, "high+100")
end)
'''
    server_path.write_text(server, encoding="utf-8")
    client_path.write_text(client, encoding="utf-8")

    def restore() -> None:
        server_path.write_bytes(original_server)
        client_path.write_bytes(original_client)

    return restore


def _prepare_real_vorbis(mta_bin: Path) -> Any:
    """Temporarily disable the loader proxy so Frida owns MTA bootstrap."""
    original = mta_bin / "vorbisfile.dll"
    real = mta_bin / "vorbisfile_real.dll"
    backup = mta_bin / "vorbisfile.native-capture-original.dll"
    if not original.exists() or not real.exists():
        return lambda: None
    original_bytes = original.read_bytes()
    real_bytes = real.read_bytes()
    if original_bytes == real_bytes:
        # A previous interrupted/older run may have left the real DLL in the
        # proxy path.  If our diagnostic backup is available, restore it
        # before returning; otherwise a later MTA launch can fail before its
        # client log is initialized.
        if backup.exists():
            backup_bytes = backup.read_bytes()
            if backup_bytes != real_bytes:
                original.write_bytes(backup_bytes)
        return lambda: None
    if not backup.exists():
        backup.write_bytes(original_bytes)
    original.write_bytes(real.read_bytes())

    def restore() -> None:
        if backup.exists():
            original.write_bytes(backup.read_bytes())

    return restore


def _start_server(
    path: Path, commands: list[str]
) -> tuple[subprocess.Popen[str], threading.Thread, threading.Event]:
    log_path = path.parent / "mods" / "deathmatch" / "logs" / "server.log"
    try:
        log_offset = log_path.stat().st_size
    except OSError:
        log_offset = 0
    process = subprocess.Popen(
        [str(path)], cwd=str(path.parent), stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
    )
    joined = threading.Event()

    def drain() -> None:
        if process.stdout is None:
            return
        for line in process.stdout:
            if "JOIN:" in line:
                joined.set()
            if any(token in line for token in ("Server started", "CONNECT:", "JOIN:", "KICK:", "ERROR:")):
                print(f"[server] {line.rstrip()}")

    thread = threading.Thread(target=drain, daemon=True)
    thread.start()

    def watch_server_log() -> None:
        offset = log_offset
        while process.poll() is None and not joined.is_set():
            try:
                with log_path.open("r", encoding="utf-8", errors="replace") as stream:
                    stream.seek(offset)
                    chunk = stream.read()
                    offset = stream.tell()
                if "JOIN:" in chunk:
                    joined.set()
                    return
            except OSError:
                pass
            time.sleep(0.25)

    threading.Thread(target=watch_server_log, daemon=True).start()
    # The debug server's stdout is not consistently flushed through the
    # redirected pipe on Windows.  Keep a bounded startup delay rather than
    # depending on that diagnostic stream for synchronization.
    time.sleep(15)
    for command in commands:
        if process.stdin is not None:
            process.stdin.write(command + "\n")
            process.stdin.flush()
        time.sleep(2)
    return process, thread, joined


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gta-exe", type=Path, default=Path(os.environ.get("MTA_GTA_EXE", "gta_sa.exe")))
    parser.add_argument(
        "--launcher-exe",
        type=Path,
        help=(
            "launch this normal Multi Theft Auto client and attach to its new GTA child; "
            "useful when direct Frida spawning stalls before the first game tick"
        ),
    )
    parser.add_argument("--mta-bin", type=Path, default=Path(os.environ.get("MTA_BIN", ".")))
    parser.add_argument(
        "--prepare-gta-import",
        action="store_true",
        help="temporarily rename GTA's WINMM.dll import to mtasa.dll for direct loader-proxy spawning",
    )
    parser.add_argument("--server-exe", type=Path)
    parser.add_argument(
        "--connect-uri",
        default="mtasa://127.0.0.1:22003",
        help="MTA connection URI passed as the GTA command-line argument",
    )
    parser.add_argument("--start-resource", action="append", default=[])
    parser.add_argument(
        "--reference-map-resource",
        help=(
            "run the actual race map resource instead of synthetic native_capture; "
            "stop play, start race, start this map, then trigger TAS from the race vehicle"
        ),
    )
    parser.add_argument(
        "--reference-record-name",
        default="etnies-native",
        help="TAS .tas basename used by --reference-map-resource",
    )
    parser.add_argument(
        "--server-command-after",
        action="append",
        nargs=2,
        metavar=("SECONDS", "COMMAND"),
        default=[],
        help="send a server-console command after startup delay; repeatable diagnostic hook",
    )
    parser.add_argument(
        "--orchestrator",
        type=Path,
        help=(
            "optional local mtasa_deobfuscation/mta_bytecode_orchestrator.py; "
            "its proven Frida-native bootstrap/survival hooks are used when supplied"
        ),
    )
    parser.add_argument(
        "--prepare-registry",
        action="store_true",
        help="temporarily point HKLM's 32-bit MTA 1.6 Last Run Location at --mta-bin",
    )
    parser.add_argument(
        "--prepare-tas-folder",
        action="store_true",
        help="temporarily use the TAS resource's public saves folder for automated local playback",
    )
    parser.add_argument(
        "--controls-only-playback",
        action="store_true",
        help="temporarily disable recorded pose/velocity playback and apply only recorded controls",
    )
    parser.add_argument(
        "--playback-pre-render",
        action="store_true",
        help="temporarily schedule TAS playback from onClientPreRender instead of onClientRender",
    )
    parser.add_argument(
        "--one-tick-config",
        type=Path,
        help=(
            "JSON public-state/control input for a one-tick diagnostic; bypasses TAS playback, "
            "writes the state once, and leaves GTA running naturally"
        ),
    )
    parser.add_argument(
        "--pose-only-playback",
        action="store_true",
        help=(
            "temporarily force recorded position/rotation while leaving native linear and "
            "angular velocity free; diagnostic only, not an independent trajectory"
        ),
    )
    parser.add_argument(
        "--pose-linear-only-playback",
        action="store_true",
        help=(
            "temporarily force recorded position/rotation/linear velocity while leaving "
            "native angular velocity free; diagnostic only"
        ),
    )
    parser.add_argument(
        "--use-real-vorbis",
        action="store_true",
        help="temporarily replace mtasa-blue's vorbisfile loader proxy with vorbisfile_real.dll",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--duration", type=float, default=240.0,
        help=(
            "capture duration in seconds; for --reference-map-resource this is "
            "the retention budget after the client JOIN"
        ),
    )
    parser.add_argument("--label", default="native-processwheel")
    parser.add_argument(
        "--cpp-hook",
        action="store_true",
        help=(
            "use the optional local mtasa-blue C++ call-site hook instead of "
            "Frida ProcessWheel interception; writes a sibling .cpp.bin stream"
        ),
    )
    parser.add_argument(
        "--cpp-stage-only",
        action="store_true",
        help=(
            "use only the lower-overhead C++ ProcessControl/ProcessSuspension "
            "boundary observers; do not install the ProcessWheel hook"
        ),
    )
    parser.add_argument(
        "--cpp-minimal",
        action="store_true",
        help=(
            "use the C++ ProcessWheel wrapper but capture only direct wheel/contact and "
            "velocity fields; useful for long-run hook-perturbation isolation"
        ),
    )
    parser.add_argument(
        "--cpp-no-matrix",
        action="store_true",
        help=(
            "use the full C++ capture except for the vehicle matrix read; "
            "isolates matrix-snapshot perturbation in long runs"
        ),
    )
    parser.add_argument(
        "--cpp-static-skid-diagnostics",
        action="store_true",
        help="enable the C++ direct read of bAlreadySkidding at 0xC1CDAC",
    )
    parser.add_argument(
        "--cpp-processcontrol-boundary",
        action="store_true",
        help=(
            "capture source ProcessControl entry/exit state in the optional "
            "C++ boundary stream; diagnostic only"
        ),
    )
    parser.add_argument(
        "--cpp-processcontrol-source-window",
        type=int,
        nargs=2,
        metavar=("START", "END"),
        help=(
            "limit the C++ ProcessControl boundary stream to inclusive source "
            "frame tags; requires --cpp-processcontrol-boundary"
        ),
    )
    parser.add_argument(
        "--cpp-processsuspension-boundary",
        action="store_true",
        help=(
            "capture direct CAutomobile::ProcessSuspension entry/exit state "
            "with the C++ trampoline hook; diagnostic only"
        ),
    )
    parser.add_argument(
        "--cpp-processsuspension-source-window",
        type=int,
        nargs=2,
        metavar=("START", "END"),
        help=(
            "limit the C++ ProcessSuspension boundary stream to inclusive source "
            "frame tags; requires --cpp-processsuspension-boundary"
        ),
    )
    parser.add_argument(
        "--timing-only",
        action="store_true",
        help="run the automated playback with no ProcessWheel hook and report timer samples",
    )
    parser.add_argument(
        "--collision-diagnostics",
        action="store_true",
        help="observe collision callbacks in the Frida route, or C++ ApplyCollisionAlt with --cpp-hook",
    )
    parser.add_argument(
        "--static-skid-diagnostics",
        action="store_true",
        help="read GTA's private CVehicle::ProcessWheel bAlreadySkidding static (Frida only)",
    )
    parser.add_argument(
        "--frida-processwheel-source-window",
        type=int,
        nargs=2,
        metavar=("START", "END"),
        help=(
            "limit Frida ProcessWheel rows to inclusive native source-frame tags; "
            "diagnostic only and incompatible with C++/timing/stage routes"
        ),
    )
    parser.add_argument(
        "--frida-state-writer-source-window",
        type=int,
        nargs=2,
        metavar=("START", "END"),
        help=(
            "limit the read-only SetElementAngularVelocity writer diagnostic to "
            "inclusive source tags; use with the Frida route"
        ),
    )
    parser.add_argument(
        "--frida-state-writer-capture-untagged",
        action="store_true",
        help=(
            "also retain angular-writer calls made before the source-tag bridge "
            "publishes its first tag; diagnostic provenance is explicitly untagged"
        ),
    )
    parser.add_argument(
        "--frida-source-tag-order-diagnostics",
        action="store_true",
        help=(
            "record the read-only source-tag bridge call timing/order relative to "
            "native ProcessControl; bounded diagnostic only"
        ),
    )
    parser.add_argument(
        "--frida-processwheel-with-processsuspension",
        action="store_true",
        help=(
            "pair the bounded Frida ProcessWheel window with a lightweight "
            "ProcessSuspension boundary; requires --frida-processwheel-source-window"
        ),
    )
    parser.add_argument(
        "--frida-processcollision-source-window",
        type=int,
        nargs=2,
        metavar=("START", "END"),
        help=(
            "capture a narrow Frida ProcessCollision entry/exit boundary for source tags; "
            "diagnostic only and incompatible with C++/timing routes"
        ),
    )
    parser.add_argument(
        "--frida-processsuspension-source-window",
        type=int,
        nargs=2,
        metavar=("START", "END"),
        help=(
            "capture a narrow Frida ProcessSuspension entry/exit boundary for source tags; "
            "diagnostic only and incompatible with C++/timing/collision-stage routes"
        ),
    )
    parser.add_argument(
        "--frida-processwheel-no-writer-diagnostics",
        action="store_true",
        help=(
            "skip SetMoveSpeed/SetElementVelocity side-channel hooks for a bounded "
            "ProcessWheel window; use only after state-write absence is independently established"
        ),
    )
    parser.add_argument(
        "--frida-processwheel-no-transmission-diagnostics",
        action="store_true",
        help=(
            "skip the CalculateDriveAcceleration boundary hook for a bounded "
            "ProcessWheel window after transmission behavior has been captured separately"
        ),
    )
    parser.add_argument(
        "--capture-from-first-gas",
        action="store_true",
        help="buffer native rows until the first nonzero gas/brake, avoiding warm-up IPC overhead",
    )
    parser.add_argument(
        "--suspension-stage-only",
        action="store_true",
        help="with --collision-diagnostics, retain only ProcessEntityCollision/ProcessSuspension snapshots",
    )
    parser.add_argument(
        "--stage-force-diagnostics",
        action="store_true",
        help=(
            "in suspension-stage-only Frida captures, publish ProcessSuspension "
            "entry/exit physical velocity state; diagnostic only"
        ),
    )
    parser.add_argument(
        "--stage-force-events",
        action="store_true",
        help=(
            "capture only the nested ProcessSuspension ApplyForce events with "
            "raw before/after velocity deltas; requires a bounded source window"
        ),
    )
    parser.add_argument(
        "--stage-force-source-window",
        type=int,
        nargs=2,
        metavar=("START", "END"),
        help="inclusive exact source-tag window for --stage-force-events",
    )
    parser.add_argument(
        "--playback-output-name",
        help="temporarily select this Lua physics-output name in the local native_capture resource",
    )
    parser.add_argument(
        "--playback-start-delay-ms",
        type=int,
        default=1000,
        help="delay source playback after vehicle setup; use 30000 for a warm native timer window",
    )
    parser.add_argument(
        "--playback-load-settle-ms",
        type=int,
        default=250,
        help=(
            "wait after loading the TAS file before recordplayback; capture-harness "
            "timing control for startup outlier diagnostics"
        ),
    )
    parser.add_argument(
        "--tas-automation-playback",
        action="store_true",
        help=(
            "trigger TAS playback through its server automation event instead of "
            "native_capture's client event; useful when resource-start ordering drops that event"
        ),
    )
    args = parser.parse_args()
    if args.cpp_stage_only:
        args.cpp_hook = True
        args.cpp_processcontrol_boundary = True
        args.cpp_processsuspension_boundary = True
    if args.frida_processwheel_source_window:
        start_frame, end_frame = args.frida_processwheel_source_window
        if start_frame < 1 or end_frame < start_frame:
            parser.error("invalid Frida ProcessWheel source window")
        if args.cpp_hook or args.timing_only or args.suspension_stage_only:
            parser.error("--frida-processwheel-source-window requires the Frida ProcessWheel route")
    if args.frida_state_writer_source_window:
        start_frame, end_frame = args.frida_state_writer_source_window
        if start_frame < 1 or end_frame < start_frame:
            parser.error("invalid Frida state-writer source window")
        if args.cpp_hook or args.timing_only:
            parser.error("--frida-state-writer-source-window requires the Frida route")
    if args.frida_state_writer_capture_untagged and not args.frida_state_writer_source_window:
        parser.error("--frida-state-writer-capture-untagged requires --frida-state-writer-source-window")
    if args.frida_source_tag_order_diagnostics and (args.cpp_hook or args.timing_only):
        parser.error("--frida-source-tag-order-diagnostics requires the Frida route")
    if args.frida_processcollision_source_window:
        start_frame, end_frame = args.frida_processcollision_source_window
        if start_frame < 1 or end_frame < start_frame:
            parser.error("invalid Frida ProcessCollision source window")
        if args.cpp_hook or args.timing_only:
            parser.error("--frida-processcollision-source-window requires the Frida route")
    if args.frida_processsuspension_source_window:
        start_frame, end_frame = args.frida_processsuspension_source_window
        if start_frame < 1 or end_frame < start_frame:
            parser.error("invalid Frida ProcessSuspension source window")
        if args.cpp_hook or args.timing_only or args.collision_diagnostics or args.suspension_stage_only:
            parser.error("--frida-processsuspension-source-window requires the reduced Frida wheel route")
    if args.cpp_minimal or args.cpp_no_matrix:
        args.cpp_hook = True
    if args.frida_processwheel_with_processsuspension:
        if not args.frida_processwheel_source_window:
            parser.error(
                "--frida-processwheel-with-processsuspension requires "
                "--frida-processwheel-source-window"
            )
        if args.cpp_hook or args.timing_only or args.collision_diagnostics or args.suspension_stage_only:
            parser.error(
                "--frida-processwheel-with-processsuspension requires the "
                "lightweight Frida wheel route without collision diagnostics"
            )
    playback_modes = sum(
        bool(value) for value in (
            args.controls_only_playback,
            args.pose_only_playback,
            args.pose_linear_only_playback,
            args.one_tick_config,
        )
    )
    if playback_modes > 1:
        parser.error("playback-only diagnostic modes are mutually exclusive")
    if args.cpp_minimal and args.cpp_no_matrix:
        parser.error("--cpp-minimal and --cpp-no-matrix are mutually exclusive")
    if args.cpp_stage_only and (args.cpp_minimal or args.cpp_no_matrix):
        parser.error("--cpp-stage-only cannot be combined with wheel capture options")
    if args.cpp_hook and args.timing_only:
        parser.error("--cpp-hook and --timing-only are mutually exclusive")
    if args.static_skid_diagnostics and (args.cpp_hook or args.timing_only):
        parser.error("--static-skid-diagnostics requires the Frida ProcessWheel route")
    if args.cpp_static_skid_diagnostics and not args.cpp_hook:
        parser.error("--cpp-static-skid-diagnostics requires --cpp-hook")
    if args.cpp_processcontrol_boundary and not args.cpp_hook:
        parser.error("--cpp-processcontrol-boundary requires --cpp-hook")
    if args.cpp_processsuspension_boundary and not args.cpp_hook:
        parser.error("--cpp-processsuspension-boundary requires --cpp-hook")
    if args.cpp_processcontrol_source_window and not args.cpp_processcontrol_boundary:
        parser.error("--cpp-processcontrol-source-window requires --cpp-processcontrol-boundary")
    if args.cpp_processcontrol_source_window:
        start_frame, end_frame = args.cpp_processcontrol_source_window
        if start_frame < 1 or end_frame < start_frame:
            parser.error("invalid C++ ProcessControl source window")
    if args.cpp_processsuspension_source_window and not args.cpp_processsuspension_boundary:
        parser.error("--cpp-processsuspension-source-window requires --cpp-processsuspension-boundary")
    if args.cpp_processsuspension_source_window:
        start_frame, end_frame = args.cpp_processsuspension_source_window
        if start_frame < 1 or end_frame < start_frame:
            parser.error("invalid C++ ProcessSuspension source window")
    if args.launcher_exe and args.prepare_gta_import:
        parser.error("--launcher-exe uses the normal launcher and cannot use --prepare-gta-import")
    if args.playback_output_name and not args.playback_output_name.replace("-", "").replace("_", "").isalnum():
        parser.error("--playback-output-name may contain only letters, numbers, '-' and '_'")
    if not args.reference_record_name.replace("-", "").replace("_", "").isalnum():
        parser.error("--reference-record-name may contain only letters, numbers, '-' and '_'")
    if any(character in args.connect_uri for character in "\r\n"):
        parser.error("--connect-uri must be a single command-line argument")
    if args.reference_map_resource and (not args.server_exe or args.tas_automation_playback):
        parser.error("--reference-map-resource requires --server-exe and cannot use --tas-automation-playback")
    if args.reference_map_resource and not args.prepare_tas_folder:
        parser.error("--reference-map-resource requires --prepare-tas-folder so the local TAS file is available")
    if args.reference_map_resource and any("\r" in value or "\n" in value for value in (args.reference_map_resource,)):
        parser.error("--reference-map-resource must be a single server resource name")
    if args.playback_start_delay_ms < 0:
        parser.error("--playback-start-delay-ms must be non-negative")
    if args.playback_load_settle_ms < 0:
        parser.error("--playback-load-settle-ms must be non-negative")
    if args.reference_map_resource:
        # etnies-native.tas contains 17,781 frames at 99 FPS.  Include client
        # startup/map setup and the requested warm-up; never silently kill a
        # real playback halfway through just because the caller copied a short
        # synthetic-capture duration.
        minimum_duration = (
            60.0 + (17781.0 / 99.0) + 15.0
            + args.playback_start_delay_ms / 1000.0
            + args.playback_load_settle_ms / 1000.0
        )
        if args.duration < minimum_duration:
            parser.error(
                f"--reference-map-resource requires --duration >= {minimum_duration:.1f}s "
                "to retain the complete TAS playback"
            )
    if args.suspension_stage_only and (
        (not args.collision_diagnostics and not args.frida_source_tag_order_diagnostics)
        or args.cpp_hook or args.timing_only
    ):
        parser.error(
            "--suspension-stage-only requires Frida --collision-diagnostics, "
            "unless it is used for source-tag-order diagnostics"
        )
    if args.stage_force_diagnostics and not args.suspension_stage_only:
        parser.error("--stage-force-diagnostics requires --suspension-stage-only")
    if args.stage_force_events and not args.suspension_stage_only:
        parser.error("--stage-force-events requires --suspension-stage-only")
    if args.stage_force_events and not args.stage_force_diagnostics:
        parser.error("--stage-force-events requires --stage-force-diagnostics")
    if args.stage_force_events and not args.stage_force_source_window:
        parser.error("--stage-force-events requires --stage-force-source-window")
    if args.stage_force_source_window and not args.stage_force_events:
        parser.error("--stage-force-source-window requires --stage-force-events")
    if args.stage_force_source_window:
        start_frame, end_frame = args.stage_force_source_window
        if start_frame < 1 or end_frame < start_frame:
            parser.error("invalid stage force source window")
    if args.cpp_stage_only and args.timing_only:
        parser.error("--cpp-stage-only cannot be combined with --timing-only")
    server_commands_after: list[tuple[float, str]] = []
    for raw_delay, command in args.server_command_after:
        try:
            delay = float(raw_delay)
        except ValueError:
            parser.error(f"invalid --server-command-after delay: {raw_delay!r}")
        if delay < 0.0 or not command.strip():
            parser.error("--server-command-after requires a non-negative delay and command")
        server_commands_after.append((delay, command))
    one_tick_config: dict[str, Any] | None = None
    if args.one_tick_config:
        try:
            loaded = json.loads(args.one_tick_config.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            parser.error(f"could not read --one-tick-config: {exc}")
        if not isinstance(loaded, dict):
            parser.error("--one-tick-config must contain a JSON object")
        one_tick_config = loaded
    _kill_targets()
    mta_bin = args.mta_bin.resolve()
    cpp_binary = args.output.with_suffix(args.output.suffix + ".cpp.bin")
    cpp_control_binary = args.output.with_suffix(args.output.suffix + ".control.bin")
    cpp_suspension_binary = args.output.with_suffix(args.output.suffix + ".suspension.bin")
    cpp_collision_binary = args.output.with_suffix(args.output.suffix + ".collision.bin")
    timing_output = args.output.with_suffix(args.output.suffix + ".timing.jsonl")
    previous_collision_flush_every = os.environ.get(
        "MTA_NATIVE_COLLISION_ALT_CPP_FLUSH_EVERY"
    )
    previous_processcontrol_output = os.environ.get(
        "MTA_NATIVE_PROCESSCONTROL_CPP_OUTPUT"
    )
    previous_processcontrol_start = os.environ.get(
        "MTA_NATIVE_PROCESSCONTROL_CPP_START_FRAME"
    )
    previous_processcontrol_end = os.environ.get(
        "MTA_NATIVE_PROCESSCONTROL_CPP_END_FRAME"
    )
    previous_processsuspension_output = os.environ.get(
        "MTA_NATIVE_PROCESSSUSPENSION_CPP_OUTPUT"
    )
    previous_processsuspension_start = os.environ.get(
        "MTA_NATIVE_PROCESSSUSPENSION_CPP_START_FRAME"
    )
    previous_processsuspension_end = os.environ.get(
        "MTA_NATIVE_PROCESSSUSPENSION_CPP_END_FRAME"
    )
    previous_mta_bin = os.environ.get("MTA_BIN")
    previous_capture_diagnostics = os.environ.get("MTA_NATIVE_CAPTURE_DIAGNOSTICS")
    os.environ["MTA_NATIVE_CAPTURE_DIAGNOSTICS"] = "1"
    if args.cpp_hook or args.timing_only or one_tick_config is not None:
        timing_output.parent.mkdir(parents=True, exist_ok=True)
        if timing_output.exists():
            timing_output.unlink()
    if args.cpp_hook:
        if not args.cpp_stage_only:
            cpp_binary.parent.mkdir(parents=True, exist_ok=True)
            if cpp_binary.exists():
                cpp_binary.unlink()
            os.environ["MTA_NATIVE_PROCESSWHEEL_CPP_OUTPUT"] = str(cpp_binary.resolve())
        else:
            os.environ.pop("MTA_NATIVE_PROCESSWHEEL_CPP_OUTPUT", None)
        if args.cpp_minimal:
            os.environ["MTA_NATIVE_PROCESSWHEEL_CPP_MINIMAL"] = "1"
        if args.cpp_no_matrix:
            os.environ["MTA_NATIVE_PROCESSWHEEL_CPP_NO_MATRIX"] = "1"
        if args.cpp_static_skid_diagnostics:
            os.environ["MTA_NATIVE_PROCESSWHEEL_CPP_STATIC_LATCH"] = "1"
        if args.cpp_processcontrol_boundary:
            cpp_control_binary.parent.mkdir(parents=True, exist_ok=True)
            if cpp_control_binary.exists():
                cpp_control_binary.unlink()
            os.environ["MTA_NATIVE_PROCESSCONTROL_CPP_OUTPUT"] = str(
                cpp_control_binary.resolve()
            )
            if args.cpp_processcontrol_source_window:
                os.environ["MTA_NATIVE_PROCESSCONTROL_CPP_START_FRAME"] = str(
                    args.cpp_processcontrol_source_window[0]
                )
                os.environ["MTA_NATIVE_PROCESSCONTROL_CPP_END_FRAME"] = str(
                    args.cpp_processcontrol_source_window[1]
                )
        if args.cpp_processsuspension_boundary:
            cpp_suspension_binary.parent.mkdir(parents=True, exist_ok=True)
            if cpp_suspension_binary.exists():
                cpp_suspension_binary.unlink()
            os.environ["MTA_NATIVE_PROCESSSUSPENSION_CPP_OUTPUT"] = str(
                cpp_suspension_binary.resolve()
            )
            suspension_window = args.cpp_processsuspension_source_window
            if suspension_window is None and args.cpp_stage_only:
                # Stage-only captures are normally bounded together: the
                # ProcessControl matrix boundary and direct suspension state
                # must cover the same source tags without paying full-run hook
                # overhead.  An explicit suspension window still wins.
                suspension_window = args.cpp_processcontrol_source_window
            if suspension_window is not None:
                os.environ["MTA_NATIVE_PROCESSSUSPENSION_CPP_START_FRAME"] = str(
                    suspension_window[0]
                )
                os.environ["MTA_NATIVE_PROCESSSUSPENSION_CPP_END_FRAME"] = str(
                    suspension_window[1]
                )
        if args.collision_diagnostics:
            if cpp_collision_binary.exists():
                cpp_collision_binary.unlink()
            os.environ["MTA_NATIVE_COLLISION_ALT_CPP_OUTPUT"] = str(cpp_collision_binary.resolve())
            # The native collision stream is a forensic side channel.  Flush
            # each row so a short valid run cannot be mistaken for a zero-row
            # capture merely because its final partial batch was never flushed.
            os.environ["MTA_NATIVE_COLLISION_ALT_CPP_FLUSH_EVERY"] = "1"
    if args.launcher_exe:
        # The normal launcher already supplies the parent-process installation
        # root.  Do not force the direct-spawn path resolver onto its child.
        os.environ.pop("MTA_BIN", None)
    else:
        os.environ["MTA_BIN"] = str(mta_bin)
    if not args.launcher_exe:
        # Direct Frida/loader launches do not reliably reach the normal URI
        # command path; the debug client has an explicitly gated fallback.
        os.environ["MTA_NATIVE_CAPTURE_AUTOCONNECT"] = "1"
    else:
        os.environ.pop("MTA_NATIVE_CAPTURE_AUTOCONNECT", None)
    playback_output_name = args.playback_output_name or "native-etnies"
    restore_registry = _prepare_registry(mta_bin) if args.prepare_registry else (lambda: None)
    restore_tas_folder = _prepare_public_tas_folder(mta_bin) if args.prepare_tas_folder else (lambda: None)
    restore_actual_race = (
        _prepare_actual_race_capture(
            mta_bin, args.reference_record_name, playback_output_name,
            args.playback_start_delay_ms
        )
        if args.reference_map_resource else (lambda: None)
    )
    restore_pose_linear_only = (
        _prepare_pose_linear_only_playback(mta_bin)
        if args.pose_linear_only_playback else (lambda: None)
    )
    restore_pose_only = (
        _prepare_pose_only_playback(mta_bin)
        if args.pose_only_playback else (lambda: None)
    )
    restore_controls_only = (
        _prepare_controls_only_playback(mta_bin)
        if args.controls_only_playback else (lambda: None)
    )
    restore_playback_load_settle = (
        _prepare_playback_load_settle(mta_bin, args.playback_load_settle_ms)
        if args.reference_map_resource else (lambda: None)
    )
    restore_playback_pre_render = (
        _prepare_playback_pre_render(mta_bin)
        if args.playback_pre_render else (lambda: None)
    )
    restore_one_tick = (
        _prepare_one_tick_resource(mta_bin, one_tick_config)
        if one_tick_config is not None else (lambda: None)
    )
    restore_capture_output = (
        _prepare_native_capture_output(mta_bin, args.playback_output_name)
        if args.playback_output_name and not args.tas_automation_playback else (lambda: None)
    )
    restore_tas_automation = (
        _prepare_tas_automation_playback(mta_bin, playback_output_name)
        if args.tas_automation_playback else (lambda: None)
    )
    restore_capture_start_delay = _prepare_native_capture_start_delay(
        mta_bin, args.playback_start_delay_ms
    )
    restore_vorbis = _prepare_real_vorbis(mta_bin) if args.use_real_vorbis else (lambda: None)
    server = None
    server_joined: threading.Event | None = None
    server_command_lock = threading.Lock()
    server_command_timers: list[threading.Timer] = []
    reference_race_cancel = threading.Event()
    reference_race_thread: threading.Thread | None = None
    scheduled_commands = list(server_commands_after)

    def send_server_command(command: str) -> None:
        if server is None or server.poll() is not None or server.stdin is None:
            return
        try:
            with server_command_lock:
                server.stdin.write(command + "\r\n")
                server.stdin.flush()
            print(f"[server-cmd-after] {command}")
        except OSError as exc:
            print(f"[server-cmd-after-error] {exc}")
    if args.server_exe:
        if args.reference_map_resource:
            # Keep the real map stopped until the debug client has joined.
            # Race ends an empty map, and direct Frida/loader startup can be
            # much slower than a fixed wall-clock schedule.
            server_commands = [
                "refresh",
                "stop play",
                "start tas",
                "start native_capture",
            ]
        else:
            server_commands = ["refresh", *[f"start {name}" for name in args.start_resource]]
        server, _, server_joined = _start_server(args.server_exe.resolve(), server_commands)
        scheduled_commands = list(server_commands_after)
        if args.reference_map_resource:
            def start_reference_race_after_join() -> None:
                assert server_joined is not None
                while not server_joined.wait(0.25):
                    if reference_race_cancel.is_set():
                        return
                if reference_race_cancel.is_set():
                    return
                send_server_command("start race")
                if reference_race_cancel.wait(2.0):
                    return
                send_server_command(f"start {args.reference_map_resource}")

            reference_race_thread = threading.Thread(
                target=start_reference_race_after_join,
                name="native-capture-start-reference-race-after-join",
                daemon=True,
            )
            reference_race_thread.start()
        for delay, command in scheduled_commands:
            timer = threading.Timer(delay, send_server_command, args=(command,))
            timer.daemon = True
            timer.start()
            server_command_timers.append(timer)

    device = frida.get_local_device()
    gta = args.gta_exe.resolve()
    launcher = args.launcher_exe.resolve() if args.launcher_exe else None
    restore_gta_import = (
        _prepare_gta_import(gta) if args.prepare_gta_import else (lambda: None)
    )
    launcher_process: subprocess.Popen[Any] | None = None
    pid: int | None = None
    spawned_suspended = False
    try:
        if launcher is not None:
            if not launcher.exists():
                raise FileNotFoundError(f"launcher executable not found: {launcher}")
            existing_gta_pids = {
                int(process.pid)
                for process in device.enumerate_processes()
                if process.name.lower().rstrip(".exe") in {"gta_sa", "gta-sa"}
            }
            launcher_process = subprocess.Popen(
                [str(launcher), args.connect_uri],
                cwd=str(launcher.parent),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            # Let the normal launcher/GTA pair finish its L3 startup and
            # establish the network session before Frida attaches.  C++ hooks
            # are already installed by multiplayer_sa_d.dll and do not require
            # this late observer attachment.
            if server_joined is not None:
                join_deadline = time.monotonic() + max(90.0, float(args.duration))
                while not server_joined.wait(0.25):
                    if time.monotonic() >= join_deadline:
                        raise RuntimeError("normal MTA launcher did not reach server JOIN")
            deadline = time.monotonic() + max(30.0, float(args.duration))
            while time.monotonic() < deadline:
                candidates = [
                    process for process in device.enumerate_processes()
                    if process.name.lower().rstrip(".exe") in {"gta_sa", "gta-sa"}
                    and int(process.pid) not in existing_gta_pids
                ]
                if candidates:
                    pid = int(candidates[0].pid)
                    break
                time.sleep(0.25)
            if pid is None:
                raise RuntimeError("normal MTA launcher did not create a new gta_sa.exe")
            session = device.attach(pid)
        else:
            spawned_suspended = True
            pid = int(device.spawn(
                str(gta), argv=[str(gta), args.connect_uri], cwd=str(gta.parent)
            ))
            session = device.attach(pid)
    except Exception:
        restore_gta_import()
        if launcher_process is not None and launcher_process.poll() is None:
            launcher_process.terminate()
        raise
    args.output.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "format": "gta-native-pre-processwheel-capture",
        "format_version": 1,
        "label": args.label,
        "gta_executable": str(gta),
        "launcher_executable": str(launcher) if launcher else "",
        "mta_bin": str(args.mta_bin.resolve()),
        "prepare_gta_import": bool(args.prepare_gta_import),
        "frida_bootstrap": not bool(args.prepare_gta_import or launcher),
        "reference_map_resource": args.reference_map_resource or "",
        "reference_record_name": args.reference_record_name,
        "connect_uri": args.connect_uri,
        "actual_race_capture": bool(args.reference_map_resource),
        "process_wheel_va": hex(IMAGE_BASE + PROCESS_WHEEL_RVA),
        "process_wheel_rva": hex(PROCESS_WHEEL_RVA),
        "processwheel_source_window": (
            list(args.frida_processwheel_source_window)
            if args.frida_processwheel_source_window else None
        ),
        "state_writer_source_window": (
            list(args.frida_state_writer_source_window)
            if args.frida_state_writer_source_window else None
        ),
        "capture_untagged_state_writers": bool(args.frida_state_writer_capture_untagged),
        "source_tag_order_diagnostics": bool(args.frida_source_tag_order_diagnostics),
        "angular_writer_rva_client_dll": hex(0x7AE0B0),
        "paired_processsuspension": bool(args.frida_processwheel_with_processsuspension),
        "processcollision_source_window": (
            list(args.frida_processcollision_source_window)
            if args.frida_processcollision_source_window else None
        ),
        "processsuspension_source_window": (
            list(args.frida_processsuspension_source_window)
            if args.frida_processsuspension_source_window else None
        ),
        "native_state_writer_diagnostics": bool(
            (args.frida_processwheel_source_window or args.frida_state_writer_source_window)
            and not args.frida_processwheel_no_writer_diagnostics
        ),
        "native_transmission_diagnostics": not args.frida_processwheel_no_transmission_diagnostics,
        "capture_level": (
            "suspension-boundary"
            if args.frida_processsuspension_source_window
            else "collision-stage" if args.suspension_stage_only else "wheel"
        ),
        "install_wheel_hook": not (args.cpp_hook or args.timing_only or args.suspension_stage_only),
        "direct_observable": (
            "CAutomobile ProcessControlCollisionCheck/ProcessCollision/"
            "ProcessEntityCollision/ProcessSuspension stage snapshots and "
            "ProcessControl matrices"
            if args.suspension_stage_only
            else "CVehicle::ProcessWheel entry arguments and vehicle state plus "
            "lightweight ProcessSuspension physical boundary"
            if args.frida_processwheel_with_processsuspension
            else "CVehicle::ProcessWheel entry arguments and vehicle state"
        ),
        "hook": (
            "mtasa-blue C++ minimal call-site wrapper"
            if args.cpp_minimal
            else "mtasa-blue C++ no-matrix call-site wrapper"
            if args.cpp_no_matrix
            else "mtasa-blue C++ call-site wrapper"
            if args.cpp_hook
            else "none (timer probe)"
            if args.timing_only
            else "Frida entry hook"
        ),
        "cpp_binary": str(cpp_binary.resolve())
        if args.cpp_hook and not args.cpp_stage_only else "",
        "cpp_control_binary": (
            str(cpp_control_binary.resolve())
            if args.cpp_processcontrol_boundary else ""
        ),
        "cpp_suspension_binary": (
            str(cpp_suspension_binary.resolve())
            if args.cpp_processsuspension_boundary else ""
        ),
        "cpp_processcontrol_boundary": bool(args.cpp_processcontrol_boundary),
        "cpp_processsuspension_boundary": bool(args.cpp_processsuspension_boundary),
        "cpp_processcontrol_source_window": (
            list(args.cpp_processcontrol_source_window)
            if args.cpp_processcontrol_source_window else None
        ),
        "cpp_processsuspension_source_window": (
            list(args.cpp_processsuspension_source_window)
            if args.cpp_processsuspension_source_window
            else list(args.cpp_processcontrol_source_window)
            if args.cpp_stage_only and args.cpp_processcontrol_source_window
            else None
        ),
        "cpp_collision_binary": (
            str(cpp_collision_binary.resolve())
            if args.cpp_hook and args.collision_diagnostics else ""
        ),
        "cpp_collision_flush_every": bool(args.cpp_hook and args.collision_diagnostics),
        "timing_samples": str(timing_output.resolve())
        if args.cpp_hook or args.timing_only or one_tick_config is not None else "",
        "collision_diagnostics": bool(args.collision_diagnostics),
        "suspension_stage_only": bool(args.suspension_stage_only),
        "stage_force_diagnostics": bool(args.stage_force_diagnostics),
        "stage_force_events": bool(args.stage_force_events),
        "stage_force_source_window": (
            list(args.stage_force_source_window)
            if args.stage_force_source_window else None
        ),
        "static_skid_diagnostics": bool(args.static_skid_diagnostics or args.cpp_static_skid_diagnostics),
        "capture_from_first_gas": bool(args.capture_from_first_gas),
        "cpp_static_skid_diagnostics": bool(args.cpp_static_skid_diagnostics),
        "cpp_source_frame_tagging": bool(args.cpp_hook),
        "source_tag_semantics": (
            "after-control-write-render-callback"
            if args.cpp_hook
            else "not_applicable"
        ),
        "cpp_capture_level": (
            "stage-only" if args.cpp_stage_only
            else "minimal" if args.cpp_minimal
            else "no-matrix" if args.cpp_no_matrix
            else "full" if args.cpp_hook else "none"
        ),
        "cpp_stage_only": bool(args.cpp_stage_only),
        "prepare_tas_folder": bool(args.prepare_tas_folder),
        "controls_only_playback": bool(args.controls_only_playback),
        "playback_pre_render": bool(args.playback_pre_render),
        "pose_only_playback": bool(args.pose_only_playback),
        "pose_linear_only_playback": bool(args.pose_linear_only_playback),
        "playback_output_name": playback_output_name if (args.tas_automation_playback or args.reference_map_resource) else args.playback_output_name or "",
        "playback_start_delay_ms": args.playback_start_delay_ms,
        "playback_load_settle_ms": args.playback_load_settle_ms,
        "tas_automation_playback": bool(args.tas_automation_playback),
        "one_tick_diagnostic": one_tick_config is not None,
        "one_tick_config": one_tick_config or {},
        "server_commands_after": [
            {"delay_s": delay, "command": command}
            for delay, command in scheduled_commands
        ],
        "reference_map_start": (
            "after_server_join_start_race_then_map"
            if args.reference_map_resource
            else "not_applicable"
        ),
        "duration_semantics": (
            "post_join_retention_budget"
            if args.reference_map_resource
            else "wall_clock_from_capture_start"
        ),
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
        elif kind in {
            "native_bootstrap", "native_bootstrap_stage", "native_bootstrap_error",
            "native_hook_error", "native_exception", "info", "warn", "error",
        }:
            print(f"[frida] {payload}")
        elif kind == "native_source_tag_bridge_batch":
            with args.output.open("a", encoding="utf-8") as stream:
                for row in payload.get("records", []):
                    stream.write(json.dumps(row, separators=(",", ":")) + "\n")
        elif kind == "native_counts":
            print(f"[native] process={payload.get('processCalls')} wheel={payload.get('wheelCalls')} frame={payload.get('frame')}")
        elif kind == "native_timing":
            if args.cpp_hook or args.timing_only or one_tick_config is not None:
                with timing_output.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(payload, separators=(",", ":")) + "\n")
            print(f"[timing] wallMs={payload.get('wallMs')} gameTimeMs={payload.get('gameTimeMs')} gameFrame={payload.get('gameFrame')}")

    native_script = _native_script(
        args.mta_bin.resolve(), args.label,
        install_wheel_hook=not (args.cpp_hook or args.timing_only or args.suspension_stage_only),
        collision_diagnostics=args.collision_diagnostics,
        suspension_stage_only=args.suspension_stage_only,
        stage_force_diagnostics=args.stage_force_diagnostics,
        stage_force_events=args.stage_force_events,
        stage_force_source_window=(
            tuple(args.stage_force_source_window)
            if args.stage_force_source_window else None
        ),
        static_skid_diagnostics=args.static_skid_diagnostics,
        capture_from_first_gas=args.capture_from_first_gas,
        one_tick_config=one_tick_config,
        skip_frida_bootstrap=bool(args.prepare_gta_import or launcher),
        processwheel_source_window=(
            tuple(args.frida_processwheel_source_window)
            if args.frida_processwheel_source_window else None
        ),
        paired_processsuspension=bool(args.frida_processwheel_with_processsuspension),
        processcollision_source_window=(
            tuple(args.frida_processcollision_source_window)
            if args.frida_processcollision_source_window else None
        ),
        processsuspension_source_window=(
            tuple(args.frida_processsuspension_source_window)
            if args.frida_processsuspension_source_window else None
        ),
        writer_diagnostics=not args.frida_processwheel_no_writer_diagnostics,
        transmission_diagnostics=not args.frida_processwheel_no_transmission_diagnostics,
        state_writer_source_window=(
            tuple(args.frida_state_writer_source_window)
            if args.frida_state_writer_source_window else None
        ),
        capture_untagged_state_writers=bool(args.frida_state_writer_capture_untagged),
        source_tag_order_diagnostics=bool(args.frida_source_tag_order_diagnostics),
    )
    if args.orchestrator and not (args.cpp_hook or args.timing_only):
        if not args.orchestrator.exists():
            parser.error(f"orchestrator does not exist: {args.orchestrator}")
        spec = importlib.util.spec_from_file_location("mta_native_bootstrap", args.orchestrator)
        if spec is None or spec.loader is None:
            parser.error(f"could not load orchestrator: {args.orchestrator}")
        bootstrap_module = importlib.util.module_from_spec(spec)
        sys.modules["mta_native_bootstrap"] = bootstrap_module
        spec.loader.exec_module(bootstrap_module)
        marker = (
            "if (INSTALL_NATIVE_WHEEL_HOOK || INSTALL_COLLISION_DIAGNOSTICS\n"
            "    || INSTALL_PAIRED_SUSPENSION\n"
            "    || INSTALL_SOURCE_TAG_ORDER_DIAGNOSTICS\n"
            "    || Array.isArray(PROCESSWHEEL_SOURCE_WINDOW)\n"
            "    || Array.isArray(PROCESSSUSPENSION_SOURCE_WINDOW)\n"
            "    || Array.isArray(STATE_WRITER_SOURCE_WINDOW)) {"
        )
        native_only = (
            "const OUTPUT_LABEL = " + json.dumps(args.label) + ";\n"
            "const INSTALL_NATIVE_WHEEL_HOOK = "
            + str(not args.suspension_stage_only).lower() + ";\n"
            "const INSTALL_COLLISION_DIAGNOSTICS = "
            + str(args.collision_diagnostics).lower()
            + ";\n"
            "const INSTALL_PAIRED_SUSPENSION = "
            + str(args.frida_processwheel_with_processsuspension).lower()
            + ";\n"
            "const INSTALL_SOURCE_TAG_ORDER_DIAGNOSTICS = "
            + str(args.frida_source_tag_order_diagnostics).lower()
            + ";\n"
            "const SUSPENSION_STAGE_ONLY = "
            + str(args.suspension_stage_only).lower()
            + ";\n"
            "const STAGE_FORCE_DIAGNOSTICS = "
            + str(args.stage_force_diagnostics).lower()
            + ";\n"
            "const STAGE_FORCE_EVENTS = "
            + str(args.stage_force_events).lower()
            + ";\n"
            "const STAGE_FORCE_SOURCE_WINDOW = "
            + json.dumps(
                list(args.stage_force_source_window)
                if args.stage_force_source_window else None
            )
            + ";\n"
            "const INSTALL_STATIC_SKID_DIAGNOSTICS = "
            + str(args.static_skid_diagnostics).lower()
            + ";\n"
            "const CAPTURE_FROM_FIRST_GAS = "
            + str(args.capture_from_first_gas).lower()
            + ";\n"
            "const PROCESSWHEEL_SOURCE_WINDOW = "
            + json.dumps(
                list(args.frida_processwheel_source_window)
                if args.frida_processwheel_source_window else None
            )
            + ";\n"
            "const PROCESSCOLLISION_SOURCE_WINDOW = "
            + json.dumps(
                list(args.frida_processcollision_source_window)
                if args.frida_processcollision_source_window else None
            )
            + ";\n"
            "const PROCESSSUSPENSION_SOURCE_WINDOW = "
            + json.dumps(
                list(args.frida_processsuspension_source_window)
                if args.frida_processsuspension_source_window else None
            )
            + ";\n"
            "const STATE_WRITER_SOURCE_WINDOW = "
            + json.dumps(
                list(args.frida_state_writer_source_window)
                if args.frida_state_writer_source_window else None
            )
            + ";\n"
            "const CAPTURE_UNTAGGED_STATE_WRITERS = "
            + str(args.frida_state_writer_capture_untagged).lower()
            + ";\n"
            "const INSTALL_STATE_WRITER_DIAGNOSTICS = "
            + str(not args.frida_processwheel_no_writer_diagnostics).lower()
            + ";\n"
            "const INSTALL_TRANSMISSION_DIAGNOSTICS = "
            + str(not args.frida_processwheel_no_transmission_diagnostics).lower()
            + ";\n"
            "const ONE_TICK_CONFIG = "
            + json.dumps(one_tick_config or {}, separators=(",", ":"))
            + ";\n"
            + native_script[native_script.index(marker):]
        )
        native_script = bootstrap_module.build_frida_script(args.label) + "\n" + native_only
    elif args.cpp_hook or args.timing_only or one_tick_config is not None:
        # The optional orchestrator's larger bootstrap payload is useful for
        # the Frida wheel route, but it can stall the client before the TAS
        # resource starts when combined with the lower-overhead C++ hook.  The
        # self-contained bootstrap above is sufficient for these routes.
        native_script += "\n" + _timing_probe_script()
    script = session.create_script(native_script)
    script.on("message", on_message)
    script.load()
    if spawned_suspended:
        assert pid is not None
        device.resume(pid)

    def restore_with_retry(action: Any) -> None:
        last_error: OSError | None = None
        for _ in range(40):
            try:
                action()
                return
            except PermissionError as exc:
                last_error = exc
                time.sleep(0.25)
        if last_error is not None:
            raise last_error

    try:
        if args.reference_map_resource and server_joined is not None:
            # In actual-race mode, startup can be delayed by the local loader
            # and the client must not lose the entire playback budget while it
            # is still joining.  ``--duration`` is therefore the post-join
            # retention budget; an absent JOIN still fails explicitly after a
            # bounded startup wait instead of silently producing a short run.
            startup_timeout = max(60.0, float(args.duration))
            deadline = time.monotonic() + startup_timeout
            while not server_joined.wait(0.25):
                if time.monotonic() >= deadline:
                    print(
                        "[capture] actual-race client did not join before the "
                        f"{startup_timeout:.1f}s startup timeout; rejecting capture"
                    )
                    break
            else:
                time.sleep(max(0.0, args.duration))
        else:
            time.sleep(max(0.0, args.duration))
    finally:
        reference_race_cancel.set()
        for timer in server_command_timers:
            timer.cancel()
        if reference_race_thread is not None:
            reference_race_thread.join(timeout=1.0)
        # Kill first: a Frida session with a busy callback queue can block
        # indefinitely while detaching from the debug client.
        if pid is not None:
            try:
                device.kill(pid)
            except Exception:
                pass
        try:
            session.detach()
        except Exception:
            pass
        if launcher_process is not None and launcher_process.poll() is None:
            try:
                launcher_process.terminate()
                launcher_process.wait(timeout=10)
            except Exception:
                try:
                    launcher_process.kill()
                except Exception:
                    pass
        # Frida's kill/detach can return before Windows closes the image
        # mappings.  Wait before restoring executable/DLL bytes.
        try:
            process = psutil.Process(int(pid))
            for _ in range(80):
                if not process.is_running():
                    break
                time.sleep(0.25)
        except (psutil.Error, TypeError, ValueError):
            time.sleep(1.0)
        if server is not None and server.poll() is None:
            try:
                if server.stdin is not None:
                    server.stdin.write("shutdown\r\n")
                    server.stdin.flush()
                server.wait(timeout=10)
            except Exception:
                server.kill()
        try:
            restore_with_retry(restore_vorbis)
        finally:
            restore_with_retry(restore_actual_race)
            restore_with_retry(restore_tas_folder)
            restore_with_retry(restore_pose_linear_only)
            restore_with_retry(restore_pose_only)
            restore_with_retry(restore_playback_pre_render)
            restore_with_retry(restore_playback_load_settle)
            restore_with_retry(restore_controls_only)
            restore_with_retry(restore_one_tick)
            restore_with_retry(restore_capture_output)
            restore_with_retry(restore_tas_automation)
            restore_with_retry(restore_capture_start_delay)
            restore_with_retry(restore_gta_import)
            restore_with_retry(restore_registry)
            if args.cpp_hook:
                os.environ.pop("MTA_NATIVE_PROCESSWHEEL_CPP_OUTPUT", None)
                os.environ.pop("MTA_NATIVE_PROCESSWHEEL_CPP_MINIMAL", None)
                os.environ.pop("MTA_NATIVE_PROCESSWHEEL_CPP_NO_MATRIX", None)
                os.environ.pop("MTA_NATIVE_PROCESSWHEEL_CPP_STATIC_LATCH", None)
                os.environ.pop("MTA_NATIVE_PROCESSCONTROL_CPP_OUTPUT", None)
                os.environ.pop("MTA_NATIVE_PROCESSCONTROL_CPP_START_FRAME", None)
                os.environ.pop("MTA_NATIVE_PROCESSCONTROL_CPP_END_FRAME", None)
                os.environ.pop("MTA_NATIVE_PROCESSSUSPENSION_CPP_OUTPUT", None)
                os.environ.pop("MTA_NATIVE_PROCESSSUSPENSION_CPP_START_FRAME", None)
                os.environ.pop("MTA_NATIVE_PROCESSSUSPENSION_CPP_END_FRAME", None)
                if previous_processcontrol_output is not None:
                    os.environ["MTA_NATIVE_PROCESSCONTROL_CPP_OUTPUT"] = previous_processcontrol_output
                if previous_processcontrol_start is not None:
                    os.environ["MTA_NATIVE_PROCESSCONTROL_CPP_START_FRAME"] = previous_processcontrol_start
                if previous_processcontrol_end is not None:
                    os.environ["MTA_NATIVE_PROCESSCONTROL_CPP_END_FRAME"] = previous_processcontrol_end
                if previous_processsuspension_output is not None:
                    os.environ["MTA_NATIVE_PROCESSSUSPENSION_CPP_OUTPUT"] = previous_processsuspension_output
                if previous_processsuspension_start is not None:
                    os.environ["MTA_NATIVE_PROCESSSUSPENSION_CPP_START_FRAME"] = previous_processsuspension_start
                if previous_processsuspension_end is not None:
                    os.environ["MTA_NATIVE_PROCESSSUSPENSION_CPP_END_FRAME"] = previous_processsuspension_end
                os.environ.pop("MTA_NATIVE_COLLISION_ALT_CPP_OUTPUT", None)
                if previous_collision_flush_every is None:
                    os.environ.pop("MTA_NATIVE_COLLISION_ALT_CPP_FLUSH_EVERY", None)
                else:
                    os.environ["MTA_NATIVE_COLLISION_ALT_CPP_FLUSH_EVERY"] = previous_collision_flush_every
            os.environ.pop("MTA_NATIVE_CAPTURE_AUTOCONNECT", None)
            if previous_mta_bin is None:
                os.environ.pop("MTA_BIN", None)
            else:
                os.environ["MTA_BIN"] = previous_mta_bin
            if previous_capture_diagnostics is None:
                os.environ.pop("MTA_NATIVE_CAPTURE_DIAGNOSTICS", None)
            else:
                os.environ["MTA_NATIVE_CAPTURE_DIAGNOSTICS"] = previous_capture_diagnostics
    print(f"native capture written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
