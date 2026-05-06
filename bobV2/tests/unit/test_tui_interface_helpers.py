import inspect
from pathlib import Path

from bob.config.schema import BobConfig
import bob.tui.interface as interface_module
from bob.tui.interface import Interface, _strip_ansi, _visible_len


class _FakeSession:
    def __init__(self, bob_home: Path) -> None:
        self.bob_home = bob_home
        self.session_id = "sess-1"
        self.cwd = bob_home
        self.action_log_path = bob_home / "logs" / "actions" / "actions.log"
        self.current_rollout_path = bob_home / "sessions" / "rollout.jsonl"


def test_format_command_labels_cmd_wrapper() -> None:
    label, arg = Interface._format_command(["cmd.exe", "/C", "dir", "/b"])

    assert label == "Cmd"
    assert arg == "dir /b"


def test_format_command_labels_powershell_and_keeps_inner_flags() -> None:
    label, arg = Interface._format_command([
        "powershell.exe",
        "-NoLogo",
        "-NoProfile",
        "-Command",
        "Get-ChildItem",
        "-Recurse",
        "-Depth",
        "3",
        "bobV2",
    ])

    assert label == "PowerShell"
    assert arg == "Get-ChildItem -Recurse -Depth 3 bobV2"


def test_format_command_labels_pwsh_c_wrapper() -> None:
    label, arg = Interface._format_command([
        "pwsh",
        "-c",
        "git",
        "status",
        "--short",
    ])

    assert label == "PowerShell"
    assert arg == "git status --short"


def test_input_box_dash_width_matches_shared_prompt_geometry() -> None:
    assert Interface._input_box_dash_width(120) == 117
    assert Interface._input_box_dash_width(40) == 37


def test_strip_ansi_removes_color_codes() -> None:
    assert _strip_ansi("\x1b[31mred\x1b[0m plain") == "red plain"


def test_parse_at_images_supports_detail_suffix(tmp_path: Path) -> None:
    img = tmp_path / "shot.png"
    img.write_bytes(b"png")

    cleaned, image_paths = interface_module._parse_at_images(f"look at @{img}#high please")

    assert cleaned == "look at  please"
    assert image_paths == [(img.resolve(), "high")]


def test_stalled_status_has_distinct_icon_and_label(tmp_path: Path) -> None:
    interface = Interface(session=_FakeSession(tmp_path / ".bob"), config=BobConfig())
    try:
        assert _strip_ansi(interface._status_icon("stalled")) == "⏳"
        assert _strip_ansi(interface._status_label("stalled")) == "stalled"
    finally:
        interface._session_log_handle.close()


def test_interface_logs_spinner_snapshot_once_per_change(tmp_path: Path) -> None:
    interface = Interface(session=_FakeSession(tmp_path / ".bob"), config=BobConfig())
    try:
        interface._log_spinner_snapshot("Thinking...", ["  one"])
        interface._log_spinner_snapshot("Thinking...", ["  one"])
        interface._log_spinner_snapshot("Thinking...", ["  two"])
        text = interface._session_log_path.read_text(encoding="utf-8-sig")
        assert text.count("SPINNER Thinking...") == 2
        assert "  one" in text
        assert "  two" in text
    finally:
        interface._session_log_handle.close()


def test_spinner_frame_is_truncated_to_terminal_width() -> None:
    line = Interface._format_spinner_frame(
        "⠋",
        "4 agents: [turn_execution] 0:03 · [cli_flow] 0:03 · [app_server] 0:03",
        columns=40,
    )

    assert _visible_len(line.replace("\r", "")) <= 40
    assert _strip_ansi(line).endswith("…")



def test_interface_logs_terminal_mutations_and_blocks(tmp_path: Path) -> None:
    interface = Interface(session=_FakeSession(tmp_path / ".bob"), config=BobConfig())
    try:
        interface._log_terminal_mutation("cursor_up", lines=2)
        interface._log_terminal_block("header", ["row 1", "\x1b[31mrow 2\x1b[0m"])
        text = interface._session_log_path.read_text(encoding="utf-8-sig")
        assert "[terminal] cursor_up lines=2" in text
        assert "[terminal-block] header" in text
        assert "row 1" in text
        assert "row 2" in text
    finally:
        interface._session_log_handle.close()


def test_interface_dedupes_identical_terminal_mutations_when_requested(tmp_path: Path) -> None:
    interface = Interface(session=_FakeSession(tmp_path / ".bob"), config=BobConfig())
    try:
        interface._log_terminal_mutation("frame_drawn", dedupe=True, spinner="Thinking...", panel_lines=0)
        interface._log_terminal_mutation("frame_drawn", dedupe=True, spinner="Thinking...", panel_lines=0)
        interface._log_terminal_mutation("frame_drawn", dedupe=True, spinner="Thinking...", panel_lines=1)
        text = interface._session_log_path.read_text(encoding="utf-8-sig")
        assert text.count("[terminal] frame_drawn") == 2
    finally:
        interface._session_log_handle.close()


def test_interface_logs_event_handler_errors(tmp_path: Path) -> None:
    interface = Interface(session=_FakeSession(tmp_path / ".bob"), config=BobConfig())
    try:
        interface._log_event_handler_error(type("Msg", (), {"type": "agent_status"})(), ValueError("bad event"))
        text = interface._session_log_path.read_text(encoding="utf-8-sig")
        assert "[event-error] type=agent_status error=ValueError: bad event" in text
    finally:
        interface._session_log_handle.close()


def test_startup_log_rows_include_current_log_paths(tmp_path: Path) -> None:
    interface = Interface(session=_FakeSession(tmp_path / ".bob"), config=BobConfig())
    try:
        rows = interface._startup_log_rows()
        assert any("Session Files" in row for row in rows)
        assert any("bob_home" in row and ".bob" in row for row in rows)
        assert any("logs" in row and "actions.log" in row for row in rows)
        assert any("logs" in row and "sess-1.log" in row for row in rows)
        assert any("sessions" in row and "rollout.jsonl" in row for row in rows)
    finally:
        interface._session_log_handle.close()


def test_consume_events_uses_module_level_shutil(tmp_path: Path) -> None:
    interface = Interface(session=_FakeSession(tmp_path / ".bob"), config=BobConfig())
    try:
        source = inspect.getsource(interface._consume_events)
        assert "import shutil" not in source
    finally:
        interface._session_log_handle.close()
