"""Tests for the upgrade service and Telegram /upgrade command."""

import asyncio
import signal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llmflows.services.upgrade import (
    _build_upgrade_cmd,
    _detect_installer,
    _get_installed_version,
    kill_ui_processes,
    pip_upgrade,
    trigger_daemon_reexec,
)


class TestDetectInstaller:

    def test_uv(self):
        with patch("llmflows.services.upgrade.sys") as mock_sys:
            mock_sys.prefix = "/Users/me/.local/share/uv/tools/llmflows"
            assert _detect_installer() == "uv"

    def test_pipx(self):
        with patch("llmflows.services.upgrade.sys") as mock_sys:
            mock_sys.prefix = "/Users/me/.local/pipx/venvs/llmflows"
            assert _detect_installer() == "pipx"

    def test_pip_fallback(self):
        with patch("llmflows.services.upgrade.sys") as mock_sys:
            mock_sys.prefix = "/Users/me/venv"
            assert _detect_installer() == "pip"


class TestBuildUpgradeCmd:

    @patch("llmflows.services.upgrade._detect_installer", return_value="uv")
    @patch("llmflows.services.upgrade.shutil.which", return_value="/usr/local/bin/uv")
    def test_uv_cmd(self, _which, _det):
        cmd = _build_upgrade_cmd()
        assert cmd[:2] == ["/usr/local/bin/uv", "tool"]
        assert "upgrade" in cmd
        assert "llmflows" in cmd

    @patch("llmflows.services.upgrade._detect_installer", return_value="pipx")
    @patch("llmflows.services.upgrade.shutil.which", return_value="/usr/local/bin/pipx")
    def test_pipx_cmd(self, _which, _det):
        cmd = _build_upgrade_cmd()
        assert cmd == ["/usr/local/bin/pipx", "upgrade", "llmflows"]


class TestPipUpgrade:
    """pip_upgrade runs the appropriate upgrade command."""

    @patch("llmflows.services.upgrade._get_installed_version", return_value="1.0.0")
    @patch("llmflows.services.upgrade.subprocess.run")
    @patch("llmflows.services.upgrade._build_upgrade_cmd", return_value=["uv", "tool", "upgrade", "llmflows"])
    def test_successful_upgrade(self, _cmd, mock_run, _ver):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="Successfully installed llmflows-1.0.0\n", stderr=""
        )

        success, old_ver, new_ver, output = pip_upgrade()

        assert success is True
        assert new_ver == "1.0.0"
        assert "Successfully installed" in output

    @patch("llmflows.services.upgrade._get_installed_version", return_value="0.21.0")
    @patch("llmflows.services.upgrade.subprocess.run")
    @patch("llmflows.services.upgrade._build_upgrade_cmd", return_value=["uv", "tool", "upgrade", "llmflows"])
    def test_failed_upgrade(self, _cmd, mock_run, _ver):
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="ERROR: No matching distribution"
        )

        success, old_ver, new_ver, output = pip_upgrade()

        assert success is False
        assert "No matching distribution" in output

    @patch("llmflows.services.upgrade.subprocess.run")
    @patch("llmflows.services.upgrade._build_upgrade_cmd", return_value=["uv", "tool", "upgrade", "llmflows"])
    def test_timeout(self, _cmd, mock_run):
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="uv", timeout=120)

        success, old_ver, new_ver, output = pip_upgrade()

        assert success is False
        assert "timed out" in output


class TestGetInstalledVersion:

    @patch("llmflows.services.upgrade.version", return_value="0.22.0")
    def test_reads_from_metadata(self, _ver):
        assert _get_installed_version("0.21.0") == "0.22.0"

    @patch("llmflows.services.upgrade.version", side_effect=Exception("oops"))
    def test_fallback_on_error(self, _ver):
        assert _get_installed_version("0.21.0") == "0.21.0"


class TestKillUIProcesses:

    @patch("llmflows.services.upgrade.os.kill")
    @patch("llmflows.services.upgrade.os.getpid", return_value=100)
    @patch("llmflows.services.upgrade.os.getuid", return_value=501)
    @patch("llmflows.services.upgrade.subprocess.check_output")
    def test_kills_other_ui_processes(self, mock_pgrep, _uid, _pid, mock_kill):
        mock_pgrep.return_value = "200\n300\n100\n"

        killed = kill_ui_processes()

        assert 200 in killed
        assert 300 in killed
        assert 100 not in killed  # excludes self
        assert mock_kill.call_count == 2

    @patch("llmflows.services.upgrade.subprocess.check_output")
    def test_no_processes(self, mock_pgrep):
        import subprocess
        mock_pgrep.side_effect = subprocess.CalledProcessError(1, "pgrep")

        killed = kill_ui_processes()

        assert killed == []


