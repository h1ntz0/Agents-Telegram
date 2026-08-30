# Contributing Guide

Contributions are welcome. Please follow these conventions when submitting pull requests:

1. **Follow Minimal Architecture**: Use standard library features when possible. Add dependencies only when strictly necessary.
2. **Preserve Security Boundaries**: Never bypass rate limiting, allowlist enforcement, or SSRF guards.
3. **Add Tests**: All new features or bug fixes must include unit or integration tests in the `tests/` directory.
4. **Run Test Suite**:
   ```bash
   pytest -v --cov=src
   ```
5. **Format & Types**: Write clean, typed Python 3.12 code following PEP 8 conventions.
