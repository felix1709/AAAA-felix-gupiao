import zipfile
from pathlib import Path

import pytest

import tools.tradingagents_service_manager as manager
from tools.tradingagents_service_manager import (
    ProcessRecord,
    ScheduledTaskRecord,
    ServiceManagerApp,
    build_briefing_command,
    build_briefing_task_action,
    collect_process_tree,
    find_tradingagents_processes,
    resolve_briefing_dir,
    resolve_project_root_from_anchors,
)

PROJECT_ROOT = str(manager.PROJECT_ROOT)
WORKSPACE_ROOT = str(manager.WORKSPACE_ROOT)
BRIEFING_DIR = str(manager.BRIEFING_DIR)


def test_finds_python_process_started_from_project_path():
    processes = [
        ProcessRecord(
            pid=100,
            parent_pid=1,
            name="python.exe",
            executable_path=r"C:\Python310\python.exe",
            command_line=rf'python "{PROJECT_ROOT}\main.py"',
        ),
        ProcessRecord(
            pid=101,
            parent_pid=1,
            name="python.exe",
            executable_path=r"C:\Python310\python.exe",
            command_line=r'python "E:\other\server.py"',
        ),
    ]

    matches = find_tradingagents_processes(
        processes,
        project_root=PROJECT_ROOT,
        excluded_pids=set(),
    )

    assert [process.pid for process in matches] == [100]


def test_ignores_the_service_manager_itself():
    processes = [
        ProcessRecord(
            pid=200,
            parent_pid=1,
            name="python.exe",
            executable_path=r"C:\Python310\python.exe",
            command_line=rf'python "{PROJECT_ROOT}\tools\tradingagents_service_manager.py"',
        ),
        ProcessRecord(
            pid=201,
            parent_pid=1,
            name="python.exe",
            executable_path=r"C:\Python310\python.exe",
            command_line=rf'python "{PROJECT_ROOT}\main.py"',
        ),
    ]

    matches = find_tradingagents_processes(
        processes,
        project_root=PROJECT_ROOT,
        excluded_pids={200},
    )

    assert [process.pid for process in matches] == [201]


def test_ignores_test_runner_processes_inside_project_path():
    processes = [
        ProcessRecord(
            pid=300,
            parent_pid=1,
            name="python.exe",
            executable_path=rf"{PROJECT_ROOT}\.venv\Scripts\python.exe",
            command_line=rf'python -m pytest "{PROJECT_ROOT}\tests\test_service_manager.py"',
        ),
        ProcessRecord(
            pid=301,
            parent_pid=1,
            name="python.exe",
            executable_path=r"C:\Python310\python.exe",
            command_line=rf'python "{PROJECT_ROOT}\main.py"',
        ),
    ]

    matches = find_tradingagents_processes(
        processes,
        project_root=PROJECT_ROOT,
        excluded_pids=set(),
    )

    assert [process.pid for process in matches] == [301]


def test_ignores_processes_from_other_tradingagents_checkouts():
    other_project = r"D:\other-work\TradingAgents"
    processes = [
        ProcessRecord(
            pid=350,
            parent_pid=1,
            name="python.exe",
            executable_path=r"C:\Python310\python.exe",
            command_line=rf'python "{other_project}\main.py"',
        ),
        ProcessRecord(
            pid=351,
            parent_pid=1,
            name="python.exe",
            executable_path=r"C:\Python310\python.exe",
            command_line=rf'python "{PROJECT_ROOT}\main.py"',
        ),
    ]

    matches = find_tradingagents_processes(
        processes,
        project_root=PROJECT_ROOT,
        excluded_pids=set(),
    )

    assert [process.pid for process in matches] == [351]


def test_finds_daily_briefing_process_started_from_workspace_path():
    processes = [
        ProcessRecord(
            pid=400,
            parent_pid=1,
            name="pythonw.exe",
            executable_path=r"C:\Python310\pythonw.exe",
            command_line=rf'pythonw "{BRIEFING_DIR}\run_briefing.py" --mode monitor',
        ),
        ProcessRecord(
            pid=401,
            parent_pid=1,
            name="python.exe",
            executable_path=r"C:\Python310\python.exe",
            command_line=r'python "E:\other\daily_briefing\run_briefing.py" --mode monitor',
        ),
    ]

    matches = find_tradingagents_processes(
        processes,
        project_root=PROJECT_ROOT,
        excluded_pids=set(),
    )

    assert [process.pid for process in matches] == [400]


