# ABOUTME: pytest config — adds skill scripts dir to sys.path so tests can import compress/estimate.
# ABOUTME: Also provides shared fixtures (sample prompts, tmp log dir).

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_SCRIPTS = REPO_ROOT / "skills" / "prompt-squeeze" / "scripts"
HOOKS_DIR = REPO_ROOT / "hooks"
MCP_DIR = REPO_ROOT / "mcp"

for p in (SKILL_SCRIPTS, HOOKS_DIR, MCP_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


@pytest.fixture()
def short_prompt() -> str:
    return "fix the bug in foo.py"


@pytest.fixture()
def verbose_prompt() -> str:
    return (
        "Hi, I was wondering if you could please help me out with something. "
        "I'm working on a project and I think it would be great if you could "
        "take a look at the file foo.py at line 42, where there's a TypeError "
        "happening due to the fact that the variable is None. Thanks in advance "
        "for any help you can give! In order to debug this, could you please "
        "show me a fix? Thank you so much."
    )


@pytest.fixture()
def long_context_prompt() -> str:
    body = (
        "Please could you take a careful look at the following Python traceback. "
        "I was wondering if you might be able to help me debug it. "
        "Thanks in advance for your patience.\n\n"
    )
    return body + ("File 'src/api/handler.py', line 88, in dispatch\n") * 200


@pytest.fixture()
def code_fenced_prompt() -> str:
    return (
        "Please review the following code:\n\n"
        "```python\n"
        "def please_compute_in_order_to_succeed():\n"
        "    return 'in order to'\n"
        "```\n\n"
        "Thanks in advance!"
    )


@pytest.fixture()
def tmp_log_dir(tmp_path, monkeypatch):
    log_dir = tmp_path / "prompt-squeeze"
    log_dir.mkdir()
    monkeypatch.setenv("PROMPT_SQUEEZE_LOG_DIR", str(log_dir))
    monkeypatch.setenv("HOME", str(tmp_path))
    return log_dir
