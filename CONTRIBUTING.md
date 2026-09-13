# Contributing to Telegram Agent Platform

Thanks for your interest in improving the project. This guide covers everything you
need to build, test, and extend the platform. By participating you agree to keep
discussions respectful and technical.

- [Development environment](#development-environment)
- [Running the test suite](#running-the-test-suite)
- [Architecture and layer rules](#architecture-and-layer-rules)
- [Adding a new AI provider](#adding-a-new-ai-provider)
- [Adding a new tool](#adding-a-new-tool)
- [Branch naming](#branch-naming)
- [Commit message convention](#commit-message-convention)
- [Pull request checklist](#pull-request-checklist)
- [Security](#security)

## Development environment

Requirements: **Python 3.12 or newer** and `git`. Windows, macOS and Linux are all
supported.

```bash
git clone https://github.com/h1ntz0/Agents-Telegram.git
cd Agents-Telegram
```

Create a virtual environment and install the package with its development extras:

```bash
# macOS / Linux
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[dev]"

# Windows (PowerShell)
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

`-e ".[dev]"` installs the project in editable mode together with `pytest`,
`pytest-asyncio` and `pytest-cov`.

Copy `.env.example` to `.env` and fill in your own credentials if you want to run the
agent locally. **Never commit `.env`** — the setup wizard writes it with `0600`
permissions and it is git-ignored.

## Running the test suite

Run the whole suite from the repository root:

```bash
# macOS / Linux
.venv/bin/python -m pytest -q

# Windows
.venv\Scripts\python.exe -m pytest -q
```

`python -m pytest` guarantees you are using the interpreter of the active virtual
environment (the `pytest` shim on `PATH` may belong to another interpreter).
`pyproject.toml` already sets `asyncio_mode = "auto"` and `pythonpath = ["."]`, so no
extra flags are needed.

Useful variations:

```bash
python -m pytest -q tests/unit              # one directory
python -m pytest -q tests/unit/test_foo.py::test_bar   # one test
python -m pytest -q --cov=src --cov-report=term-missing  # coverage
```

Tests must be deterministic and must not reach the network or a real Telegram API.
Use the fixtures in `tests/conftest.py`; keep new asynchronous tests `async def` —
the suite runs them automatically.

## Architecture and layer rules

The codebase follows a clean-architecture dependency rule. Imports may only point
"inwards" toward the domain:

```text
src/interfaces ─┐
                ├──> src/application ──> src/domain
src/infrastructure ─┘
```

- `src/domain/` — pure business models and interfaces (`agent.py`, `provider.py`,
  `tool.py`, `user.py`). It must not import from any other `src` package, and
  **never** from `src/infrastructure`.
- `src/application/` — use cases and orchestration (config, setup wizard, doctor,
  provider registry). It may import `src.domain` only.
- `src/infrastructure/` — concrete adapters (AI providers, database, Telegram,
  scheduler, security, tools). It implements domain interfaces.
- `src/interfaces/` — entry points, currently the CLI in `src/interfaces/cli/main.py`.

Practical rules:

- Never import `src.infrastructure` from `src.domain` or `src.application` — inject
  the adapter instead (see how `application/provider_registry.py` receives a built
  provider).
- Prefer the standard library; add a dependency only when it is genuinely needed.
- Keep code typed and PEP 8 compliant, targeting Python 3.12.

## Adding a new AI provider

Three places define a provider; add it to all of them:

1. `src/infrastructure/ai/factory.py` — instantiate and return the concrete provider
   from `create_ai_provider()`. Put the adapter itself next to the other providers in
   `src/infrastructure/ai/` (for example `openai_provider.py`).
2. `src/domain/provider.py` — add the provider id and its suggested models to
   `PROVIDER_MODELS_CATALOG`. This drives the model picker and the fallback model.
3. `src/application/config_manager.py` — add the environment-variable prefix to
   `PROVIDER_ENV_PREFIX` (for example `"9router": "NINE_ROUTER"`), so
   `<PREFIX>_API_KEY`, `<PREFIX>_BASE_URL` and `<PREFIX>_MODEL` are read from `.env`.

Add a unit test under `tests/unit/` that builds the provider with fake credentials and
asserts the request shape, then update `docs/` if the provider needs special setup.

## Adding a new tool

1. Implement the tool in `src/infrastructure/tools/` by subclassing `BaseTool` from
   `src/domain/tool.py`. Declare `name`, `description`, JSON-schema parameters, and
   the correct `PermissionLevel` / `RiskLevel`. Destructive tools must be marked as
   such so the confirmation gate applies.
2. Register an instance in `src/interfaces/cli/main.py`, guarded by a config flag
   (see how `WeatherTool` or `GitHubTool` are wired into `ToolRegistry`).
3. Document the tool in `docs/integrations/tools.md` — purpose, permission, risk
   level, and parameter schema.

Add tests covering both the success path and the rejection path (permission denied,
path escape, SSRF block).

## Branch naming

Branch off `main` and use a short, prefixed, kebab-case name:

```text
feat/ollama-streaming
fix/pid-file-stale
docs/setup-troubleshooting
chore/bump-actions
```

## Commit message convention

Use [Conventional Commits](https://www.conventionalcommits.org/):

```text
<type>(<optional scope>): <imperative summary>

<body — why, not what>

<footer — e.g. Closes #42>
```

Common types: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `chore`, `ci`.
Write the summary in the imperative mood, keep the first line under 72 characters, and
reference the issue it closes. Example:

```text
fix(setup): forward --non-interactive flags through PowerShell launcher

The PowerShell wrapper dropped $args, so the non-interactive path was
unreachable on Windows. Pass the user's arguments through unchanged.

Closes #57
```

## Pull request checklist

Before opening a pull request, confirm:

- [ ] `python -m pytest -q` passes locally.
- [ ] New behaviour has tests; bug fixes include a regression test.
- [ ] Layer rules above are respected (no infrastructure import from domain).
- [ ] `README.md` / `docs/` updated when user-facing behaviour changes.
- [ ] No secrets, database files, or generated artefacts committed.
- [ ] The PR description states the exact commands you ran as testing evidence.

Keep pull requests focused — one logical change per PR. Fill in the pull request
template completely; reviewers will ask for the missing evidence otherwise.

## Security

Do not open a public issue for a vulnerability. Follow the private reporting process
in [SECURITY.md](SECURITY.md). Never paste bot tokens or API keys into an issue, a
pull request, or a log.