def test_finds_packaged_briefing_process_started_from_clean_folder():
    processes = [
        ProcessRecord(
            pid=410,
            parent_pid=1,
            name="AAA.exe",
            executable_path=rf"{WORKSPACE_ROOT}\AAA.exe",
            command_line=rf'"{WORKSPACE_ROOT}\AAA.exe" --run-briefing --mode monitor',
        ),
        ProcessRecord(
            pid=411,
            parent_pid=1,
            name="AAA.exe",
            executable_path=rf"{WORKSPACE_ROOT}\AAA.exe",
            command_line=rf'"{WORKSPACE_ROOT}\AAA.exe"',
        ),
    ]

    matches = find_tradingagents_processes(
        processes,
        project_root=PROJECT_ROOT,
        excluded_pids=set(),
    )

    assert [process.pid for process in matches] == [410]


def test_collect_process_tree_returns_descendants_before_parent():
    processes = [
        ProcessRecord(10, 1, "uv.exe", "", "uv run python main.py"),
        ProcessRecord(11, 10, "python.exe", "", "python main.py"),
        ProcessRecord(12, 11, "python.exe", "", "worker"),
        ProcessRecord(20, 1, "python.exe", "", "other"),
    ]

    assert collect_process_tree([10], processes, excluded_pids=set()) == [12, 11, 10]


def test_build_briefing_command_can_generate_preview_without_sending():
    command = build_briefing_command("premarket", send=False)

    assert Path(command[0]).name in {"pythonw.exe", "python.exe", "py.exe", "python"}
    assert command[-4:] == [
        str(Path(BRIEFING_DIR) / "run_briefing.py"),
        "--mode",
        "premarket",
        "--no-send",
    ]


def test_build_briefing_command_can_generate_and_send():
    command = build_briefing_command("close", send=True)

    assert command[-3:] == [
        str(Path(BRIEFING_DIR) / "run_briefing.py"),
        "--mode",
        "close",
    ]


def test_build_briefing_command_uses_packaged_exe_when_frozen(monkeypatch):
    monkeypatch.setattr(manager.sys, "frozen", True, raising=False)
    monkeypatch.setattr(manager.sys, "executable", rf"{WORKSPACE_ROOT}\AAA.exe")

    command = build_briefing_command("midday", send=False)

    assert command == [
        rf"{WORKSPACE_ROOT}\AAA.exe",
        "--run-briefing",
        "--mode",
        "midday",
        "--no-send",
    ]


def test_scheduled_task_action_uses_packaged_exe_when_frozen(monkeypatch):
    monkeypatch.setattr(manager.sys, "frozen", True, raising=False)
    monkeypatch.setattr(manager.sys, "executable", rf"{WORKSPACE_ROOT}\AAA.exe")

    action = build_briefing_task_action("close")

    assert action.execute == rf"{WORKSPACE_ROOT}\AAA.exe"
    assert action.arguments == "--run-briefing --mode close"
    assert action.working_directory == WORKSPACE_ROOT


def test_scheduled_refresh_waits_before_polling_again():
    calls = []

    class FakeRoot:
        def after(self, delay_ms, callback):
            calls.append((delay_ms, callback))

    class Enabled:
        def get(self):
            return True

    app = ServiceManagerApp.__new__(ServiceManagerApp)
    app.root = FakeRoot()
    app.auto_refresh = Enabled()
    app.refresh = lambda silent=False: calls.append(("refresh", silent))

    app._schedule_refresh()

    assert len(calls) == 1
    assert calls[0][0] == 5000
    assert callable(calls[0][1])


def test_resolve_project_root_when_exe_is_in_workspace_root(tmp_path):
    workspace = tmp_path / "A沪深"
    project = workspace / "TradingAgents"
    (project / "tools").mkdir(parents=True)
    (workspace / "daily_briefing").mkdir()

    assert resolve_project_root_from_anchors([workspace]) == project


def test_resolve_project_root_when_exe_is_in_dist_folder(tmp_path):
    workspace = tmp_path / "A沪深"
    project = workspace / "TradingAgents"
    dist = project / "dist"
    (project / "tools").mkdir(parents=True)
    (workspace / "daily_briefing").mkdir()
    dist.mkdir()

    assert resolve_project_root_from_anchors([dist]) == project


def test_resolve_project_root_when_repo_contains_briefing_dir(tmp_path):
    project = tmp_path / "AAAA-felix-gupiao"
    (project / "tools").mkdir(parents=True)
    (project / "daily_briefing").mkdir()

    assert resolve_project_root_from_anchors([project]) == project


