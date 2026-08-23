from __future__ import annotations

import importlib.util
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "tools" / "native_processwheel_capture.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("native_processwheel_capture", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_one_tick_resource_prep_handles_crlf_and_delay(tmp_path):
    tool = _load_tool()
    resource = (
        tmp_path / "server" / "mods" / "deathmatch" / "resources" / "native_capture"
    )
    resource.mkdir(parents=True)
    server = (
        'local vehicle = nil\r\n'
        'local function startPlayer(player)\r\n'
        '    triggerClientEvent(player, "nativeCapture:start", resourceRoot, "etnies-native", "native-etnies")\r\n'
        'end\r\n'
    )
    client = 'addEvent("nativeCapture:start", true)\r\n'
    (resource / "server.lua").write_bytes(server.encode())
    (resource / "client.lua").write_bytes(client.encode())

    restore = tool._prepare_one_tick_resource(
        tmp_path,
        {"position": [1, 2, 3], "nativeInternal": {}, "oneTickDelayMs": 30000},
    )
    prepared = (resource / "server.lua").read_bytes().decode()
    assert 'nativeCapture:oneTick' in prepared
    assert "end, 30000, 1)" in prepared
    assert "\r\n" in prepared

    restore()
    assert (resource / "server.lua").read_bytes().decode() == server
    assert (resource / "client.lua").read_bytes().decode() == client


def test_one_tick_resource_prep_accepts_current_source_tag_trigger(tmp_path):
    tool = _load_tool()
    resource = tmp_path / "server" / "mods" / "deathmatch" / "resources" / "native_capture"
    resource.mkdir(parents=True)
    server = (
        'local function startPlayer(player)\n'
        '    triggerClientEvent(player, "nativeCapture:start", resourceRoot, "etnies-native", "source-tag-smoke")\n'
        'end\n'
    )
    client = "addEvent(\"nativeCapture:oneTick\", true)\n"
    (resource / "server.lua").write_text(server, encoding="utf-8")
    (resource / "client.lua").write_text(client, encoding="utf-8")
    restore = tool._prepare_one_tick_resource(
        tmp_path, {"position": [1, 2, 3], "nativeInternal": {}, "oneTickDelayMs": 30000}
    )
    prepared = (resource / "server.lua").read_text(encoding="utf-8")
    assert "nativeCapture:oneTick" in prepared
    assert "end, 30000, 1)" in prepared
    restore()
    assert (resource / "server.lua").read_text(encoding="utf-8") == server


def test_playback_load_settle_prep_is_reversible(tmp_path):
    tool = _load_tool()
    resource = tmp_path / "server" / "mods" / "deathmatch" / "resources" / "tas"
    resource.mkdir(parents=True)
    client = resource / "client.lua"
    original = (
        b"\ttas.var.automation.playbackTimer = setTimer(tas.automation_start_playback, 250, 1)\n"
    )
    client.write_bytes(original)
    restore = tool._prepare_playback_load_settle(tmp_path, 5000)
    assert b"automation_start_playback, 5000, 1" in client.read_bytes()
    restore()
    assert client.read_bytes() == original


def test_playback_pre_render_prep_is_reversible(tmp_path):
    tool = _load_tool()
    resource = (
        tmp_path / "server" / "mods" / "deathmatch" / "resources" / "tas"
    )
    resource.mkdir(parents=True)
    client = resource / "client.lua"
    original = b"playbackPreRender = false\n"
    client.write_bytes(original)
    restore = tool._prepare_playback_pre_render(tmp_path)
    assert client.read_bytes() == b"playbackPreRender = true\n"
    restore()
    assert client.read_bytes() == original


def test_controls_only_and_prerender_overrides_survive_user_config(tmp_path):
    tool = _load_tool()
    resource = tmp_path / "server" / "mods" / "deathmatch" / "resources" / "tas"
    resource.mkdir(parents=True)
    original = (
        b"useOnlyBinds = false\n"
        b"playbackInterpolation = true\n"
        b"playbackPreRender = false\n"
        b"if not tas.settings.useOnlyBinds then\n"
        b"if not tas.settings.useOnlyBinds then\n"
        b"\tlocal cachedWarpsLoaded = false\n"
    )
    client = resource / "client.lua"
    client.write_bytes(original)
    restore_controls = tool._prepare_controls_only_playback(tmp_path)
    prepared = client.read_bytes()
    assert b"tas.settings.useOnlyBinds = true" in prepared
    assert b"tas.settings.playbackInterpolation = false" in prepared
    assert b"if false then -- native-capture controls-only state writes disabled" in prepared
    restore_pre_render = tool._prepare_playback_pre_render(tmp_path)
    prepared = client.read_bytes()
    assert b"tas.settings.playbackPreRender = true" in prepared
    restore_pre_render()
    restore_controls()
    assert client.read_bytes() == original


