"""MCP service -- manages global MCP server processes.

All MCP servers (built-in and third-party) run as long-lived SSE processes,
started once on daemon boot and shared across all concurrent runs.  The bridge
extension (mcp-bridge.ts) connects to them over HTTP/SSE.

Replaces the old BrowserService with a single, uniform lifecycle manager.
"""

import logging
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("llmflows.mcp")

_LLMFLOWS_DIR = Path.home() / ".llmflows"
_NODE_MODULES = _LLMFLOWS_DIR / "node_modules"
_TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"

_SERVER_READY_TIMEOUT = 30  # seconds to wait for SSE server to start
_HEALTH_CHECK_INTERVAL = 60  # seconds between health checks


@dataclass
class _ServerInstance:
    server_id: str
    proc: subprocess.Popen
    port: int
    pid: int
    url: str
    started_at: float = field(default_factory=time.time)


class McpService:
    """Manages all MCP servers as long-running global SSE processes."""

    def __init__(self) -> None:
        self._instances: dict[str, _ServerInstance] = {}
        self._lock = threading.Lock()

    def start_all_enabled(self) -> None:
        """Start every enabled McpConnector. Called on daemon boot."""
        from ..db.database import get_session
        from ..db.models import McpConnector
        from ..config import load_system_config

        config = load_system_config()
        mcp_config = config.get("mcp", {})
        if not mcp_config.get("enabled", True):
            logger.info("MCP globally disabled, skipping server startup")
            return

        port_range_start = mcp_config.get("port_range_start", 19100)

        session = get_session()
        try:
            connectors = session.query(McpConnector).filter_by(enabled=True).all()
            for i, conn in enumerate(connectors):
                port = conn.port or (port_range_start + i)
                if conn.port is None:
                    conn.port = port
                    session.commit()
                try:
                    self.start_server(conn, port)
                except Exception:
                    logger.exception("Failed to start MCP server '%s'", conn.server_id)
        finally:
            session.close()

    def start_server(self, connector, port: Optional[int] = None) -> _ServerInstance:
        """Start a single MCP server process."""
        server_id = connector.server_id
        with self._lock:
            existing = self._instances.get(server_id)
            if existing and existing.proc.poll() is None:
                return existing

        if port is None:
            port = connector.port or 19100

        command = connector.command
        if connector.builtin:
            script = _TOOLS_DIR / command.split()[-1]
            tsx_bin = _NODE_MODULES / ".bin" / "tsx"
            cmd = [str(tsx_bin), str(script), "--port", str(port)]
        else:
            cmd = [*command.split(), "--port", str(port)]

        env_vars = {
            **os.environ,
            "NODE_PATH": str(_NODE_MODULES),
            "PORT": str(port),
        }
        for k, v in connector.get_env().items():
            env_vars[k] = str(v)
        for k, v in connector.get_credentials().items():
            env_vars[k] = str(v)

        logger.info("Starting MCP server '%s' on port %d: %s", server_id, port, " ".join(cmd))

        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env_vars,
            start_new_session=True,
        )

        url = f"http://localhost:{port}"
        self._wait_for_ready(proc, server_id, url)

        inst = _ServerInstance(
            server_id=server_id,
            proc=proc,
            port=port,
            pid=proc.pid,
            url=url,
        )
        with self._lock:
            self._instances[server_id] = inst

        logger.info("MCP server '%s' started (pid=%d, url=%s)", server_id, proc.pid, url)
        return inst

    def stop_server(self, server_id: str) -> None:
        """Stop a specific MCP server."""
        with self._lock:
            inst = self._instances.pop(server_id, None)
        if inst:
            self._kill(inst)

    def restart_server(self, server_id: str) -> Optional[_ServerInstance]:
        """Restart a server by stopping and re-reading config from DB."""
        self.stop_server(server_id)

        from ..db.database import get_session
        from ..db.models import McpConnector

        session = get_session()
        try:
            connector = session.query(McpConnector).filter_by(server_id=server_id).first()
            if connector and connector.enabled:
                return self.start_server(connector)
        finally:
            session.close()
        return None

    def get_endpoint(self, server_id: str) -> Optional[str]:
        """Return the SSE URL for a running server, or None."""
        with self._lock:
            inst = self._instances.get(server_id)
            if inst and inst.proc.poll() is None:
                return inst.url
        return None

    def get_endpoints(self, server_ids: list[str]) -> list[dict]:
        """Return [{server_id, url}] for the requested servers that are running."""
        result = []
        with self._lock:
            for sid in server_ids:
                inst = self._instances.get(sid)
                if inst and inst.proc.poll() is None:
                    result.append({"server_id": sid, "url": inst.url})
        return result

    def is_running(self, server_id: str) -> bool:
        with self._lock:
            inst = self._instances.get(server_id)
            return bool(inst and inst.proc.poll() is None)

    def get_status(self) -> dict[str, dict]:
        """Return status info for all tracked servers."""
        with self._lock:
            return {
                sid: {
                    "running": inst.proc.poll() is None,
                    "pid": inst.pid,
                    "port": inst.port,
                    "url": inst.url,
                    "uptime_seconds": int(time.time() - inst.started_at),
                }
                for sid, inst in self._instances.items()
            }

    def release_session(self, run_id: str, server_ids: Optional[list[str]] = None) -> None:
        """Tell stateful servers to close the session for a run.

        Sends an HTTP request to the server's release endpoint.
        Servers that don't support sessions simply ignore it.
        """
        import urllib.request
        import urllib.error

        targets = server_ids or list(self._instances.keys())
        for sid in targets:
            url = self.get_endpoint(sid)
            if not url:
                continue
            try:
                req = urllib.request.Request(
                    f"{url}/session/{run_id}",
                    method="DELETE",
                )
                urllib.request.urlopen(req, timeout=5)
            except (urllib.error.URLError, OSError):
                pass

    def health_check(self) -> list[str]:
        """Check all tracked servers, restart any that have crashed.

        Returns list of server_ids that were restarted.
        """
        restarted = []
        with self._lock:
            crashed = [
                sid for sid, inst in self._instances.items()
                if inst.proc.poll() is not None
            ]
        for sid in crashed:
            logger.warning("MCP server '%s' has crashed, restarting...", sid)
            inst = self.restart_server(sid)
            if inst:
                restarted.append(sid)
            else:
                logger.error("Failed to restart MCP server '%s'", sid)
        return restarted

    def stop_all(self) -> None:
        """Kill all MCP servers (daemon shutdown)."""
        with self._lock:
            instances = list(self._instances.items())
            self._instances.clear()
        for server_id, inst in instances:
            self._kill(inst)
        logger.info("All MCP servers stopped")

    @staticmethod
    def _wait_for_ready(proc: subprocess.Popen, server_id: str, url: str) -> None:
        """Wait until the SSE server responds or the process exits."""
        import urllib.request
        import urllib.error

        deadline = time.time() + _SERVER_READY_TIMEOUT
        while time.time() < deadline:
            if proc.poll() is not None:
                stderr = (proc.stderr.read() if proc.stderr else b"").decode(errors="replace")
                raise RuntimeError(
                    f"MCP server '{server_id}' exited (code={proc.returncode}): {stderr[:500]}"
                )
            try:
                urllib.request.urlopen(f"{url}/sse", timeout=2)
                return
            except (urllib.error.URLError, OSError):
                time.sleep(0.5)

        proc.kill()
        raise RuntimeError(
            f"MCP server '{server_id}' did not become ready within {_SERVER_READY_TIMEOUT}s"
        )

    @staticmethod
    def _kill(inst: _ServerInstance) -> None:
        """Terminate an MCP server process."""
        try:
            os.killpg(os.getpgid(inst.pid), signal.SIGTERM)
            inst.proc.wait(timeout=5)
            logger.info("MCP server '%s' stopped (pid=%d)", inst.server_id, inst.pid)
        except ProcessLookupError:
            pass
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(inst.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            logger.warning("MCP server '%s' killed (SIGKILL, pid=%d)", inst.server_id, inst.pid)
        except Exception:
            logger.exception("Error stopping MCP server '%s'", inst.server_id)