def test_resolve_project_root_from_clean_portable_folder(tmp_path):
    workspace = tmp_path / "AStockBriefingManager"
    (workspace / "daily_briefing").mkdir(parents=True)

    assert resolve_project_root_from_anchors([workspace]) == workspace / "TradingAgents"


def test_resolve_briefing_dir_prefers_sibling_layout(tmp_path, monkeypatch):
    monkeypatch.delenv("A_STOCK_BRIEFING_DIR", raising=False)
    workspace = tmp_path / "AStock"
    project = workspace / "TradingAgents"
    briefing = workspace / "daily_briefing"
    project.mkdir(parents=True)
    briefing.mkdir()

    assert resolve_briefing_dir(project) == briefing


def test_resolve_briefing_dir_supports_repo_local_layout(tmp_path, monkeypatch):
    monkeypatch.delenv("A_STOCK_BRIEFING_DIR", raising=False)
    project = tmp_path / "AAAA-felix-gupiao"
    briefing = project / "daily_briefing"
    briefing.mkdir(parents=True)

    assert resolve_briefing_dir(project) == briefing


def test_api_settings_form_values_are_normalized():
    class FakeVar:
        def __init__(self, value):
            self.value = value

        def get(self):
            return self.value

    app = ServiceManagerApp.__new__(ServiceManagerApp)
    app.api_vars = {
        "base_url": FakeVar(" https://api.example.com/v1/ "),
        "api_key": FakeVar(" sk-test-key "),
        "model": FakeVar(" gpt-test "),
    }

    assert app._api_settings_from_form() == {
        "base_url": "https://api.example.com/v1",
        "api_key": "sk-test-key",
        "model": "gpt-test",
    }


def test_smtp_settings_form_values_are_normalized():
    class FakeVar:
        def __init__(self, value):
            self.value = value

        def get(self):
            return self.value

    app = ServiceManagerApp.__new__(ServiceManagerApp)
    app.smtp_vars = {
        "host": FakeVar(" smtp.example.com "),
        "port": FakeVar(" 465 "),
        "user": FakeVar(" sender@example.com "),
        "auth_code": FakeVar(" auth-code "),
    }

    assert app._smtp_settings_from_form() == {
        "host": "smtp.example.com",
        "port": 465,
        "user": "sender@example.com",
        "auth_code": "auth-code",
    }


def test_lookup_stock_name_reads_tencent_quote_response():
    class FakeResponse:
        content = 'v_sh600000="51~浦发银行~600000~9.40";'.encode("gbk")

        def raise_for_status(self):
            return None

    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse()

    assert manager.lookup_stock_name("600000", request_get=fake_get) == "浦发银行"
    assert calls[0][0].endswith("q=sh600000")
    assert calls[0][1]["timeout"] == 6


def test_stock_form_resolves_name_from_code(monkeypatch):
    class FakeVar:
        def __init__(self, value):
            self.value = value

        def get(self):
            return self.value

    app = ServiceManagerApp.__new__(ServiceManagerApp)
    app.stock_vars = {
        "code": FakeVar("600000"),
        "name": FakeVar(""),
        "shares": FakeVar("100"),
        "cost": FakeVar("9.12"),
        "risk": FakeVar(""),
        "risk2": FakeVar(""),
        "clear": FakeVar(""),
        "hard_stop": FakeVar(""),
        "reduce_low": FakeVar(""),
        "reduce_high": FakeVar(""),
    }
    app.stock_enabled = FakeVar(True)
    app.settings = {"stocks": []}
    monkeypatch.setattr(manager, "lookup_stock_name", lambda code: "浦发银行")

    stock = app._stock_from_form()

    assert stock["full_code"] == "600000.SS"
    assert stock["name"] == "浦发银行"
    assert stock["shares"] == 100
    assert stock["cost"] == 9.12


def test_api_connection_success_updates_model_options():
    class FakeVar:
        def __init__(self):
            self.value = ""

        def set(self, value):
            self.value = value

    class FakeCombo:
        def __init__(self):
            self.values = ()

        def __setitem__(self, key, value):
            if key == "values":
                self.values = value

    result = type(
        "Result",
        (),
        {
            "ok": True,
            "message": "连接成功。",
            "models": ("model-a", "model-b"),
        },
    )()
    app = ServiceManagerApp.__new__(ServiceManagerApp)
    app.api_test_status = FakeVar()
    app.model_combo = FakeCombo()

    message = app._format_api_test_result(result)

    assert message == "连接成功。"
    assert app.api_test_status.value == "连接正常"
    assert app.model_combo.values == ("model-a", "model-b")