def test_controls_only_accepts_already_disabled_interpolation_default(tmp_path):
    tool = _load_tool()
    resource = tmp_path / "server" / "mods" / "deathmatch" / "resources" / "tas"
    resource.mkdir(parents=True)
    client = resource / "client.lua"
    original = (
        b"useOnlyBinds = false\n"
        b"playbackInterpolation = false\n"
        b"if not tas.settings.useOnlyBinds then\n"
        b"if not tas.settings.useOnlyBinds then\n"
        b"\tlocal cachedWarpsLoaded = false\n"
    )
    client.write_bytes(original)
    restore = tool._prepare_controls_only_playback(tmp_path)
    prepared = client.read_bytes()
    assert b"tas.settings.useOnlyBinds = true" in prepared
    assert b"native-capture controls-only state writes disabled" in prepared
    restore()
    assert client.read_bytes() == original


def test_controls_only_recovers_already_controls_only_deployment(tmp_path):
    tool = _load_tool()
    resource = tmp_path / "server" / "mods" / "deathmatch" / "resources" / "tas"
    resource.mkdir(parents=True)
    client = resource / "client.lua"
    original = (
        b"useOnlyBinds = true\n"
        b"playbackInterpolation = false\n"
        b"if not tas.settings.useOnlyBinds then\n"
        b"if not tas.settings.useOnlyBinds then\n"
        b"\tlocal cachedWarpsLoaded = false\n"
    )
    client.write_bytes(original)
    restore = tool._prepare_controls_only_playback(tmp_path)
    assert b"native-capture controls-only state writes disabled" in client.read_bytes()
    restore()
    assert client.read_bytes() == original


def test_restore_order_reverses_overlapping_tas_preparations():
    source = TOOL.read_text(encoding="utf-8")
    cleanup = source[source.index("        try:\n            restore_with_retry(restore_vorbis)"):]
    assert cleanup.index("restore_playback_pre_render") < cleanup.index("restore_controls_only")
    assert cleanup.index("restore_controls_only") < cleanup.index("restore_tas_folder")


def test_actual_race_duration_guard_preserves_full_playback():
    source = TOOL.read_text(encoding="utf-8")
    assert "17781.0 / 99.0" in source
    assert "requires --duration" in source


def test_client_receives_connection_uri_without_debug_core_autoconnect():
    source = TOOL.read_text(encoding="utf-8")
    assert 'default="mtasa://127.0.0.1:22003"' in source
    assert 'argv=[str(gta), args.connect_uri]' in source
    assert '"connect_uri": args.connect_uri' in source


def test_normal_launcher_child_attach_mode_is_separate_from_direct_bootstrap():
    source = TOOL.read_text(encoding="utf-8")
    assert '"--launcher-exe"' in source
    assert 'normal MTA launcher did not create a new GTA child process' in source
    assert '_is_gta_process_name(process.name)' in source
    assert 'candidates.sort(key=create_time, reverse=True)' in source
    assert 'GTA candidates after JOIN' in source
    assert 'skip_frida_bootstrap=bool(args.prepare_gta_import or launcher)' in source
    assert 'launcher_process.terminate()' in source


def test_launcher_cleanup_and_attach_include_debug_gta_child_name():
    tool = _load_tool()
    assert tool._is_gta_process_name("gta_sa.exe")
    assert tool._is_gta_process_name("gta_sa_d.exe")
    assert tool._is_gta_process_name("gta-sa_d.exe")
    assert not tool._is_gta_process_name("gta_sa_helper.exe")


def test_actual_race_map_start_waits_for_client_join():
    source = TOOL.read_text(encoding="utf-8")
    assert "server_joined.wait(0.25)" in source
    assert "start_reference_race_after_join" in source
    assert "after_server_join_start_race_then_map" in source
    assert '(25.0, "start race")' not in source
    assert 'post_join_retention_budget' in source
    assert 'actual-race client did not join' in source


def test_loader_mode_disables_mixed_frida_bootstrap():
    tool = _load_tool()
    script = tool._native_script(Path("C:/mta"), "loader", skip_frida_bootstrap=True)
    assert "if (!true)" in script
    assert "if (!skip_frida_bootstrap)" not in script


def test_one_tick_wheel_state_offset_is_after_gas_audio_field():
    source = TOOL.read_text(encoding="utf-8")
    assert "writeU32Array(0x968, internal.wheelStates)" in source
    assert "u32Array4(vehicle.add(0x968))" in source


