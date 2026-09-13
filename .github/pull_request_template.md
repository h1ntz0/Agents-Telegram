## Summary

<!-- What does this change do, and why? One or two paragraphs. Link the issue it closes. -->

Closes #

## Type of change

<!-- Tick every box that applies. -->

- [ ] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Breaking change (existing behaviour or configuration changes)
- [ ] Documentation only
- [ ] Refactor / internal cleanup (no behaviour change)
- [ ] CI, packaging, or tooling

## Testing evidence

<!--
Paste the exact commands you ran and their outcome. "Tests pass" is not evidence.
Example:

    .venv/bin/python -m pytest -q
    214 passed in 18.42s
-->

```text

```

- [ ] `python -m pytest -q` passes locally
- [ ] I added or updated tests for the changed behaviour
- [ ] I manually exercised the changed path (describe how above)

## Security

- [ ] I have **not** committed `.env`, `data/agent.db`, API keys, bot tokens, or any other secret
- [ ] New outbound requests keep SSRF guard, allowlist, and rate-limit behaviour intact
- [ ] Destructive tools still require explicit confirmation

## Checklist

- [ ] Code follows the clean-architecture layer rules in [CONTRIBUTING.md](https://github.com/h1ntz0/Agents-Telegram/blob/main/CONTRIBUTING.md)
- [ ] Public behaviour changes are reflected in `README.md` / `docs/`
- [ ] Commit messages follow the conventional-commit format