def test_taskbar_title_shows_background_running_state():
    app = ServiceManagerApp.__new__(ServiceManagerApp)

    assert app._taskbar_title_for_status("运行中: 2") == "AAA - 后台运行中"
    assert app._taskbar_title_for_status("定时已启用") == "AAA"


def test_window_icon_path_points_to_red_bull_asset():
    app = ServiceManagerApp.__new__(ServiceManagerApp)

    icon_path = app._window_icon_path()

    assert icon_path.name == "red_bull.png"
    assert icon_path.exists()


def test_tray_preference_is_persisted():
    class FakeVar:
        def __init__(self, value=False):
            self.value = value

        def get(self):
            return self.value

        def set(self, value):
            self.value = value

    app = ServiceManagerApp.__new__(ServiceManagerApp)
    app.minimize_to_tray = FakeVar(False)
    app.settings = {}
    saved_values = []
    app.save_current_settings = lambda silent=False: saved_values.append(
        app.minimize_to_tray.get()
    )
    app._sync_tray_mode = lambda: None

    app.minimize_to_tray.set(True)
    app._save_tray_preference()

    assert app.settings["minimize_to_tray"] is True
    assert saved_values == [True]


def test_theme_tokens_use_banana_dark_console_palette():
    app = ServiceManagerApp.__new__(ServiceManagerApp)

    tokens = app._theme_tokens()

    assert tokens["window_bg"] == "#0f1117"
    assert tokens["panel_bg"] == "#171a21"
    assert tokens["accent"] == "#ffd84d"
    assert tokens["success"] == "#2ee59d"


def test_navigation_renames_api_to_settings_and_recipient_page_is_explicit():
    app = ServiceManagerApp.__new__(ServiceManagerApp)

    nav_items = app._nav_items()

    assert ("settings", "设置") in nav_items
    assert ("recipients", "邮箱") in nav_items
    assert ("service", "服务") in nav_items
    assert all(label != "API" for _key, label in nav_items)
    assert all(label != "添加收件人邮箱" for _key, label in nav_items)


def test_api_action_buttons_stay_in_header_row_to_avoid_clipping():
    app = ServiceManagerApp.__new__(ServiceManagerApp)

    layout = app._api_action_layout()

    assert layout["row"] == 0
    assert layout["column"] == 2
    assert layout["columnspan"] == 2


def test_checklist_routes_sender_to_settings_and_recipients_to_recipient_page():
    app = ServiceManagerApp.__new__(ServiceManagerApp)

    checklist = dict(app._checklist_config())

    assert checklist["发件邮箱已配置"] == "settings"
    assert checklist["至少有一个收件人"] == "recipients"


def test_checklist_button_labels_match_their_routes():
    app = ServiceManagerApp.__new__(ServiceManagerApp)

    labels = {
        item: app._checklist_button_label(page_key)
        for item, page_key in app._checklist_config()
    }

    assert labels["发件邮箱已配置"] == "去设置"
    assert labels["至少有一个收件人"] == "去邮箱"
    assert labels["至少有一只关注股票"] == "去股票"
    assert labels["定时服务已启用"] == "去服务"


def test_stock_form_fields_exclude_manual_name_input():
    app = ServiceManagerApp.__new__(ServiceManagerApp)

    fields = app._stock_form_fields()

    assert ("name", "名称") not in fields
    assert fields[0] == ("code", "代码")


def test_edit_selected_stock_loads_holding_values_into_form():
    class FakeVar:
        def __init__(self, value=""):
            self.value = value

        def get(self):
            return self.value

        def set(self, value):
            self.value = value

    class FakeTree:
        def selection(self):
            return ["600000.SS"]

    app = ServiceManagerApp.__new__(ServiceManagerApp)
    app.stock_tree = FakeTree()
    app.settings = {
        "stocks": [
            {
                "code": "600000",
                "suffix": "SS",
                "full_code": "600000.SS",
                "name": "浦发银行",
                "shares": 300,
                "cost": 9.12,
                "risk": 8.5,
                "risk2": None,
                "clear": 7.9,
                "hard_stop": None,
                "reduce_low": 10.0,
                "reduce_high": 10.5,
                "enabled": True,
            }
        ]
    }
    app.stock_vars = {
        key: FakeVar()
        for key in (
            "code",
            "name",
            "shares",
            "cost",
            "risk",
            "risk2",
            "clear",
            "hard_stop",
            "reduce_low",
            "reduce_high",
        )
    }
    app.stock_enabled = FakeVar(False)

    app.edit_selected_stock()

    assert app.stock_vars["code"].value == "600000.SS"
    assert app.stock_vars["name"].value == "浦发银行"
    assert app.stock_vars["shares"].value == "300"
    assert app.stock_vars["cost"].value == "9.12"
    assert app.stock_enabled.value is True