def test_one_tick_stable_timer_filter_and_state_hold_are_supported():
    source = TOOL.read_text(encoding="utf-8")
    assert "requireStableTimerStep" in source
    assert "oneTickWarmHoldMs" in source
    assert "one_tick_config is not None" in source
    assert "native_timer_step" in source or "timerStep" in source


def test_controls_only_playback_preserves_live_kinematic_extension():
    source = (TOOL.parents[1] / "new" / "tas" / "client.lua").read_text(encoding="utf-8")
    assert "frame_data.x.livePosition = live_p" in source
    assert "frame_data.x.liveVelocity = live_v" in source
    assert "frame_data.x.liveAngularVelocity = live_rv" in source
    assert "liveVelocity = extra.liveVelocity" in source
    assert "liveAngularVelocity = extra.liveAngularVelocity" in source
    assert "serialized TAS p/v/rv fields" in source


def test_source_tag_is_written_after_controls_are_applied():
    source = (TOOL.parents[1] / "new" / "tas" / "client.lua").read_text(encoding="utf-8")
    capture_tool = TOOL.read_text(encoding="utf-8")
    assert "after-control-write-render-callback" in capture_tool
    tag = source.index("setNativeProcessWheelSourceTag(tas.var.play_frame, frame_data.tick)")
    controls = source.index("tas.resetBinds()", tag - 6000)
    nitro = source.index("tas.nos(vehicle, frame_data.n)", controls)
    capture = source.index("tas.capture_playback_frame(vehicle, frame_data, deltaTime)", tag)
    assert controls < nitro < tag < capture
    assert "after all controls" in source[tag - 400:tag]


def test_frida_processwheel_can_pair_lightweight_processsuspension():
    tool = _load_tool()
    script = tool._native_script(
        Path("C:/mta"),
        "paired-startup",
        processwheel_source_window=(1, 3),
        paired_processsuspension=True,
        writer_diagnostics=False,
        transmission_diagnostics=False,
    )
    assert "const INSTALL_PAIRED_SUSPENSION = true;" in script
    assert "source:'gta-native-paired-process-suspension'" in script
    assert "if (INSTALL_PAIRED_SUSPENSION && !INSTALL_COLLISION_DIAGNOSTICS)" in script
    assert "sourceFrameTagEntry:this.nativePairedSuspensionTag.frame" in script
    assert "physicalBefore:this.nativePairedSuspensionPhysicalBefore" in script


def test_frida_angular_state_writer_diagnostic_is_bounded_and_read_only():
    tool = _load_tool()
    script = tool._native_script(
        Path("C:/mta"),
        "angular-writer-window",
        install_wheel_hook=False,
        state_writer_source_window=(1, 3),
        capture_untagged_state_writers=True,
        writer_diagnostics=True,
        transmission_diagnostics=False,
    )
    assert "const STATE_WRITER_SOURCE_WINDOW = [1, 3];" in script
    assert "const CAPTURE_UNTAGGED_STATE_WRITERS = true;" in script
    assert "staticSetElementAngularVelocityRva = 0x7AE0B0" in script
    assert "source:'gta-native-set-element-angular-velocity'" in script
    assert "sourceTagWasPublished" in script
    assert "callerModule" in script
    assert "callerSymbol" in script
    assert "callerBacktrace" in script
    assert "gta-native-set-element-velocity-public-initializer" in script
    assert "clientEntityNative411Candidates" in script
    assert "offset = -0x2000" in script
    assert "offset <= 0x3000" in script
    assert "SetElementAngularVelocity signature mismatch" in script
    assert "turnVelocityPtr = this.context.esp.add(8).readPointer()" in script


def test_frida_processwheel_source_window_limits_rows_without_disabling_hook():
    tool = _load_tool()
    script = tool._native_script(
        Path("C:/mta"),
        "wheel-window",
        processwheel_source_window=(24, 100),
    )
    assert "const PROCESSWHEEL_SOURCE_WINDOW = [24, 100];" in script
    assert "sourceTag.frame < PROCESSWHEEL_SOURCE_WINDOW[0]" in script
    assert "sourceFrameTag:sourceTag.frame" in script
    assert "timerStep:f(timerStep)" in script
    assert "transmissionCalls:c.transmissionCalls" in script
    assert "const INSTALL_STATE_WRITER_DIAGNOSTICS = true;" in script
    assert "const INSTALL_TRANSMISSION_DIAGNOSTICS = true;" in script
    assert "CPhysicalSA::SetMoveSpeed" in script
    assert "CVehicleSA::SetMoveSpeed" in script
    assert "staticSetElementVelocityRva = 0x7B0010" in script
    assert "source:'gta-native-set-element-velocity'" in script
    assert "source:'gta-native-set-move-speed'" in script
    assert "if (INSTALL_NATIVE_WHEEL_HOOK)" in script


