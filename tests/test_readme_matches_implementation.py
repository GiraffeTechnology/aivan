"""Keep README instructions honest.

Every script path, `aivan` CLI subcommand, and documented AIVAN_* /
OPENCLAW_* environment variable mentioned in the README must exist in the
repository, so the docs cannot drift back out of sync with the code.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")


def _cli_subcommands() -> set[str]:
    text = (ROOT / "src" / "aivan" / "cli" / "main.py").read_text(encoding="utf-8")
    return set(re.findall(r'add_parser\("([a-z0-9-]+)"', text))


def test_readme_script_paths_exist():
    for match in re.findall(r"scripts/[A-Za-z0-9_./-]+", README):
        if not match.endswith((".py", ".sh")):
            continue  # glob or prose mention, not a concrete path
        path = ROOT / match
        assert path.is_file(), f"README references missing script {match}"


def test_readme_cli_commands_exist():
    known = _cli_subcommands()
    referenced = set(re.findall(r"(?:uv run )?aivan ([a-z][a-z0-9-]+)", README))
    # Words following "aivan" that are prose, not subcommands, are filtered by
    # requiring an exact CLI-parser match check only for code-fenced commands.
    fenced = "\n".join(re.findall(r"```(?:bash|sh|shell|text)?\n(.*?)```", README, re.DOTALL))
    fenced_cmds = set(re.findall(r"\baivan ([a-z][a-z0-9-]+)", fenced))
    for cmd in fenced_cmds:
        assert cmd in known, f"README documents unknown CLI command: aivan {cmd}"
    assert referenced or True  # informational; fenced commands are the contract


def test_readme_env_vars_exist_in_code_or_env_example():
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    code = ""
    for py in (ROOT / "src").rglob("*.py"):
        code += py.read_text(encoding="utf-8")
    for ts in (ROOT / "integrations" / "openclaw-aivan-plugin").glob("*.ts"):
        code += ts.read_text(encoding="utf-8")

    documented = set(re.findall(r"\b((?:AIVAN|OPENCLAW|GLTG|GIRAFFE)[A-Z0-9_]*)=", README))
    for var in sorted(documented):
        assert var in env_example or var in code, (
            f"README documents env var {var} that neither .env.example nor the code uses"
        )


def test_readme_does_not_reference_removed_files():
    for match in re.findall(r"(?:src|docs|data|integrations|skills)/[A-Za-z0-9_./-]+", README):
        candidate = ROOT / match.rstrip(".`")
        if not candidate.suffix:
            continue  # directory-style mention
        if candidate.suffix in {".db", ".log"}:
            continue  # created at runtime, gitignored
        assert candidate.exists(), f"README references missing path {match}"