def test_overview_card_grid_uses_two_columns_to_avoid_overlap():
    app = ServiceManagerApp.__new__(ServiceManagerApp)

    assert app._overview_card_grid_position(0) == (0, 0)
    assert app._overview_card_grid_position(1) == (0, 1)
    assert app._overview_card_grid_position(2) == (1, 0)
    assert app._overview_card_grid_position(4) == (2, 0)


def test_is_newer_version_compares_release_tags():
    assert manager.is_newer_version("0.2.0", "v0.2.1") is True
    assert manager.is_newer_version("0.2.1", "v0.2.1") is False
    assert manager.is_newer_version("0.2.1", "v0.2.0") is False


def test_check_latest_release_detects_newer_release():
    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "tag_name": "v0.2.1",
                "html_url": "https://github.com/felix1709/AAAA-felix-gupiao/releases/tag/v0.2.1",
                "assets": [
                    {
                        "name": "AStockBriefingManager-clean.zip",
                        "browser_download_url": (
                            "https://github.com/felix1709/AAAA-felix-gupiao/releases/"
                            "download/v0.2.1/AStockBriefingManager-clean.zip"
                        ),
                    }
                ],
            }

    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse()

    result = manager.check_latest_release(current_version="0.2.0", request_get=fake_get)

    assert result.ok is True
    assert result.has_update is True
    assert result.latest_version == "v0.2.1"
    assert result.asset_name == "AStockBriefingManager-clean.zip"
    assert result.asset_download_url.endswith("/AStockBriefingManager-clean.zip")
    assert "发现新版本" in result.message
    assert calls[0][0].endswith("/releases/latest")


def test_check_latest_release_reports_missing_install_package():
    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "tag_name": "v0.2.2",
                "html_url": "https://github.com/felix1709/AAAA-felix-gupiao/releases/tag/v0.2.2",
                "assets": [],
            }

    result = manager.check_latest_release(current_version="0.2.1", request_get=lambda *_a, **_k: FakeResponse())

    assert result.ok is True
    assert result.has_update is True
    assert result.asset_download_url == ""
    assert "未找到可自动安装的 zip 包" in result.message


def test_update_manifest_skips_user_data_and_logs(tmp_path):
    package_root = tmp_path / "AStockBriefingManager-clean"
    (package_root / "daily_briefing" / "data").mkdir(parents=True)
    (package_root / "daily_briefing" / "logs").mkdir(parents=True)
    (package_root / "AAA.exe").write_text("exe", encoding="utf-8")
    (package_root / "StartManager.bat").write_text("start", encoding="utf-8")
    (package_root / "daily_briefing" / ".env").write_text("secret", encoding="utf-8")
    (package_root / "daily_briefing" / ".env.example").write_text("example", encoding="utf-8")
    (package_root / "daily_briefing" / "data" / "service_settings.json").write_text(
        "secret settings",
        encoding="utf-8",
    )
    (package_root / "daily_briefing" / "logs" / "service.log").write_text("log", encoding="utf-8")

    manifest = manager.build_update_file_manifest(package_root)

    assert Path("AAA.exe") in manifest
    assert Path("StartManager.bat") in manifest
    assert Path("daily_briefing/.env.example") in manifest
    assert Path("daily_briefing/.env") not in manifest
    assert Path("daily_briefing/data/service_settings.json") not in manifest
    assert Path("daily_briefing/logs/service.log") not in manifest


def test_find_update_package_root_supports_nested_clean_release(tmp_path):
    extract_root = tmp_path / "extract"
    package_root = extract_root / "AStockBriefingManager-clean"
    package_root.mkdir(parents=True)
    (package_root / "AAA.exe").write_text("exe", encoding="utf-8")

    assert manager.find_update_package_root(extract_root) == package_root


def test_extract_update_archive_rejects_paths_outside_target(tmp_path):
    archive_path = tmp_path / "bad.zip"
    extract_root = tmp_path / "extract"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../escape.txt", "bad")

    with pytest.raises(ValueError, match="不安全"):
        manager.extract_update_archive(archive_path, extract_root)