class TestTriggerDaemonReexec:

    @patch("llmflows.services.upgrade.os.kill")
    @patch("llmflows.services.upgrade.os.getpid", return_value=42)
    def test_sends_sigusr2(self, _pid, mock_kill):
        trigger_daemon_reexec()
        mock_kill.assert_called_once_with(42, signal.SIGUSR2)


class TestDaemonReexecSignal:
    """Daemon._handle_reexec sets the re-exec flag and stops the loop."""

    def test_handle_reexec_sets_flag(self):
        from llmflows.services.daemon import Daemon

        with patch("llmflows.services.daemon.load_system_config", return_value={
            "daemon": {"poll_interval_seconds": 5, "run_timeout_minutes": 30},
        }):
            d = Daemon()
            d.running = True

            d._handle_reexec(signal.SIGUSR2, None)

            assert d._reexec is True
            assert d.running is False


class TestUpgradeCLI:
    """The upgrade CLI command orchestrates pip, daemon, and UI."""

    @patch("llmflows.services.upgrade.start_ui_background", return_value=999)
    @patch("llmflows.services.upgrade.restart_daemon_via_cli", return_value=(True, "Daemon started (pid 123)"))
    @patch("llmflows.services.upgrade.kill_ui_processes", return_value=[555])
    @patch("llmflows.services.upgrade.pip_upgrade", return_value=(True, "0.21.0", "0.22.0", "ok"))
    def test_full_upgrade(self, _pip, _kill, _daemon, _ui):
        from click.testing import CliRunner
        from llmflows.cli.upgrade import upgrade

        result = CliRunner().invoke(upgrade)

        assert result.exit_code == 0
        assert "0.21.0" in result.output
        assert "0.22.0" in result.output
        assert "Upgrade complete" in result.output

    @patch("llmflows.services.upgrade.pip_upgrade", return_value=(False, "0.21.0", "0.21.0", "ERROR"))
    def test_failed_upgrade_exits(self, _pip):
        from click.testing import CliRunner
        from llmflows.cli.upgrade import upgrade

        result = CliRunner().invoke(upgrade)

        assert result.exit_code != 0


class TestTelegramUpgradeCommand:
    """The Telegram /upgrade handler upgrades, restarts, and triggers re-exec."""

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    @pytest.fixture
    def tg_bot(self):
        with patch.dict("sys.modules", {
            "telegram": MagicMock(),
            "telegram.ext": MagicMock(),
            "telegram.request": MagicMock(),
        }):
            from llmflows.services.gateway.telegram import TelegramBot
            bot = TelegramBot.__new__(TelegramBot)
            bot.config = {"bot_token": "fake"}
            bot.session_factory = MagicMock()
            bot.bot_token = "fake"
            bot.allowed_ids = set()
            bot._active_chats = set()
            bot._awaiting_response = {}
            bot._notification_photos = {}
            bot._pending_run_vars = {}
            bot._app = MagicMock()
            bot._loop = MagicMock()
        return bot

    @patch("llmflows.services.upgrade.trigger_daemon_reexec")
    @patch("llmflows.services.upgrade.start_ui_background", return_value=999)
    @patch("llmflows.services.upgrade.kill_ui_processes", return_value=[555])
    @patch("llmflows.services.upgrade.pip_upgrade", return_value=(True, "0.21.0", "0.22.0", "ok"))
    def test_upgrade_success(self, _pip, _kill, _ui, mock_reexec, tg_bot):
        update = MagicMock()
        update.effective_chat.id = 123
        update.message.reply_text = AsyncMock()

        self._run(tg_bot._handle_upgrade_command(update, None))

        calls = update.message.reply_text.call_args_list
        assert any("0.22.0" in str(c) for c in calls)
        mock_reexec.assert_called_once()

    @patch("llmflows.services.upgrade.pip_upgrade", return_value=(False, "0.21.0", "0.21.0", "ERROR"))
    def test_upgrade_failure(self, _pip, tg_bot):
        update = MagicMock()
        update.effective_chat.id = 123
        update.message.reply_text = AsyncMock()

        self._run(tg_bot._handle_upgrade_command(update, None))

        calls = update.message.reply_text.call_args_list
        assert any("failed" in str(c).lower() for c in calls)

    @patch("llmflows.services.upgrade.pip_upgrade", return_value=(True, "0.21.0", "0.21.0", "ok"))
    def test_already_latest(self, _pip, tg_bot):
        update = MagicMock()
        update.effective_chat.id = 123
        update.message.reply_text = AsyncMock()

        self._run(tg_bot._handle_upgrade_command(update, None))

        calls = update.message.reply_text.call_args_list
        assert any("latest" in str(c).lower() for c in calls)