def test_native_setter_handoff_capture_is_bounded_and_explicitly_untagged():
    tool = _load_tool()
    script = tool._native_script(
        Path("C:/mta"),
        "native-setter-handoff",
        processwheel_source_window=(1, 3),
        state_writer_source_window=(1, 3),
        capture_untagged_state_writers=True,
        capture_untagged_native_setters_after_writer=True,
    )
    assert "const CAPTURE_UNTAGGED_NATIVE_SETTERS_AFTER_WRITER = true;" in script
    assert "postWriterUntaggedNativeSetterCalls < 16" in script
    assert "publicVelocityWriterObserved" in script
    assert "untagged-after-public-velocity-writer" in script
    assert "publicWriterClientEntity" in script
    assert "source:'untagged-after-public-angular-writer'" not in script
    assert "captureProvenance:untaggedNativeSetter" in script
    assert "nativeVehicle:this.context.ecx.toString()" in script
    assert "const nativeCandidates = clientEntityNative411Candidates(this.context.ecx);" in script
    assert "wrapperNative411Candidates:nativeCandidates" in script
    assert "nativePrivateStateSnapshot" in script
    assert "returnedWrapperNative411CandidateStates" in script
    assert "DebugSymbol.findFunctionsNamed('CPoolsSA::AddVehicle')" in script
    assert "DebugSymbol.findFunctionsNamed(name)" in script
    assert "source:'gta-native-set-turn-speed'" in script
    assert "nested-public-angular-writer" in script
    assert "publicAngularWriterInProgress" in script
    assert "source:'gta-native-pools-add-vehicle'" in script
    assert "source-CPoolsSA::AddVehicle" in script
    assert "enumerateSymbols" not in script


def test_frida_stage_source_window_limits_exact_stage_rows_and_keeps_named_setter_route():
    tool = _load_tool()
    script = tool._native_script(
        Path("C:/mta"),
        "turn-stage-startup",
        collision_diagnostics=True,
        suspension_stage_only=True,
        stage_source_window=(1, 3),
        state_writer_source_window=(1, 3),
        capture_untagged_state_writers=True,
        writer_diagnostics=True,
        transmission_diagnostics=False,
    )
    assert "const STAGE_SOURCE_WINDOW = [1, 3];" in script
    assert "stageSourceInWindow" in script
    assert "source:'gta-native-set-turn-speed'" in script
    assert "DebugSymbol.findFunctionsNamed(name)" in script


def test_frida_stage_can_omit_heavy_processcollision_observers():
    tool = _load_tool()
    script = tool._native_script(
        Path("C:/mta"),
        "turn-stage-startup-light",
        collision_diagnostics=False,
        suspension_stage_only=True,
        capture_stage_processcollision=False,
        stage_source_window=(1, 3),
        state_writer_source_window=(1, 3),
        capture_untagged_state_writers=True,
        writer_diagnostics=True,
        transmission_diagnostics=False,
    )
    assert "const CAPTURE_STAGE_PROCESSCOLLISION = false;" in script
    assert "if (SUSPENSION_STAGE_ONLY && CAPTURE_STAGE_PROCESSCOLLISION)" in script
    assert "SUSPENSION_STAGE_ONLY && CAPTURE_STAGE_PROCESSCOLLISION)\n            || Array.isArray(PROCESSCOLLISION_SOURCE_WINDOW)" in script


def test_frida_stage_can_capture_bounded_untagged_rows_after_public_writer():
    tool = _load_tool()
    script = tool._native_script(
        Path("C:/mta"),
        "turn-stage-startup-untagged",
        collision_diagnostics=False,
        suspension_stage_only=True,
        capture_stage_processcollision=False,
        capture_untagged_stage_after_writer=True,
        stage_source_window=(1, 3),
        state_writer_source_window=(1, 3),
        capture_untagged_state_writers=True,
        writer_diagnostics=True,
        transmission_diagnostics=False,
    )
    assert "const CAPTURE_UNTAGGED_STAGE_AFTER_WRITER = true;" in script
    assert "gta-native-process-stage-untagged-after-writer" in script
    assert "post-public-angular-writer-untagged-processcontrol" in script
    assert "untaggedStageAfterWriterCount < maxUntaggedStageAfterWriter" in script
    assert "suspensionAtProcessControlEntry:(INSTALL_COLLISION_DIAGNOSTICS" in script


