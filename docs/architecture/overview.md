# Architecture Overview

This platform follows a modular Clean Architecture pattern designed to decouple external transport (Telegram), AI models (OpenAI, Anthropic, Google, Ollama), persistence (SQLite), and execution tools.

## Core Layers

1. **Domain Layer (`src/domain/`)**:
   - Defines core business entities: `Session`, `Message`, `Role`, `ToolCall`, `ToolResponse`, `TelegramUser`.
   - Defines tool permissions (`READ`, `WRITE`, `EXECUTE`, `DESTRUCTIVE`) and risk classifications.
   - Defines provider contracts (`AIProvider`, `CompletionRequest`, `CompletionResponse`).

2. **Application Layer (`src/application/`)**:
   - `AgentOrchestrator`: Implements the ReAct control loop, prompt generation with dynamic user memory, tool selection, confirmation checks, and message persistence.
   - `SetupWizard`: Guides users through environment validation, progressive configuration, and live connection verification.
   - `ConfigManager`: Resolves configuration from CLI arguments, environment variables, `.env`, and YAML defaults with Pydantic validation.
   - `SystemDoctor`: Executes comprehensive runtime and connectivity checks.

3. **Infrastructure Layer (`src/infrastructure/`)**:
   - `telegram/`: Asynchronous client supporting long-polling, callback queries, message splitting, and user authorization.
   - `ai/`: Provider adapters for OpenAI, Anthropic, Google Gemini, OpenRouter, and Ollama.
   - `database/`: Asynchronous SQLite storage for user sessions, messages, and persistent key-value memory.
   - `security/`: SSRF guard, rate limiter, prompt boundary wrapper, and regex secret scrubber.
   - `tools/`: Sandboxed tools for web search, filesystem operations, GitHub API, and optional shell execution.

4. **Interface Layer (`src/interfaces/cli/`)**:
   - Provides unified CLI entrypoints for setup, runtime lifecycle, diagnostics, configuration inspection, and backup.
