# Agent Notes

Keep this project small.

- Human entry point: `README.md`.
- Code entry point: `server.py`.
- Do not add docs unless the README would become confusing without them.
- Never commit `.env`, cookies, tokens, private keys, Chrome profiles, or HAR
  files.
- Prefer the Python standard library.

Before handoff:

```bash
python -m unittest discover -s tests -v
python -m py_compile server.py tests/test_server.py
git diff --check
```
