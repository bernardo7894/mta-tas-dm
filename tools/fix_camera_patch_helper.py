from pathlib import Path

path = Path("tools/apply_camera_telemetry_patch.py")
text = path.read_text(encoding="utf-8")
old = r"'\texecuteCommandHandler(tas.registered_commands.save_record, args[1])\n\texecuteCommandHandler(tas.registered_commands.save_analysis, args[1])\n\n"
new = r"'\t\texecuteCommandHandler(tas.registered_commands.save_record, args[1])\n\t\texecuteCommandHandler(tas.registered_commands.save_analysis, args[1])\n\n"
count = text.count(old)
if count != 2:
    raise SystemExit(f"expected 2 saveboth anchor prefixes, found {count}")
path.write_text(text.replace(old, new), encoding="utf-8")