def test_frida_processsuspension_source_window_adds_only_narrow_boundary():
    tool = _load_tool()
    script = tool._native_script(
        Path("C:/mta"),
        "suspension-window",
        processwheel_source_window=(20, 30),
        processsuspension_source_window=(20, 30),
        writer_diagnostics=False,
        transmission_diagnostics=False,
    )
    assert "const PROCESSSUSPENSION_SOURCE_WINDOW = [20, 30];" in script
    assert "source:'gta-native-process-suspension-boundary'" in script
    assert "nativeNarrowSuspensionBefore" in script
    assert "sourceFrameTagEntry:boundary.sourceFrameTagEntry" in script
    assert "sourceTag.frame < PROCESSSUSPENSION_SOURCE_WINDOW[0]" in script


def test_frida_processwheel_can_skip_writer_side_channel_hooks():
    tool = _load_tool()
    script = tool._native_script(
        Path("C:/mta"),
        "wheel-window-no-writers",
        processwheel_source_window=(20, 100),
        writer_diagnostics=False,
    )
    assert "const INSTALL_STATE_WRITER_DIAGNOSTICS = false;" in script
    assert "if (INSTALL_STATE_WRITER_DIAGNOSTICS" in script
    assert "Array.isArray(PROCESSWHEEL_SOURCE_WINDOW)" in script


def test_frida_processwheel_can_skip_transmission_boundary_hook():
    tool = _load_tool()
    script = tool._native_script(
        Path("C:/mta"),
        "wheel-window-no-transmission",
        processwheel_source_window=(20, 100),
        writer_diagnostics=False,
        transmission_diagnostics=False,
    )
    assert "const INSTALL_TRANSMISSION_DIAGNOSTICS = false;" in script
    assert "if (INSTALL_TRANSMISSION_DIAGNOSTICS)" in script


def test_untagged_post_writer_processwheel_window_is_bounded_and_paired():
    tool = _load_tool()
    script = tool._native_script(
        Path("C:/mta"),
        "post-writer-stack",
        processwheel_source_window=(1, 3),
        paired_processsuspension=True,
        state_writer_source_window=(1, 3),
        capture_untagged_state_writers=True,
        capture_untagged_processwheel_after_writer=True,
        writer_diagnostics=True,
        transmission_diagnostics=False,
    )
    assert "const CAPTURE_UNTAGGED_PROCESSWHEEL_AFTER_WRITER = true;" in script
    assert "allowPostWriterUntaggedWheel" in script
    assert "postWriterUntaggedWheelCalls < 4" in script
    assert "allowPostWriterUntaggedSuspension" in script
    assert "postWriterUntaggedSuspensionCaptured" in script
    assert "sourceTagInWheelWindow" in script


def test_source_tag_order_diagnostic_is_read_only_and_bounded():
    tool = _load_tool()
    script = tool._native_script(
        Path("C:/mta"),
        "tag-order",
        install_wheel_hook=False,
        collision_diagnostics=True,
        suspension_stage_only=True,
        source_tag_order_diagnostics=True,
    )
    assert "const INSTALL_SOURCE_TAG_ORDER_DIAGNOSTICS = true;" in script
    assert "SetNativeProcessWheelSourceTagBridge" in script
    assert "source:'gta-native-source-tag-bridge'" in script
    assert "native_source_tag_bridge_batch" in script
    assert "write" not in script[script.index("source:'gta-native-source-tag-bridge'"):script.index("source:'gta-native-source-tag-bridge'") + 600]


def test_suspension_stage_can_pair_public_angular_writer_diagnostic():
    tool = _load_tool()
    script = tool._native_script(
        Path("C:/mta"),
        "stage-writer",
        install_wheel_hook=False,
        collision_diagnostics=True,
        suspension_stage_only=True,
        state_writer_source_window=(1, 3),
        capture_untagged_state_writers=True,
    )
    assert "const STATE_WRITER_SOURCE_WINDOW = [1, 3];" in script
    assert "source:'gta-native-process-stage'" in script
    assert "source:'gta-native-set-element-angular-velocity'" in script


def test_suspension_stage_only_omits_wheel_hook_but_keeps_stage_hooks():
    tool = _load_tool()
    script = tool._native_script(
        Path("C:/mta"),
        "stage",
        install_wheel_hook=False,
        collision_diagnostics=True,
        suspension_stage_only=True,
    )
    assert "if (INSTALL_NATIVE_WHEEL_HOOK || INSTALL_COLLISION_DIAGNOSTICS" in script
    assert "source:'gta-native-process-stage'" in script
    assert "GetNativeProcessWheelSourceTagBridge" in script
    assert "sourceFrameTagEntry" in script
    assert "sourceFrameTagExit" in script
    assert "if (INSTALL_NATIVE_WHEEL_HOOK)" in script
    assert script.index("source:'gta-native-process-stage'") < script.index("if (INSTALL_NATIVE_WHEEL_HOOK) {")


