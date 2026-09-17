# Agent Notes

Keep this project small.

- Human entry point: `README.md`.
- Code entry point: `china_finance_rss/server.py`.
- Do not add docs unless the README would become confusing without them.
- Never commit `.env`, cookies, tokens, private keys, Chrome profiles, or HAR
  files.
- Prefer the Python standard library.

Before handoff, run only the checks that match what changed — never the
business suite for tooling/doc-only edits:

| Changed paths | Run |
| --- | --- |
| `china_finance_rss/**`, `tests/**` | `python -m py_compile china_finance_rss/*.py tests/*.py` then `python -m unittest discover -s tests -v` |
| `opencode.json`, `.opencode/**` | `bash .opencode/scripts/check-opencode.sh` |
| docs only (`*.md`, `doc/**`) | nothing extra |
| anything | `git diff --check` |

`bash .opencode/scripts/check-changed.sh [base]` applies the right set from the
diff automatically (base defaults to `HEAD`; pass `HEAD~1` once changes are
committed).