def test_write_update_script_copies_manifest_without_sensitive_files(tmp_path):
    package_root = tmp_path / "package"
    install_root = tmp_path / "install"
    script_path = tmp_path / "install_update.ps1"
    package_root.mkdir()
    install_root.mkdir()

    script = manager.write_update_script(
        package_root=package_root,
        install_root=install_root,
        current_executable=install_root / "AAA.exe",
        current_pid=1234,
        manifest=[
            Path("AAA.exe"),
            Path("StartManager.bat"),
            Path("daily_briefing/.env.example"),
        ],
        script_path=script_path,
        temp_root=tmp_path,
    )

    content = Path(script).read_text(encoding="utf-8")

    assert "$PidToWait = 1234" in content
    assert "AAA.exe" in content
    assert "StartManager.bat" in content
    assert ".env.example" in content
    assert "service_settings.json" not in content
    assert "daily_briefing\\logs" not in content
    assert "Start-Process" in content


def test_update_check_result_restores_button_state():
    class FakeVar:
        def __init__(self):
            self.value = ""

        def set(self, value):
            self.value = value

    class FakeButton:
        def __init__(self):
            self.state = "disabled"

        def configure(self, **kwargs):
            self.state = kwargs["state"]

    app = ServiceManagerApp.__new__(ServiceManagerApp)
    app.update_check_status = FakeVar()
    app.update_check_button = FakeButton()
    app.install_update_button = FakeButton()

    message = app._format_update_check_result(
        manager.UpdateCheckResult(
            ok=True,
            has_update=False,
            latest_version="v0.2.0",
            message="当前已是最新版本。",
        )
    )

    assert message == "当前已是最新版本。"
    assert app.update_check_status.value == "当前已是最新版本。"
    assert app.update_check_button.state == "normal"
    assert app.install_update_button.state == "disabled"


def test_update_check_result_enables_install_button_when_package_is_available():
    class FakeVar:
        def __init__(self):
            self.value = ""

        def set(self, value):
            self.value = value

    class FakeButton:
        def __init__(self):
            self.state = "disabled"

        def configure(self, **kwargs):
            self.state = kwargs["state"]

    app = ServiceManagerApp.__new__(ServiceManagerApp)
    app.update_check_status = FakeVar()
    app.update_check_button = FakeButton()
    app.install_update_button = FakeButton()

    app._format_update_check_result(
        manager.UpdateCheckResult(
            ok=True,
            has_update=True,
            latest_version="v0.2.2",
            message="发现新版本 v0.2.2，可一键下载并安装。",
            asset_download_url="https://example.com/AStockBriefingManager-clean.zip",
            asset_name="AStockBriefingManager-clean.zip",
        )
    )

    assert app.latest_update_result.asset_download_url.endswith(".zip")
    assert app.install_update_button.state == "normal"


def test_window_close_handler_is_registered(monkeypatch):
    class FakeVar:
        def __init__(self, value=None):
            self.value = value

        def get(self):
            return self.value

        def set(self, value):
            self.value = value

    class FakeRoot:
        def __init__(self):
            self.protocol_calls = []

        def title(self, _value):
            pass

        def geometry(self, _value):
            pass

        def minsize(self, _width, _height):
            pass

        def bind(self, _sequence, _callback):
            pass

        def protocol(self, name, callback):
            self.protocol_calls.append((name, callback))

    root = FakeRoot()
    monkeypatch.setattr(manager.settings_store, "load_settings", lambda: {})
    monkeypatch.setattr(manager.tk, "BooleanVar", lambda value=False: FakeVar(value))
    monkeypatch.setattr(manager.tk, "StringVar", lambda value="": FakeVar(value))
    monkeypatch.setattr(ServiceManagerApp, "_build_ui", lambda self: None)
    monkeypatch.setattr(ServiceManagerApp, "_apply_window_icon", lambda self: None)
    monkeypatch.setattr(ServiceManagerApp, "refresh_async", lambda self: None)
    monkeypatch.setattr(ServiceManagerApp, "_schedule_refresh", lambda self: None)

    app = ServiceManagerApp(root)

    assert root.protocol_calls == [("WM_DELETE_WINDOW", app.on_close_request)]


