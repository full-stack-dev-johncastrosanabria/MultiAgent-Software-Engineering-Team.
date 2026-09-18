"""Isolate every test's view of Settings and Langfuse from the operator's real
.env and shell environment (M-24), without disabling any code -- the telemetry
row needs the trace-construction code to still run against an injected fake
client (``LangfuseTracer(client=...)``, see tests/integration/test_observability.py).

This file also owns the omission budget: a ``pytest_collection_modifyitems``
hook counts the items carrying the ``needs_docker`` skip mark and publishes the
tally through the ``needs_docker_budget`` fixture, which
tests/unit/test_docker_skip_budget.py asserts against.
"""

import pytest
from _docker import needs_docker

from engineering_team.config import Settings

NEEDS_DOCKER_REASON = needs_docker.mark.kwargs["reason"]

_DOCKER_SKIP_BUDGET: pytest.StashKey[dict[str, object]] = pytest.StashKey()


@pytest.fixture(autouse=True)
def _isolated_settings_and_langfuse_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Stops Settings() from reading the repository's real .env FILE. This is the
    # load-bearing line: pydantic-settings reads that file directly, never
    # through os.environ, so the delenv loop below is a second, independent
    # layer and not a substitute for it.
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    # Belt and suspenders against operator shell pollution, and the only defense
    # for the two paths that read os.environ directly instead of through
    # Settings (observability/evaluation.py's offline directory, and
    # RUN_LIVE_MULTIMODEL).
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    monkeypatch.delenv("RUN_LIVE_MULTIMODEL", raising=False)
    monkeypatch.setenv("DELIVERY_BACKEND", "none")


def _item_path(item: pytest.Item, config: pytest.Config) -> str:
    try:
        return item.path.relative_to(config.rootpath).as_posix()
    except ValueError:
        return item.path.as_posix()


def pytest_collection_modifyitems(
    session: pytest.Session, config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Record which collected items carry the needs_docker skip mark.

    The count is per file and the collected files travel with it, because the
    repository's pinned regression command deliberately collects only part of
    the suite: the guard test can then check what was actually collected
    instead of asserting a whole-suite total the run never had a chance to see.
    """

    marked_by_file: dict[str, int] = {}
    collected_files: set[str] = set()
    for item in items:
        path = _item_path(item, config)
        collected_files.add(path)
        for mark in item.iter_markers("skipif"):
            if mark.kwargs.get("reason") == NEEDS_DOCKER_REASON:
                marked_by_file[path] = marked_by_file.get(path, 0) + 1
                break
    config.stash[_DOCKER_SKIP_BUDGET] = {
        "marked_by_file": marked_by_file,
        "collected_files": collected_files,
    }


@pytest.fixture
def needs_docker_budget(pytestconfig: pytest.Config) -> dict[str, object]:
    return pytestconfig.stash[_DOCKER_SKIP_BUDGET]
