"""Inferring the services a project needs when it does not declare them (ADR 5).

Five of the six repositories this system targets expect a database already
running on a developer's machine. Where a project ships a compose file that file
is the topology; this is what happens when it does not.

Two artefacts come out, and the difference matters. The run needs services on a
closed network with the project redirected onto them, because inside the run
`localhost` is the command's own container. A developer needs the opposite: ports
on localhost, exactly where their existing configuration already looks, so
`docker compose up -d` makes their tests pass without touching their code. The
second is worth proposing as a pull request; the first never leaves the run.

Configuration is read by looking for connection URIs, not by parsing. A regex
over text finds `jdbc:postgresql://host:port/name` in YAML, properties files and
JSON alike, and avoids reintroducing a YAML parser that finding 2 removed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

RUN = "run"
DELIVERY = "delivery"


@dataclass(frozen=True, order=True)
class Dependency:
    """One service a project expects to be able to reach."""

    engine: str
    port: int
    database: str
    user: str
    password: str


@dataclass(frozen=True)
class Engine:
    """How to run one database engine, and how a project addresses it."""

    image: str
    port: int
    service: str
    environment: tuple[tuple[str, str], ...]
    init_directory: str | None
    jdbc_scheme: str | None
    healthcheck: str
    """How the engine says it is ready to accept connections.

    Required, not optional: `--wait` without a healthcheck waits for the
    container to be running, which for a database is several seconds before it
    can answer. ADR 5 says readiness is a health check and never a delay; a
    derived file that omits one silently breaks that."""


# Versions are an assumption: no project's configuration states one. Pinned by
# digest so a run stays reproducible, and stated in the generated file so the
# developer can see what was guessed on their behalf.
ENGINES: dict[str, Engine] = {
    "postgres": Engine(
        image=(
            "postgres@sha256:"
            "18cfe3ef5e6815560c98237d6216d1e5119702fb0f3894c8785dd58b8bbe5d73"
        ),
        port=5432,
        service="postgres",
        environment=(
            ("POSTGRES_DB", "{database}"),
            ("POSTGRES_USER", "{user}"),
            ("POSTGRES_PASSWORD", "{password}"),
        ),
        init_directory="/docker-entrypoint-initdb.d/",
        jdbc_scheme="postgresql",
        healthcheck="pg_isready -U {user} -d {database}",
    ),
    "mysql": Engine(
        image=(
            "mysql@sha256:"
            "b3b90af2a6552ae30c266fdb7d5dd55f3afb72404bb78d37fe8a23eb857fd3fb"
        ),
        port=3306,
        service="mysql",
        environment=(
            ("MYSQL_DATABASE", "{database}"),
            ("MYSQL_ROOT_PASSWORD", "{password}"),
        ),
        init_directory="/docker-entrypoint-initdb.d/",
        jdbc_scheme="mysql",
        healthcheck="mysqladmin ping -h 127.0.0.1 --silent",
    ),
    "mssql": Engine(
        image=(
            "mcr.microsoft.com/mssql/server@sha256:"
            "ba4c8329f48fb8f02e1416be6a930ebfd71268caee78aa985f3af4315e457c89"
        ),
        port=1433,
        service="mssql",
        # Published for linux/amd64 only: on Apple Silicon this is emulation, for
        # a service that starts on every run. Postgres and MySQL publish arm64,
        # so parity between the engines should not be promised.
        environment=(("ACCEPT_EULA", "Y"), ("MSSQL_SA_PASSWORD", "{password}")),
        init_directory=None,
        jdbc_scheme="sqlserver",
        healthcheck="/opt/mssql-tools18/bin/sqlcmd -C -S localhost -U sa -P $MSSQL_SA_PASSWORD -Q 'SELECT 1'",
    ),
    "mongo": Engine(
        image=(
            "mongo@sha256:"
            "b6421fd6d1c5ded6377b397d8983e2f82e2100dc5123332dcfda2065a472be5b"
        ),
        port=27017,
        service="mongo",
        environment=(),
        # Mongo runs .js and .sh here, not .sql, so a project's schema script is
        # not assumed to apply to it.
        init_directory=None,
        jdbc_scheme=None,
        # No double quotes: the probe is emitted inside a double-quoted YAML
        # scalar, and nesting them produced a file compose refused to parse.
        healthcheck="mongosh --quiet --eval 'db.adminCommand({{ping:1}}).ok'",
    ),
}

_URI = re.compile(
    r"\b(?:jdbc:)?(?P<engine>postgresql|postgres|mysql|mariadb|mongodb)"
    r"(?:\+srv)?://(?P<host>[^/:\s\"'}]+)(?::(?P<port>\d+))?"
    r"(?:/(?P<database>[A-Za-z0-9_.-]+))?"
)
_PAIRS = re.compile(
    r"\b(?P<key>Host|Server|Port|Database|Initial\s*Catalog|User\s*Id|Username|User|Uid|Password|Pwd)"
    r"\s*=\s*(?P<value>[^;\"']+)",
    re.IGNORECASE,
)
# Spring writes `username: ${VAR:default}`; the default is what the project uses.
_YAML_VALUE = re.compile(
    r"^\s*(?P<key>username|user|password)\s*:\s*(?P<value>\S+)\s*$", re.MULTILINE
)
_PLACEHOLDER = re.compile(r"^\$\{[^:}]+:?(?P<default>[^}]*)\}$")
_ALIASES = {"postgresql": "postgres", "mariadb": "mysql", "mongodb": "mongo"}


def _unwrap(value: str) -> str:
    """Take the default out of a `${VAR:default}` placeholder."""
    match = _PLACEHOLDER.match(value.strip().strip("\"'"))
    return (match.group("default") if match else value).strip().strip("\"',")


def _without_comments(text: str) -> str:
    """Drop whole-line comments before looking for connection strings.

    A configuration file may explain a framework quirk by quoting a connection
    string -- one of these projects documents exactly that -- and an extractor
    reading prose invents a service the project does not use. Only leading `#`
    and `//` are removed: `//` also appears inside every URI here.
    """
    kept = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(("#", "//")):
            continue
        kept.append(line)
    return "\n".join(kept)


def _credentials(text: str) -> tuple[str, str]:
    user = password = ""
    for match in _YAML_VALUE.finditer(text):
        value = _unwrap(match.group("value"))
        if match.group("key") == "password":
            password = password or value
        else:
            user = user or value
    return user, password


def _dotnet_engine(pairs: dict[str, str]) -> str:
    """Which engine a .NET connection string means."""
    if "host" in pairs:
        return "postgres"
    port = (pairs.get("port") or "").strip()
    server = pairs.get("server", "")
    if port == "1433" or ",1433" in server:
        return "mssql"
    if port == "5432":
        return "postgres"
    return "mysql"


def extract_dependencies(sources: dict[str, str]) -> tuple[Dependency, ...]:
    """Find the services a project's configuration expects to reach.

    An empty result is an answer: a project on SQLite needs nothing started, and
    saying so is not a failure to infer.
    """
    found: dict[str, Dependency] = {}
    for text in (_without_comments(sources[name]) for name in sorted(sources)):
        pairs = {
            key.lower().replace(" ", ""): value.strip()
            for key, value in _PAIRS.findall(text)
        }
        yaml_user, yaml_password = _credentials(text)
        for match in _URI.finditer(text):
            engine = _ALIASES.get(match.group("engine"), match.group("engine"))
            engine_spec = ENGINES.get(engine)
            if engine_spec is None:
                continue
            database = (match.group("database") or "").split("?")[0]
            if not database:
                continue
            port = int(match.group("port") or engine_spec.port)
            user = pairs.get("username") or pairs.get("userid") or pairs.get("user") \
                or pairs.get("uid") or yaml_user
            password = pairs.get("password") or pairs.get("pwd") or yaml_password
            found.setdefault(
                engine, Dependency(engine, port, database, user, password)
            )
        if "host" in pairs or "server" in pairs:
            # A .NET connection string does not name its engine. `Host=` is the
            # Npgsql spelling; `Server=` is shared by MySQL and SQL Server, and
            # only the port separates them. `Data Source=` is SQLite -- a file,
            # so no service at all -- and is deliberately not matched above.
            engine = _dotnet_engine(pairs)
            database = pairs.get("database") or pairs.get("initialcatalog") or ""
            if database:
                found.setdefault(
                    engine,
                    Dependency(
                        engine,
                        int(pairs.get("port") or ENGINES[engine].port),
                        database,
                        pairs.get("username") or pairs.get("userid")
                        or pairs.get("user") or pairs.get("uid") or "",
                        pairs.get("password") or pairs.get("pwd") or "",
                    ),
                )
    return tuple(sorted(found.values()))


def derive_compose(
    dependencies: tuple[Dependency, ...],
    *,
    mode: str,
    init_script: str | None = None,
) -> str:
    """Render the services a project needs, for a run or for a developer.

    `run` closes the network and publishes nothing, because the run reaches the
    services by name. `delivery` publishes on localhost, where the project's own
    configuration already looks, and parameterises the credentials so no
    plaintext password is proposed into anyone's history.
    """
    if mode not in (RUN, DELIVERY):
        raise ValueError(f"unknown compose mode: {mode!r}")
    if not dependencies:
        return ""
    lines = [
        "# Generated by ASET from the connection strings this project already",
        "# declares. Engine versions are an assumption -- no configuration here",
        "# states one -- pinned by digest so a run stays reproducible.",
        "services:",
    ]
    for dependency in dependencies:
        engine = ENGINES[dependency.engine]
        lines += [f"  {engine.service}:", f"    image: {engine.image}"]
        if engine.environment:
            lines.append("    environment:")
            for name, template in engine.environment:
                if mode == DELIVERY and name.endswith(("PASSWORD", "USER")):
                    lines.append(f"      {name}: ${{{name}}}")
                else:
                    lines.append(
                        f"      {name}: "
                        + template.format(
                            database=dependency.database,
                            user=dependency.user or "aset",
                            password=dependency.password or "aset",
                        )
                    )
        # In delivery mode the credentials are variables, so the probe has to
        # read the container's own environment rather than the value inferred
        # today: a developer who changes POSTGRES_USER in their .env would
        # otherwise have a service that never reports healthy. `$$` is how a
        # literal `$` survives compose's own interpolation.
        probe = engine.healthcheck.format(
            database=dependency.database,
            user="$$POSTGRES_USER" if mode == DELIVERY and dependency.engine == "postgres"
            else (dependency.user or "aset"),
        )
        lines += [
            "    healthcheck:",
            f'      test: ["CMD-SHELL", "{probe}"]',
            "      interval: 2s",
            "      timeout: 5s",
            "      retries: 30",
            # A cold database image can take a while on its first start; the
            # retries above are the budget, not a fixed wait.
            "      start_period: 5s",
        ]
        if mode == DELIVERY:
            lines += ["    ports:", f'      - "{dependency.port}:{engine.port}"']
        if init_script and engine.init_directory:
            lines += [
                "    volumes:",
                f"      - ./{init_script}:{engine.init_directory}10-init.sql:ro",
            ]
    if mode == RUN:
        lines += ["networks:", "  default:", "    internal: true"]
    lines.append("")
    return "\n".join(lines)


def environment_variables_example(dependencies: tuple[Dependency, ...]) -> str:
    """The companion file for the delivery rendering, with no real secrets."""
    lines = ["# Copy to .env and fill in. Values are examples, not credentials."]
    for dependency in dependencies:
        for name, _ in ENGINES[dependency.engine].environment:
            if name.endswith("PASSWORD"):
                lines.append(f"{name}=change-me")
            elif name.endswith("USER"):
                lines.append(f"{name}={dependency.user or 'aset'}")
    lines.append("")
    return "\n".join(lines)


def environment_overrides(
    dependencies: tuple[Dependency, ...], stack: str
) -> tuple[tuple[str, str], ...]:
    """Point a component at the service instead of at localhost.

    Only variables the framework documents. Inventing one for an ecosystem that
    does not read it would look like configuration and do nothing.
    """
    overrides: list[tuple[str, str]] = []
    for dependency in dependencies:
        engine = ENGINES[dependency.engine]
        host = engine.service
        if stack == "jvm" and engine.jdbc_scheme:
            overrides.append((
                "SPRING_DATASOURCE_URL",
                f"jdbc:{engine.jdbc_scheme}://{host}:{engine.port}/{dependency.database}",
            ))
            if dependency.user:
                overrides.append(("SPRING_DATASOURCE_USERNAME", dependency.user))
            if dependency.password:
                overrides.append(("SPRING_DATASOURCE_PASSWORD", dependency.password))
        elif stack == "jvm" and dependency.engine == "mongo":
            overrides.append((
                "SPRING_DATA_MONGODB_URI",
                f"mongodb://{host}:{engine.port}/{dependency.database}",
            ))
        elif stack == "dotnet" and dependency.engine == "postgres":
            connection = (
                f"Host={host};Port={engine.port};Database={dependency.database};"
                f"Username={dependency.user};Password={dependency.password}"
            )
            overrides.append(("ConnectionStrings__Default", connection))
        elif stack == "dotnet" and dependency.engine == "mysql":
            connection = (
                f"server={host};port={engine.port};database={dependency.database};"
                f"user={dependency.user};password={dependency.password};"
            )
            overrides.append(("ConnectionStrings__DefaultConnection", connection))
    return tuple(overrides)