def test_stage_capture_includes_transmission_history_boundary():
    tool = _load_tool()
    script = tool._native_script(
        Path("C:/mta"),
        "stage",
        install_wheel_hook=False,
        collision_diagnostics=True,
        suspension_stage_only=True,
    )
    assert "const transmissionSnapshot" in script
    assert "inertiaValue1:f(vehicle.add(0x808))" in script
    assert "inertiaValue2:f(vehicle.add(0x80C))" in script
    assert "transmission:control.transmission" in script
    assert "transmission:transmissionSnapshot(vehicle)" in script
    assert "calculateDriveAcceleration" in script
    assert "transmissionCalls:control.transmissionCalls" in script
    assert "inertiaValue2After" in script


def test_collision_diagnostics_capture_fresh_automobile_col_points():
    source = TOOL.read_text(encoding="utf-8")
    assert "main.base.add(0x81BFF8)" in source
    assert "colPointArray(automobileCollisionPoints, 12)" in source
    assert "colPointArray(this.nativeEntityCollisionOutput, 32)" in source
    assert "SUSPENSION_STAGE_ONLY" in source
    assert "automobileCollisionPointsAfter:colPointArray(automobileCollisionPoints, 12)" in source
    assert "CAPTURE_FROM_FIRST_GAS" in source
    assert "SUSPENSION_STAGE_ONLY" in source
    assert "if (!SUSPENSION_STAGE_ONLY)" in source
    assert "captureActive = true" in source
    assert "maxPreCaptureRecords = 512" in source


def test_timing_probe_captures_native_timer_fields():
    source = TOOL.read_text(encoding="utf-8")
    assert "timerOldStep:timerOldStep.readFloat()" in source
    assert "timerStepNonClipped:timerStepNonClipped.readFloat()" in source
    assert "timerStep:timerStep.readFloat()" in source


def test_cpp_collision_stream_flushes_partial_batches():
    source = TOOL.read_text(encoding="utf-8")
    assert 'MTA_NATIVE_COLLISION_ALT_CPP_FLUSH_EVERY' in source
    assert 'os.environ["MTA_NATIVE_COLLISION_ALT_CPP_FLUSH_EVERY"] = "1"' in source
    assert '"cpp_collision_flush_every"' in source


def test_cpp_stage_only_selects_boundary_observers_without_wheel_output():
    source = TOOL.read_text(encoding="utf-8")
    assert '"--cpp-stage-only"' in source
    assert 'args.cpp_stage_only' in source
    assert 'MTA_NATIVE_PROCESSCONTROL_CPP_OUTPUT' in source
    assert 'MTA_NATIVE_PROCESSSUSPENSION_CPP_OUTPUT' in source
    assert 'not args.cpp_stage_only' in source


def test_cpp_stage_public_angular_route_is_minimal_and_does_not_hook_processcontrol():
    tool = _load_tool()
    script = tool._cpp_public_angular_writer_script("cpp-stage-public-angular")
    assert "0x7AE0B0" in script
    assert "gta-native-set-element-angular-velocity-cpp-stage-join" in script
    assert "GetNativeProcessWheelSourceTagBridge" in script
    assert "nativeCandidates" in script
    assert "CVehicleSA::SetTurnSpeed" in script
    assert "CPhysicalSA::SetTurnSpeed" in script
    assert "gta-native-set-turn-speed-cpp-stage-join" in script
    assert "Interceptor.attach(address" in script
    assert "PROCESS_CONTROL_RVA" not in script
    assert "Interceptor.attach(processControl" not in script


def test_cpp_processcontrol_boundary_source_window_is_explicit_diagnostic():
    source = TOOL.read_text(encoding="utf-8")
    assert '"--cpp-processcontrol-boundary"' in source
    assert '"--cpp-processcontrol-source-window"' in source
    assert 'MTA_NATIVE_PROCESSCONTROL_CPP_START_FRAME' in source
    assert 'MTA_NATIVE_PROCESSCONTROL_CPP_END_FRAME' in source
    assert 'cpp_processcontrol_boundary' in source
    assert 'cpp_processcontrol_source_window' in source


def test_cpp_processsuspension_boundary_is_explicit_diagnostic():
    source = TOOL.read_text(encoding="utf-8")
    assert "--cpp-processsuspension-boundary" in source
    assert "--cpp-processsuspension-source-window" in source
    assert "MTA_NATIVE_PROCESSSUSPENSION_CPP_OUTPUT" in source
    assert "MTA_NATIVE_PROCESSSUSPENSION_CPP_START_FRAME" in source
    assert "cpp_suspension_binary" in source
    assert "cpp_processsuspension_boundary" in source