def test_has_background_activity_when_processes_or_tasks_enabled():
    app = ServiceManagerApp.__new__(ServiceManagerApp)
    app.processes = []
    app.task_records = []

    assert app._has_background_activity() is False

    app.task_records = [ScheduledTaskRecord("daily", "Ready", "", "", "")]
    assert app._has_background_activity() is True

    app.task_records = [ScheduledTaskRecord("daily", "Disabled", "", "", "")]
    app.processes = [ProcessRecord(10, 1, "python.exe", "", "python run_briefing.py")]
    assert app._has_background_activity() is True


def test_close_request_without_background_exits_immediately():
    class FakeRoot:
        def __init__(self):
            self.destroyed = False
            self.iconified = False

        def destroy(self):
            self.destroyed = True

        def iconify(self):
            self.iconified = True

    app = ServiceManagerApp.__new__(ServiceManagerApp)
    app.root = FakeRoot()
    app.processes = []
    app.task_records = [ScheduledTaskRecord("daily", "Disabled", "", "", "")]
    app._ask_close_action = lambda: "shutdown"

    app.on_close_request()

    assert app.root.destroyed is True
    assert app.root.iconified is False


def test_close_request_can_minimize_to_taskbar():
    class FakeRoot:
        def __init__(self):
            self.destroyed = False
            self.iconified = False

        def destroy(self):
            self.destroyed = True

        def iconify(self):
            self.iconified = True

    logs = []
    app = ServiceManagerApp.__new__(ServiceManagerApp)
    app.root = FakeRoot()
    app.processes = [ProcessRecord(10, 1, "python.exe", "", "python run_briefing.py")]
    app.task_records = []
    app._ask_close_action = lambda: "minimize"
    app._append_log = logs.append

    app.on_close_request()

    assert app.root.iconified is True
    assert app.root.destroyed is False
    assert logs == ["窗口已最小化到任务栏，后台服务继续运行。"]


def test_close_request_can_shutdown_service_and_exit(monkeypatch):
    class FakeRoot:
        def __init__(self):
            self.destroyed = False
            self.iconified = False

        def destroy(self):
            self.destroyed = True

        def iconify(self):
            self.iconified = True

    disabled_values = []
    stopped_pids = []
    logs = []

    def fake_stop_process_tree(pids):
        stopped_pids.extend(pids)
        return manager.StopResult(stopped=list(pids), failed={})

    monkeypatch.setattr(manager, "set_briefing_tasks_enabled", disabled_values.append)
    monkeypatch.setattr(manager, "stop_process_tree", fake_stop_process_tree)

    app = ServiceManagerApp.__new__(ServiceManagerApp)
    app.root = FakeRoot()
    app.processes = [ProcessRecord(10, 1, "python.exe", "", "python run_briefing.py")]
    app.task_records = [ScheduledTaskRecord("daily", "Ready", "", "", "")]
    app._ask_close_action = lambda: "shutdown"
    app._append_log = logs.append

    app.on_close_request()

    assert disabled_values == [False]
    assert stopped_pids == [10]
    assert app.root.destroyed is True
    assert app.root.iconified is False
    assert "定时服务已停用" in logs
    assert "已停止 PID: 10" in logs


def test_next_run_time_picks_first_available_task_time():
    app = ServiceManagerApp.__new__(ServiceManagerApp)
    app.task_records = [
        ScheduledTaskRecord("a", "Disabled", "", "", ""),
        ScheduledTaskRecord("b", "Ready", "2026/08/28 15:00:00", "", ""),
    ]

    assert app._next_run_time() == "2026/08/28 15:00:00"


def test_overview_items_report_configuration_state():
    class FakeVar:
        def get(self):
            return "连接正常"

    app = ServiceManagerApp.__new__(ServiceManagerApp)
    app.processes = []
    app.task_records = [ScheduledTaskRecord("daily", "Ready", "2026/08/28 09:00:00", "", "0")]
    app.settings = {
        "recipients": ["desk@example.com"],
        "stocks": [{"full_code": "600000.SS", "enabled": True}],
        "smtp": {
            "host": "smtp.example.com",
            "user": "desk@example.com",
            "auth_code": "secret",
        },
        "llm_api": {
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-test-key",
            "model": "gpt-test",
        },
    }
    app.api_test_status = FakeVar()

    items = app._overview_items()

    assert ("邮箱配置", "正常", "发件邮箱已配置，收件人 1 个") in items
    assert ("API 配置", "正常", "gpt-test") in items


