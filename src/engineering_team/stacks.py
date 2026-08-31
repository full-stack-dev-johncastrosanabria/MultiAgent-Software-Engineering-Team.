"""What "run the tests" means in each ecosystem.

The third of the three questions `mcp/quality.py` used to answer at once (ADR 3):
not what quality is, and not where code executes, but which commands to run. A
profile is attached to a component rather than a repository, because none of the
repositories this system targets is a single stack (ADR 4).

Images are pinned by digest (ADR 2). Every one of them is the Debian base the
official images share, so profiles reuse layers instead of each pulling its own
world.
"""

from __future__ import annotations

from dataclasses import dataclass

# Replaced with whatever `CommandRunner.prepare_environment` returned. Only the
# Python profile uses it: `mvn test` is the command, with no module to import.
INTERPRETER = "{interpreter}"

# Replaced with the runner's environment root. Toolchain caches must live there:
# containers run as the host user with HOME set to a directory they cannot write,
# and each command gets a fresh container, so anything written outside the shared
# volume is gone before the next phase starts.
ENVIRONMENT = "{environment}"

_Template = tuple[str, ...] | None


@dataclass(frozen=True)
class StackProfile:
    """One ecosystem: which image carries its toolchain, and what to run."""

    name: str
    image: str
    test_template: tuple[str, ...]
    lint_template: _Template = None
    build_template: _Template = None
    install_template: _Template = None
    environment: tuple[tuple[str, str], ...] = ()
    """Environment the toolchain needs, with ENVIRONMENT expanded."""
    test_needs_network: bool = False
    """Whether the test phase resolves dependencies while it runs.

    Python does not: QualityMCP installs from a hashed lock first and the test
    phase is offline, which is the stronger position. Maven, dotnet and npm
    resolve during the build they are asked for. This was measured, not assumed --
    `dependency:go-offline` completes and a subsequent offline `mvn test` still
    fails, so pretending a restore phase makes them offline would be a claim the
    evidence does not support. The cache lives on the shared volume, so the
    network is used on the first run and largely idle afterwards.
    """

    def _expand(
        self, template: _Template, interpreter: str, environment: str
    ) -> list[str] | None:
        if template is None:
            return None
        return [
            part.replace(INTERPRETER, interpreter).replace(ENVIRONMENT, environment)
            for part in template
        ]

    def test_command(self, interpreter: str, environment: str = "") -> list[str]:
        expanded = self._expand(self.test_template, interpreter, environment)
        assert expanded is not None
        return expanded

    def lint_command(self, interpreter: str, environment: str = "") -> list[str] | None:
        return self._expand(self.lint_template, interpreter, environment)

    def build_command(self, interpreter: str, environment: str = "") -> list[str] | None:
        return self._expand(self.build_template, interpreter, environment)

    def install_command(
        self, interpreter: str, environment: str = ""
    ) -> list[str] | None:
        """Dependencies, where an explicit step is the right place to fetch them."""
        return self._expand(self.install_template, interpreter, environment)

    def env(self, environment: str = "") -> tuple[tuple[str, str], ...]:
        """The declared environment, with the runner's environment root filled in."""
        return tuple(
            (name, value.replace(ENVIRONMENT, environment))
            for name, value in self.environment
        )


PROFILES: dict[str, StackProfile] = {
    "python": StackProfile(
        name="python",
        image=(
            "python@sha256:"
            "7ce4b6dfe35e55397b7cda544f8a13f191b7ae28dc5aad71fe664dbc9bc2623f"
        ),
        # `-I` keeps the interpreter isolated from the environment it inherits.
        test_template=(INTERPRETER, "-I", "-m", "pytest"),
        lint_template=(INTERPRETER, "-I", "-m", "ruff", "check", "."),
        build_template=(INTERPRETER, "-I", "-m", "compileall", "."),
    ),
    "jvm": StackProfile(
        name="jvm",
        image=(
            "maven@sha256:"
            "8f6ac126f7810bb5549c4cd122d2bf0e9cda5bdeb0838aa928f09e779fd8bef8"
        ),
        test_template=(
            "mvn", "-B", "-q", f"-Dmaven.repo.local={ENVIRONMENT}/m2", "test",
        ),
        build_template=(
            "mvn", "-B", "-q", f"-Dmaven.repo.local={ENVIRONMENT}/m2",
            "-DskipTests", "package",
        ),
        test_needs_network=True,
    ),
    "dotnet": StackProfile(
        name="dotnet",
        image=(
            "mcr.microsoft.com/dotnet/sdk@sha256:"
            "e1ffd2a92ae84c1291bc1b6887501f8af98e6331e7af6d4c8d37168c5e87a64c"
        ),
        # The package path is an MSBuild property, but where the CLI writes its
        # first-run state is not: without DOTNET_CLI_HOME it tries to write to a
        # HOME the container user cannot write and throws before running anything.
        environment=(
            ("DOTNET_CLI_HOME", f"{ENVIRONMENT}/dotnet"),
            ("DOTNET_NOLOGO", "1"),
            ("DOTNET_CLI_TELEMETRY_OPTOUT", "1"),
        ),
        test_template=(
            "dotnet", "test", "--nologo", f"-p:RestorePackagesPath={ENVIRONMENT}/nuget",
        ),
        build_template=(
            "dotnet", "build", "--nologo", f"-p:RestorePackagesPath={ENVIRONMENT}/nuget",
        ),
        test_needs_network=True,
    ),
    "go": StackProfile(
        name="go",
        image=(
            "golang@sha256:"
            "167053a2bb901972bf2c1611f8f52c44d5fe7e762e5cab213708d82c421614db"
        ),
        # `./...` and not `.`: a Go module's tests live in every package under it.
        test_template=("go", "test", "./..."),
        build_template=("go", "build", "./..."),
        lint_template=("go", "vet", "./..."),
        environment=(("GOMODCACHE", f"{ENVIRONMENT}/gomod"), ("GOCACHE", f"{ENVIRONMENT}/gocache")),
        test_needs_network=True,
    ),
    "node": StackProfile(
        name="node",
        image=(
            "node@sha256:"
            "83f487e0a63425e5b4d146fb5e5be574bcbe1b7b843d3ebafdd95eaf7767a7e5"
        ),
        test_template=("npm", "test", "--silent"),
        lint_template=("npm", "run", "lint"),
        build_template=("npm", "run", "build"),
        # `ci` and not `install`: it fails on a lockfile that disagrees with the
        # manifest instead of quietly resolving something else.
        install_template=("npm", "ci", "--cache", f"{ENVIRONMENT}/npm"),
        test_needs_network=True,
    ),
}


def profile_for(stack: str) -> StackProfile:
    """The profile for a detected stack, or a refusal.

    Never a default. A component whose stack has no profile is a component
    nothing knows how to build, and guessing would run the wrong toolchain.
    """
    try:
        return PROFILES[stack]
    except KeyError:
        raise KeyError(f"no stack profile for {stack!r}") from None
