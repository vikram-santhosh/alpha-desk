"""Temporary DB isolation for backtesting.

Patches all DB_PATH references to temp files so production data
is never touched during backtest runs.
"""

import shutil
import tempfile
from pathlib import Path

from src.utils.logger import get_logger

log = get_logger(__name__)


class TempDBContext:
    """Patches all DB_PATH references to temp files. Restores on exit."""

    def __init__(self):
        self._tmpdir = tempfile.mkdtemp(prefix="alphadesk_backtest_")
        self._originals: dict[str, Path] = {}

    def __enter__(self):
        import src.advisor.memory as mem_mod
        import src.shared.agent_bus as bus_mod
        import src.shared.cost_tracker as cost_mod

        self._originals = {
            "memory": mem_mod.DB_PATH,
            "bus": bus_mod.DB_PATH,
            "cost": cost_mod.DB_PATH,
        }

        mem_mod.DB_PATH = Path(self._tmpdir) / "advisor_memory.db"
        bus_mod.DB_PATH = Path(self._tmpdir) / "agent_bus.db"
        cost_mod.DB_PATH = Path(self._tmpdir) / "cost_tracker.db"

        log.info("Temp DB dir: %s", self._tmpdir)
        return self

    def __exit__(self, *args):
        import src.advisor.memory as mem_mod
        import src.shared.agent_bus as bus_mod
        import src.shared.cost_tracker as cost_mod

        mem_mod.DB_PATH = self._originals["memory"]
        bus_mod.DB_PATH = self._originals["bus"]
        cost_mod.DB_PATH = self._originals["cost"]

        try:
            shutil.rmtree(self._tmpdir)
            log.info("Cleaned up temp DB dir: %s", self._tmpdir)
        except Exception as e:
            log.warning("Could not clean up %s: %s", self._tmpdir, e)

    @property
    def tmpdir(self) -> str:
        return self._tmpdir
