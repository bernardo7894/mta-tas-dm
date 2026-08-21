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

if (INSTALL_NATIVE_WHEEL_HOOK) {{
(function installNativeWheelHook() {{
    const main = Process.mainModule;
    const processWheel = main.base.add({PROCESS_WHEEL_RVA});
    const processControl = main.base.add({PROCESS_CONTROL_RVA});
    const processControlCollisionCheck = main.base.add(0x2A29C0);
    const processCollision = main.base.add(0x14DFB0);
    const checkCollision = main.base.add(0x14D920);
    const applyForce = main.base.add(0x142B50);
    const applyTurnForce = main.base.add(0x142A50);
    const applyCollisionAlt = main.base.add(0x144D50);
    const gameFrameCounter = main.base.add(0x77CB4C);
    const gameTimeMs = main.base.add(0x77CB84);
    let frame = 0, processCalls = 0, wheelCalls = 0, batch = [];
    const controlStates = new Map();
    const pendingCollisions = new Map();
    const f = p => {{ try {{ return p.readFloat(); }} catch(_) {{ return null; }} }};
    const u8 = p => {{ try {{ return p.readU8(); }} catch(_) {{ return null; }} }};
    const s32 = p => {{ try {{ return p.readS32(); }} catch(_) {{ return null; }} }};
    const vec = p => {{ try {{ return [p.readFloat(),p.add(4).readFloat(),p.add(8).readFloat()]; }} catch(_) {{ return null; }} }};
    const array4 = p => [0,1,2,3].map(i => f(p.add(i * 4)));
    const dot = (a,b) => a && b ? a[0]*b[0]+a[1]*b[1]+a[2]*b[2] : null;
    const delta = (a,b) => a && b ? a.map((v,i) => v-b[i]) : null;
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
    function flush() {{ if (batch.length) {{ send({{type:'native_batch', label:OUTPUT_LABEL, records:batch}}); batch=[]; }} }}
    try {{
        Interceptor.attach(processControl, {{
            onEnter() {{
                const vehicle = this.context.ecx;
                try {{
                    if (vehicle.add(0x22).readU16() === 411) {{
                        frame++; processCalls++;
                        const key = vehicle.toString();
                        controlStates.set(key, {{
                            gameFrame:(()=>{{try{{return gameFrameCounter.readU32()}}catch(_){{return null}}}})(),
                            gameTimeMs:(()=>{{try{{return gameTimeMs.readU32()}}catch(_){{return null}}}})(),
                            linearVelocity:vec(vehicle.add(0x44)),
                            angularVelocity:vec(vehicle.add(0x50)),
                            frictionMoveVelocity:vec(vehicle.add(0x5C)),
                            frictionAngularVelocity:vec(vehicle.add(0x68)),
                            vtable:(()=>{{try{{return vehicle.readPointer().toString()}}catch(_){{return null}}}})(),
                            vtableCollisionCheck:(()=>{{try{{return vehicle.readPointer().add(0x5C).readPointer().toString()}}catch(_){{return null}}}})(),
                            vehicleFlagsByte3:u8(vehicle.add(0x42B)),
                            audioChangingGear:((u8(vehicle.add(0x42B)) || 0) & 0x20) !== 0,
                            collisionProcess:pendingCollisions.get(key) || null,
                            applyForces:[],
                            applyTurnForces:[],
                            collisionAlternates:[],
                        }});
                        pendingCollisions.delete(key);
                        this.nativeControlKey = key;
                    }}
                }} catch(_) {{}}
            }},
        }});
        if (INSTALL_COLLISION_DIAGNOSTICS) {{
        Interceptor.attach(processCollision, {{
            onEnter() {{
                const vehicle = this.context.ecx;
                try {{
                    if (vehicle.add(0x22).readU16() !== 411) return;
                    this.nativeCollisionKey = vehicle.toString();
                    this.nativeCollisionVehicle = vehicle;
                    this.nativeCollisionBefore = physicalSnapshot(vehicle);
                }} catch(_) {{}}
            }},
            onLeave() {{
                if (!this.nativeCollisionKey) return;
                try {{
                    const after = physicalSnapshot(this.nativeCollisionVehicle);
                    if (snapshotChanged(this.nativeCollisionBefore, after))
                        pendingCollisions.set(this.nativeCollisionKey, {{
                            before:this.nativeCollisionBefore,
                            after:after,
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
                }} catch(_) {{}}
            }},
            onLeave() {{
                if (!this.nativeForceKey) return;
                try {{
                    const control = controlStates.get(this.nativeForceKey);
                    const after = physicalSnapshot(this.nativeForceVehicle);
                    if (control && snapshotChanged(this.nativeForceBefore, after))
                        control.applyForces.push({{
                            force:this.nativeForceVector,
                            point:this.nativeForcePoint,
                            before:this.nativeForceBefore,
                            after:after,
                        }});
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
                    mass:f(vehicle.add(0x8C)), turnMass:f(vehicle.add(0x90)), centerOfMass:vec(vehicle.add(0xA4)),
                    controlEntry:(()=>{{const c=controlStates.get(vehicle.toString());return c ? {{gameFrame:c.gameFrame,gameTimeMs:c.gameTimeMs,linearVelocity:c.linearVelocity,angularVelocity:c.angularVelocity,frictionMoveVelocity:c.frictionMoveVelocity,frictionAngularVelocity:c.frictionAngularVelocity,vtable:c.vtable,vtableCollisionCheck:c.vtableCollisionCheck,vehicleFlagsByte3:c.vehicleFlagsByte3,audioChangingGear:c.audioChangingGear,collisionProcess:c.collisionProcess,collisionCheck:c.collisionCheck,collisionCheckInner:c.collisionCheckInner,applyForces:c.applyForces,applyTurnForces:c.applyTurnForces,collisionAlternates:c.collisionAlternates}} : null;}})(),
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
}}
"""


def _timing_probe_script() -> str:
    return """
(function installNativeTimingProbe() {
    const main = Process.mainModule;
    const gameFrame = main.base.add(0x77CB4C);
    const gameTimeMs = main.base.add(0x77CB84);
    setInterval(function() {
        try {
            send({type:'native_timing', wallMs:Date.now(), gameFrame:gameFrame.readU32(), gameTimeMs:gameTimeMs.readU32()});
        } catch (_) {}
    }, 1000);
})();
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
        return lambda: None
    original = client.read_bytes()
    markers = (
        (b"useOnlyBinds = false", b"useOnlyBinds = true"),
        (b"playbackInterpolation = true", b"playbackInterpolation = false"),
    )
    patched = original
    for old, new in markers:
        if old not in patched:
            return lambda: None
        patched = patched.replace(old, new, 1)
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


def _prepare_real_vorbis(mta_bin: Path) -> Any:
    """Temporarily disable the loader proxy so Frida owns MTA bootstrap."""
    original = mta_bin / "vorbisfile.dll"
    real = mta_bin / "vorbisfile_real.dll"
    backup = mta_bin / "vorbisfile.native-capture-original.dll"
    if not original.exists() or not real.exists() or original.read_bytes() == real.read_bytes():
        return lambda: None
    if not backup.exists():
        backup.write_bytes(original.read_bytes())
    original.write_bytes(real.read_bytes())

    def restore() -> None:
        if backup.exists():
            original.write_bytes(backup.read_bytes())

    return restore


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
    parser.add_argument("--duration", type=float, default=240.0)
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
        "--playback-output-name",
        help="temporarily select this Lua physics-output name in the local native_capture resource",
    )
    args = parser.parse_args()
    if args.cpp_minimal or args.cpp_no_matrix:
        args.cpp_hook = True
    playback_modes = sum(
        bool(value) for value in (
            args.controls_only_playback,
            args.pose_only_playback,
            args.pose_linear_only_playback,
        )
    )
    if playback_modes > 1:
        parser.error("playback-only diagnostic modes are mutually exclusive")
    if args.cpp_minimal and args.cpp_no_matrix:
        parser.error("--cpp-minimal and --cpp-no-matrix are mutually exclusive")
    if args.cpp_hook and args.timing_only:
        parser.error("--cpp-hook and --timing-only are mutually exclusive")
    if args.playback_output_name and not args.playback_output_name.replace("-", "").replace("_", "").isalnum():
        parser.error("--playback-output-name may contain only letters, numbers, '-' and '_'")
    _kill_targets()
    mta_bin = args.mta_bin.resolve()
    cpp_binary = args.output.with_suffix(args.output.suffix + ".cpp.bin")
    cpp_collision_binary = args.output.with_suffix(args.output.suffix + ".collision.bin")
    timing_output = args.output.with_suffix(args.output.suffix + ".timing.jsonl")
    if args.cpp_hook or args.timing_only:
        timing_output.parent.mkdir(parents=True, exist_ok=True)
        if timing_output.exists():
            timing_output.unlink()
    if args.cpp_hook:
        cpp_binary.parent.mkdir(parents=True, exist_ok=True)
        if cpp_binary.exists():
            cpp_binary.unlink()
        os.environ["MTA_NATIVE_PROCESSWHEEL_CPP_OUTPUT"] = str(cpp_binary.resolve())
        if args.cpp_minimal:
            os.environ["MTA_NATIVE_PROCESSWHEEL_CPP_MINIMAL"] = "1"
        if args.cpp_no_matrix:
            os.environ["MTA_NATIVE_PROCESSWHEEL_CPP_NO_MATRIX"] = "1"
        if args.collision_diagnostics:
            if cpp_collision_binary.exists():
                cpp_collision_binary.unlink()
            os.environ["MTA_NATIVE_COLLISION_ALT_CPP_OUTPUT"] = str(cpp_collision_binary.resolve())
    os.environ["MTA_BIN"] = str(mta_bin)
    restore_registry = _prepare_registry(mta_bin) if args.prepare_registry else (lambda: None)
    restore_tas_folder = _prepare_public_tas_folder(mta_bin) if args.prepare_tas_folder else (lambda: None)
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
    restore_capture_output = (
        _prepare_native_capture_output(mta_bin, args.playback_output_name)
        if args.playback_output_name else (lambda: None)
    )
    restore_vorbis = _prepare_real_vorbis(mta_bin) if args.use_real_vorbis else (lambda: None)
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
        "process_wheel_rva": hex(PROCESS_WHEEL_RVA),
        "direct_observable": "CVehicle::ProcessWheel entry arguments and vehicle state",
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
        "cpp_binary": str(cpp_binary.resolve()) if args.cpp_hook else "",
        "cpp_collision_binary": (
            str(cpp_collision_binary.resolve())
            if args.cpp_hook and args.collision_diagnostics else ""
        ),
        "timing_samples": str(timing_output.resolve()) if args.cpp_hook or args.timing_only else "",
        "collision_diagnostics": bool(args.collision_diagnostics),
        "cpp_capture_level": (
            "minimal" if args.cpp_minimal
            else "no-matrix" if args.cpp_no_matrix
            else "full" if args.cpp_hook else "none"
        ),
        "prepare_tas_folder": bool(args.prepare_tas_folder),
        "controls_only_playback": bool(args.controls_only_playback),
        "pose_only_playback": bool(args.pose_only_playback),
        "pose_linear_only_playback": bool(args.pose_linear_only_playback),
        "playback_output_name": args.playback_output_name or "",
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
        elif kind == "native_timing":
            if args.cpp_hook or args.timing_only:
                with timing_output.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(payload, separators=(",", ":")) + "\n")
            print(f"[timing] wallMs={payload.get('wallMs')} gameTimeMs={payload.get('gameTimeMs')} gameFrame={payload.get('gameFrame')}")

    native_script = _native_script(
        args.mta_bin.resolve(), args.label,
        install_wheel_hook=not (args.cpp_hook or args.timing_only),
        collision_diagnostics=args.collision_diagnostics,
    )
    if args.orchestrator:
        if not args.orchestrator.exists():
            parser.error(f"orchestrator does not exist: {args.orchestrator}")
        spec = importlib.util.spec_from_file_location("mta_native_bootstrap", args.orchestrator)
        if spec is None or spec.loader is None:
            parser.error(f"could not load orchestrator: {args.orchestrator}")
        bootstrap_module = importlib.util.module_from_spec(spec)
        sys.modules["mta_native_bootstrap"] = bootstrap_module
        spec.loader.exec_module(bootstrap_module)
        if args.cpp_hook or args.timing_only:
            native_script = bootstrap_module.build_frida_script(args.label) + "\n"
            native_script += _timing_probe_script()
        else:
            marker = "if (INSTALL_NATIVE_WHEEL_HOOK) {"
            native_only = (
                "const OUTPUT_LABEL = " + json.dumps(args.label) + ";\n"
                "const INSTALL_NATIVE_WHEEL_HOOK = true;\n"
                "const INSTALL_COLLISION_DIAGNOSTICS = "
                + str(args.collision_diagnostics).lower()
                + ";\n"
                + native_script[native_script.index(marker):]
            )
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
        try:
            restore_vorbis()
        finally:
            restore_tas_folder()
            restore_pose_linear_only()
            restore_pose_only()
            restore_controls_only()
            restore_capture_output()
            restore_registry()
            if args.cpp_hook:
                os.environ.pop("MTA_NATIVE_PROCESSWHEEL_CPP_OUTPUT", None)
                os.environ.pop("MTA_NATIVE_PROCESSWHEEL_CPP_MINIMAL", None)
                os.environ.pop("MTA_NATIVE_PROCESSWHEEL_CPP_NO_MATRIX", None)
                os.environ.pop("MTA_NATIVE_COLLISION_ALT_CPP_OUTPUT", None)
    print(f"native capture written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