def test_api_background_error_restores_test_button():
    class FakeVar:
        def __init__(self):
            self.value = ""

        def set(self, value):
            self.value = value

    class FakeButton:
        def __init__(self):
            self.state = "disabled"

        def configure(self, **kwargs):
            self.state = kwargs["state"]

    app = ServiceManagerApp.__new__(ServiceManagerApp)
    app.api_test_status = FakeVar()
    app.api_test_button = FakeButton()
    app._append_log = lambda message: None
    app._sync_overview = lambda: None

    app._after_background_error("测试 API 连接", "boom")

    assert app.api_test_status.value == "连接失败"
    assert app.api_test_button.state == "normal"


def test_saving_unchanged_api_settings_keeps_successful_test_status(monkeypatch):
    class FakeVar:
        def __init__(self, value=""):
            self.value = value

        def get(self):
            return self.value

        def set(self, value):
            self.value = value

    app = ServiceManagerApp.__new__(ServiceManagerApp)
    app.settings = {
        "llm_api": {
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-test-key",
            "model": "gpt-test",
        }
    }
    app.api_vars = {
        "base_url": FakeVar("https://api.example.com/v1"),
        "api_key": FakeVar("sk-test-key"),
        "model": FakeVar("gpt-test"),
    }
    app.api_key_hint = FakeVar()
    app.api_test_status = FakeVar("连接正常")
    app._sync_recipient_list = lambda: None
    app._sync_stock_tree = lambda: None
    app._sync_schedule_table = lambda: None
    app._sync_smtp_widgets = lambda: None
    app._sync_overview = lambda: None
    app._append_log = lambda _message: None
    monkeypatch.setattr(manager.settings_store, "save_settings", lambda settings: settings)

    app.save_api_settings()

    assert app.api_test_status.value == "连接正常"


def test_saving_changed_api_settings_requires_retest(monkeypatch):
    class FakeVar:
        def __init__(self, value=""):
            self.value = value

        def get(self):
            return self.value

        def set(self, value):
            self.value = value

    app = ServiceManagerApp.__new__(ServiceManagerApp)
    app.settings = {
        "llm_api": {
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-test-key",
            "model": "gpt-old",
        }
    }
    app.api_vars = {
        "base_url": FakeVar("https://api.example.com/v1"),
        "api_key": FakeVar("sk-test-key"),
        "model": FakeVar("gpt-new"),
    }
    app.api_key_hint = FakeVar()
    app.api_test_status = FakeVar("连接正常")
    app._sync_recipient_list = lambda: None
    app._sync_stock_tree = lambda: None
    app._sync_schedule_table = lambda: None
    app._sync_smtp_widgets = lambda: None
    app._sync_overview = lambda: None
    app._append_log = lambda _message: None
    monkeypatch.setattr(manager.settings_store, "save_settings", lambda settings: settings)

    app.save_api_settings()

    assert app.api_test_status.value == "未测试"

def test_build_briefing_command_supports_github_trending_mode():
    command = build_briefing_command("github", send=True)

    assert "--mode" in command
    assert "github" in command
    assert "--no-send" not in command

    preview = build_briefing_command("github", send=False)

    assert preview[-1] == "--no-send"


def test_build_briefing_task_action_supports_github_trending_mode():
    action = build_briefing_task_action("github")

    assert action.arguments.endswith("--mode github")




def test_autostart_registers_then_enables_tasks(monkeypatch):
    calls = []
    app = ServiceManagerApp.__new__(ServiceManagerApp)
    app._write_startup_log = lambda _message: None
    app._safe_log = lambda _message: None
    monkeypatch.setattr(manager, "register_briefing_tasks", lambda: calls.append("register"))
    monkeypatch.setattr(manager, "set_briefing_tasks_enabled", lambda enabled: calls.append(("enabled", enabled)))

    app._enable_tasks_for_autostart()

    assert calls == ["register", ("enabled", True)]


def test_autostart_survives_task_registration_failure(monkeypatch):
    messages = []
    app = ServiceManagerApp.__new__(ServiceManagerApp)
    app._write_startup_log = messages.append
    app._safe_log = messages.append

    def boom():
        raise RuntimeError("no permission")

    monkeypatch.setattr(manager, "register_briefing_tasks", boom)
    monkeypatch.setattr(manager, "set_briefing_tasks_enabled", lambda enabled: None)

    app._enable_tasks_for_autostart()

    assert any("自动启用定时服务失败" in message for message in messages)
def test_github_task_name_is_registered_for_service_toggles():
    assert "GitHub每日推送" in manager.BRIEFING_TASK_NAMES
