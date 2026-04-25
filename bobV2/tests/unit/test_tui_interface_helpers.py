from pathlib import Path

from bob.config.schema import BobConfig
from bob.tui.interface import Interface, _strip_ansi


class _FakeSession:
    def __init__(self, bob_home: Path) -> None:
        self.bob_home = bob_home
        self.session_id = "sess-1"
        self.cwd = bob_home


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


def test_interface_logs_spinner_snapshot_once_per_change(tmp_path: Path) -> None:
    interface = Interface(session=_FakeSession(tmp_path / ".bob"), config=BobConfig())
    try:
        interface._log_spinner_snapshot("Thinking...", ["  one"])
        interface._log_spinner_snapshot("Thinking...", ["  one"])
        interface._log_spinner_snapshot("Thinking...", ["  two"])
        text = interface._session_log_path.read_text(encoding="utf-8")
        assert text.count("SPINNER Thinking...") == 2
        assert "  one" in text
        assert "  two" in text
    finally:
        interface._session_log_handle.close()


def test_interface_logs_agent_status_updates(tmp_path: Path) -> None:
    interface = Interface(session=_FakeSession(tmp_path / ".bob"), config=BobConfig())
    try:
        interface._record_agent_status(
            "a1",
            color="",
            display_name="researcher",
            activity="Findings collected",
            tokens=120,
            status="done",
        )
        assert interface._agent_statuses["a1"]["status"] == "done"
        assert interface._agent_statuses["a1"]["tokens"] == 120
        assert interface._agent_statuses["a1"]["_done_at"] is not None
        text = interface._session_log_path.read_text(encoding="utf-8")
        assert "[agent-panel] update id=a1 status=done tokens=120 activity=Findings collected" in text
    finally:
        interface._session_log_handle.close()


def test_interface_logs_terminal_mutations_and_blocks(tmp_path: Path) -> None:
    interface = Interface(session=_FakeSession(tmp_path / ".bob"), config=BobConfig())
    try:
        interface._log_terminal_mutation("cursor_up", lines=2)
        interface._log_terminal_block("header", ["row 1", "\x1b[31mrow 2\x1b[0m"])
        text = interface._session_log_path.read_text(encoding="utf-8")
        assert "[terminal] cursor_up lines=2" in text
        assert "[terminal-block] header" in text
        assert "row 1" in text
        assert "row 2" in text
    finally:
        interface._session_log_handle.close()


def test_interface_writes_session_log_and_clear_events(tmp_path: Path) -> None:
    interface = Interface(session=_FakeSession(tmp_path / ".bob"), config=BobConfig())
    try:
        interface._log_ui_line("hello")
        interface._agent_statuses = {
            "a1": {"status": "done"},
            "a2": {"status": "error"},
        }
        interface._clear_agent_statuses("test_clear")
        text = interface._session_log_path.read_text(encoding="utf-8")
        assert "[session] log started for session=sess-1" in text
        assert "hello" in text
        assert "[agent-panel] cleared reason=test_clear removed=a1, a2" in text
    finally:
        interface._session_log_handle.close()