def test_stage_force_diagnostics_publishes_suspension_physical_boundary():
    tool = _load_tool()
    script = tool._native_script(
        Path("C:/mta"),
        "stage-force",
        install_wheel_hook=False,
        collision_diagnostics=True,
        suspension_stage_only=True,
        stage_force_diagnostics=True,
    )
    assert "const STAGE_FORCE_DIAGNOSTICS = true;" in script
    assert "physicalBefore:this.nativeSuspensionPhysicalBefore" in script
    assert "physicalAfter:STAGE_FORCE_DIAGNOSTICS" in script
    assert "forceEvents:(STAGE_FORCE_DIAGNOSTICS || STAGE_FORCE_EVENTS)" in script
    assert "applyForces:STAGE_FORCE_DIAGNOSTICS ? control.applyForces : null" in script
    assert "nativeForceDuringSuspension" in script


def test_stage_force_events_are_bounded_and_capture_velocity_deltas():
    tool = _load_tool()
    script = tool._native_script(
        Path("C:/mta"),
        "stage-force-events",
        install_wheel_hook=False,
        collision_diagnostics=True,
        suspension_stage_only=True,
        stage_force_diagnostics=True,
        stage_force_events=True,
        stage_force_source_window=(20, 30),
    )
    assert "const STAGE_FORCE_EVENTS = true;" in script
    assert "const STAGE_FORCE_SOURCE_WINDOW = [20, 30];" in script
    assert "source:'gta-native-processsuspension-ApplyForce'" in script
    assert "linearVelocityDelta:delta" in script
    assert "activeSuspensionForceContext" in script


def test_reduced_stage_probe_keeps_collision_check_and_matrix_boundaries():
    tool = _load_tool()
    script = tool._native_script(
        Path("C:/mta"),
        "stage",
        install_wheel_hook=False,
        collision_diagnostics=True,
        suspension_stage_only=True,
    )
    assert "const matrixSnapshot" in script
    assert "position:control.position" in script
    assert "frictionAngularVelocity:control.frictionAngularVelocity" in script
    assert "force:control.force" in script
    assert "torque:control.torque" in script
    assert "matrix:control.matrix" in script
    assert "collisionCheck:control.collisionCheck" in script
    assert "nativeStageCollisionKey" in script
    assert "nativeStageProcessCollisionKey" in script
    assert "nativeStageProcessCollisionBeforeSuspension" in script
    assert "automobileCollisionPointsBefore:this.nativeStageProcessCollisionBeforeAutomobileCollisionPoints" in script
    assert "suspensionAfter:afterSuspension" in script
    assert "processCollisionBoundaries:control.processCollisionBoundaries" in script


def test_processcollision_untagged_after_writer_capture_is_bounded_and_labelled():
    tool = _load_tool()
    script = tool._native_script(
        Path("C:/mta"),
        "collision-writer-startup",
        install_wheel_hook=False,
        collision_diagnostics=True,
        suspension_stage_only=True,
        processcollision_source_window=(1, 3),
        capture_untagged_processcollision_after_writer=True,
        state_writer_source_window=(1, 3),
        capture_untagged_state_writers=True,
    )
    assert "const CAPTURE_UNTAGGED_PROCESSCOLLISION_AFTER_WRITER = true;" in script
    assert "allowUntaggedProcessCollisionAfterWriter" in script
    assert "'untagged-after-public-angular-writer'" in script


def test_processcollision_untagged_startup_capture_is_bounded_and_labelled():
    tool = _load_tool()
    script = tool._native_script(
        Path("C:/mta"),
        "collision-startup",
        install_wheel_hook=False,
        collision_diagnostics=True,
        suspension_stage_only=True,
        processcollision_source_window=(1, 30),
        capture_untagged_processcollision_before_source=True,
        untagged_processcollision_min_game_time_ms=30000,
    )
    assert "const CAPTURE_UNTAGGED_PROCESSCOLLISION_BEFORE_SOURCE = true;" in script
    assert "const UNTAGGED_PROCESSCOLLISION_MIN_GAME_TIME_MS = 30000;" in script
    assert "maxUntaggedProcessCollisionBeforeSource = 8" in script
    assert "'untagged-before-source-tag'" in script
    assert "captureProvenance:boundary.captureProvenance" in script


