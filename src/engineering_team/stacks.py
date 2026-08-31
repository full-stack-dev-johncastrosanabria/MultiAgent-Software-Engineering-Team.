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

    def _expand(self, template: _Template, interpreter: str) -> list[str] | None:
        if template is None:
            return None
        return [interpreter if part is INTERPRETER else part for part in template]

    def test_command(self, interpreter: str) -> list[str]:
        expanded = self._expand(self.test_template, interpreter)
        assert expanded is not None
        return expanded

    def lint_command(self, interpreter: str) -> list[str] | None:
        return self._expand(self.lint_template, interpreter)

    def build_command(self, interpreter: str) -> list[str] | None:
        return self._expand(self.build_template, interpreter)

    def install_command(self, interpreter: str) -> list[str] | None:
        """Dependencies, where the test command does not fetch them itself.

        Maven and dotnet resolve on demand; npm needs an explicit install, and
        Python is installed by QualityMCP from a hashed lock where one exists.
        """
        return self._expand(self.install_template, interpreter)


PROFILES: dict[str, StackProfile] = {
    "python": StackProfile(
        name="python",
        image=(
            "python@sha256:"
            "16f75ad0fbc6c4883a8afd63b2d700c3cf68ccffc1aaeca5304ca0a3a908451f"
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
            "edf045813426842617b1667456ddec0026885146465e890b897655d877ba3386"
        ),
        test_template=("mvn", "-B", "-q", "test"),
        build_template=("mvn", "-B", "-q", "-DskipTests", "package"),
    ),
    "dotnet": StackProfile(
        name="dotnet",
        image=(
            "mcr.microsoft.com/dotnet/sdk@sha256:"
            "0e53453ccfc8ff2d51319fe80c678971c6d0f8008dff3565fa88e15840b69854"
        ),
        test_template=("dotnet", "test", "--nologo"),
        build_template=("dotnet", "build", "--nologo"),
    ),
    "node": StackProfile(
        name="node",
        image=(
            "node@sha256:"
            "4d676821dff059fd00d277ee4261ef34ea712317fed0737c03941481b5760c96"
        ),
        test_template=("npm", "test", "--silent"),
        lint_template=("npm", "run", "lint"),
        build_template=("npm", "run", "build"),
        # `ci` and not `install`: it fails on a lockfile that disagrees with the
        # manifest instead of quietly resolving something else.
        install_template=("npm", "ci"),
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
