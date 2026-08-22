from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
CLIENT = REPO / "new" / "tas" / "client.lua"
SERVER = REPO / "new" / "tas" / "server.lua"


def test_playback_failure_reports_controller_and_element_state_once():
    source = CLIENT.read_text(encoding="utf-8")
    assert 'tas:playbackFailureDiagnostic' in source
    assert "playback_last_vehicle" in source
    assert "occupiedVehicle" in source
    assert "lastKnownVehicle" in source
    assert source.index("tas.report_playback_failure()") < source.rindex(
        "tas.finish_playback_recording(false)"
    )
    assert "single failure-time report" in source


def test_playback_failure_server_event_is_authenticated_and_automation_scoped():
    source = SERVER.read_text(encoding="utf-8")
    assert 'addEvent("tas:playbackFailureDiagnostic", true)' in source
    assert "client ~= source" in source
    assert "active.player ~= client" in source
    assert "toJSON(context, true)" in source