def test_actual_race_capture_removes_synthetic_map_and_polls_race_vehicle(tmp_path):
    tool = _load_tool()
    resource = (
        tmp_path / "server" / "mods" / "deathmatch" / "resources" / "native_capture"
    )
    resource.mkdir(parents=True)
    original_meta = (
        '<meta>\r\n'
        '  <map src="Etnies.map" dimension="0" />\r\n'
        '  <script src="server.lua" type="server" />\r\n'
        '  <script src="client.lua" type="client" />\r\n'
        '</meta>\r\n'
    ).encode()
    original_server = b'local original = true\r\n'
    (resource / "meta.xml").write_bytes(original_meta)
    (resource / "server.lua").write_bytes(original_server)

    restore = tool._prepare_actual_race_capture(
        tmp_path, "etnies-native", "race-tags", delay_ms=30000
    )
    meta = (resource / "meta.xml").read_bytes().decode()
    server = (resource / "server.lua").read_bytes().decode()
    assert "Etnies.map" not in meta
    assert 'src="client.lua"' not in meta
    assert 'getPedOccupiedVehicle(player)' in server
    assert 'getElementModel(vehicle) ~= 411' in server
    assert '"race-tags"' in server
    assert "end, 30000, 1)" in server
    assert '"tas:automationStart"' in server
    assert "\r\n" in server

    restore()
    assert (resource / "meta.xml").read_bytes() == original_meta
    assert (resource / "server.lua").read_bytes() == original_server
    assert not (resource / "meta.xml.native-capture-original").exists()
    assert not (resource / "server.lua.native-capture-original").exists()


def test_tas_automation_playback_replaces_native_event_and_restores(tmp_path):
    tool = _load_tool()
    resource = (
        tmp_path / "server" / "mods" / "deathmatch" / "resources" / "native_capture"
    )
    resource.mkdir(parents=True)
    original = (
        'local vehicle = nil\r\n'
        '    triggerClientEvent(player, "nativeCapture:start", resourceRoot, "etnies-native", "native-etnies")\r\n'
    ).encode()
    path = resource / "server.lua"
    path.write_bytes(original)

    restore = tool._prepare_tas_automation_playback(tmp_path, "tagged-run")
    prepared = path.read_bytes().decode()
    assert '"tas:automationStart"' in prepared
    assert 'getResourceRootElement(tasResource)' in prepared
    assert '"tagged-run"' in prepared
    assert "\r\n" in prepared
    restore()
    assert path.read_bytes() == original


def test_gta_import_redirects_and_restores(tmp_path):
    tool = _load_tool()
    path = tmp_path / "gta_sa.exe"
    original = b"prefixWINMM.dllsuffix"
    path.write_bytes(original)

    restore = tool._prepare_gta_import(path)

    assert path.read_bytes() == b"prefixmtasa.dllsuffix"
    assert (tmp_path / "gta_sa.exe.native-capture-original").read_bytes() == original
    restore()
    assert path.read_bytes() == original

    path.write_bytes(b"prefixWINMM.dllmiddleWINMM.dllsuffix")
    restore = tool._prepare_gta_import(path)
    assert path.read_bytes() == b"prefixmtasa.dllmiddleWINMM.dllsuffix"
    restore()
    assert path.read_bytes() == b"prefixWINMM.dllmiddleWINMM.dllsuffix"


def test_real_vorbis_recovers_stale_real_dll_from_backup(tmp_path):
    tool = _load_tool()
    (tmp_path / "vorbisfile.dll").write_bytes(b"real")
    (tmp_path / "vorbisfile_real.dll").write_bytes(b"real")
    (tmp_path / "vorbisfile.native-capture-original.dll").write_bytes(b"proxy")

    restore = tool._prepare_real_vorbis(tmp_path)

    assert (tmp_path / "vorbisfile.dll").read_bytes() == b"proxy"
    restore()
    assert (tmp_path / "vorbisfile.dll").read_bytes() == b"proxy"


def test_native_capture_start_delay_handles_crlf_and_restores(tmp_path):
    tool = _load_tool()
    resource = (
        tmp_path / "server" / "mods" / "deathmatch" / "resources" / "native_capture"
    )
    resource.mkdir(parents=True)
    original = (
        'addEvent("nativeCapture:start", true)\r\n'
        'addEventHandler("nativeCapture:start", resourceRoot, function(recordName, outputName)\r\n'
        '    setTimer(function()\r\n'
        '        executeCommandHandler("loadr", recordName)\r\n'
        '        setTimer(function()\r\n'
        '            executeCommandHandler("recordplayback", outputName)\r\n'
        '        end, 1000, 1)\r\n'
        '    end, 1000, 1)\r\n'
        'end)\r\n'
    ).encode()
    path = resource / "client.lua"
    path.write_bytes(original)

    restore = tool._prepare_native_capture_start_delay(tmp_path, 30000)
    prepared = path.read_bytes().decode()
    assert "end, 30000, 1)" in prepared
    assert "\r\n" in prepared
    restore()
    assert path.read_bytes() == original
