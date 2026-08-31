"""The guardrail must block secrets without blocking ordinary code.

Found by running the system against a real repository: every stage that sends
repository content to a cloud provider died with "sensitive content is not
allowed in cloud context" on a file whose only offence was reading an
environment variable.
"""

from __future__ import annotations

import pytest

from engineering_team.guardrails.secrets import require_safe_cloud_context


def test_reading_an_environment_variable_is_not_a_secret() -> None:
    """`os.environ` contains the four characters `.env`, and the check looked for
    them as a substring. FlaskApiProduct's config.py uses it four times, so the
    Developer stage could not run against that repository at all — nor against
    most others, since this is how Python reads configuration."""
    require_safe_cloud_context('port = os.environ.get("PORT", "8000")')
    require_safe_cloud_context('os.environ["HOME"]')
    require_safe_cloud_context("value = os.environb.get(b'X')")


def test_mentioning_an_env_file_is_not_sending_one() -> None:
    """Naming the file is what real projects do: a comment about where
    configuration comes from, a .gitignore entry, a setup document. Refusing the
    mention blocked five files in one repository and the run with them."""
    for text in (
        "# las variables de entorno se cargan desde .env",
        "copy .env.example to .env before running",
        ".env\n.env.local\n",
    ):
        require_safe_cloud_context(text)


def test_the_contents_of_an_env_file_never_reach_a_prompt() -> None:
    """Two independent gates, neither of them this one: only an allowlist of
    source suffixes is readable, and .env is excluded by name on top of that."""
    from engineering_team.repository_evidence import (
        is_credential_path,
        safe_repository_path,
    )

    for path in (".env", ".env.example", ".env.production"):
        assert is_credential_path(path)
        assert safe_repository_path(path) is None


def test_a_credential_assignment_is_still_refused() -> None:
    for text in (
        'api_key = "sk-live-abcdef"',
        "password: hunter2",
        "ACCESS_TOKEN=ghp_realtokenvalue",
    ):
        with pytest.raises(ValueError):
            require_safe_cloud_context(text)


def test_a_real_projects_configuration_module_passes() -> None:
    """Verbatim shape of the file that blocked the run."""
    module = (
        "import os\n"
        "class Config:\n"
        "    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \\\n"
        "        'sqlite:///flask_api.db'\n"
        "    DEBUG = os.environ.get('FLASK_DEBUG', '0') == '1'\n"
    )
    require_safe_cloud_context(module)
