"""CLI LLM router.

Uses logged-in CLI / Pro tools instead of API quota. Every result is cached in
SQLite, so re-runs are free.

Public:
    ask(prompt, task_type="score", json_mode=False, use_cache=True) -> str
    ask_json(prompt, task_type="score", use_cache=True) -> dict
"""
from __future__ import annotations
import hashlib
import json
import sqlite3
import subprocess
import time
import shutil
import shlex
import os
import tempfile
from typing import Callable
from .config import (
    COPILOT_ASK_COMMAND,
    CHATGPT_ASK_COMMAND,
    CODEX_MODEL,
    CODEX_REASONING_EFFORT,
    CACHE_DB,
)


# ---------- providers ---------- #

PROVIDER_COOLDOWN_SECONDS = int(os.getenv("LLM_PROVIDER_COOLDOWN_SECONDS", "600") or 600)
_PROVIDER_COOLDOWNS: dict[str, float] = {}


def _cli(cmd: list[str], prompt: str, timeout: int = 90, *, stdin_prompt: bool = False) -> str:
    executable = cmd[0]
    resolved = shutil.which(executable) or (executable if os.path.exists(executable) else None)
    if not resolved:
        raise RuntimeError(f"{cmd[0]} not installed")
    resolved_cmd = [resolved, *cmd[1:]]
    run_cmd = resolved_cmd if stdin_prompt else resolved_cmd + [prompt]
    try:
        result = subprocess.run(
            run_cmd,
            input=prompt if stdin_prompt else None,
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        safe_cmd = " ".join(shlex.quote(part) for part in resolved_cmd[:4])
        raise TimeoutError(f"{cmd[0]} timed out after {timeout}s while running: {safe_cmd}") from e
    except OSError as e:
        raise RuntimeError(f"{cmd[0]} could not start: {e}") from e
    if result.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {result.stderr[:200]}")
    return result.stdout.strip()


def _codex_cli(prompt: str, task_type: str = "score", **_):
    timeout = 75 if task_type in ("score", "extract") else 180
    cmd = [
        "codex", "exec",
        "--skip-git-repo-check",
        "-c", f'model_reasoning_effort="{CODEX_REASONING_EFFORT}"',
    ]
    if CODEX_MODEL:
        cmd += ["--model", CODEX_MODEL]
    with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as tmp:
        out_path = tmp.name
    try:
        _cli(cmd + ["--output-last-message", out_path, "-"],
             prompt, timeout=timeout, stdin_prompt=True)
        with open(out_path, encoding="utf-8") as f:
            return f.read().strip()
    finally:
        try:
            os.unlink(out_path)
        except OSError:
            pass


def _gemini_cli(prompt: str, task_type: str = "score", **_):
    timeout = int(os.getenv("GEMINI_TIMEOUT_SCORE", "75") or 75) if task_type in ("score", "extract") else 150
    return _cli(["gemini", "-p"], prompt, timeout=timeout)


def _chatgpt_cli(prompt: str, task_type: str = "score", **_):
    """ChatGPT CLI only when explicitly configured or installed.

    Falls through to `codex` because `codex login --with-chatgpt` lets the
    user spend ChatGPT Pro quota instead of OpenAI API credits.
    """
    timeout = 75 if task_type in ("score", "extract") else 180
    if CHATGPT_ASK_COMMAND:
        return _cli(shlex.split(CHATGPT_ASK_COMMAND), prompt, timeout=timeout)
    if shutil.which("chatgpt"):
        return _cli(["chatgpt", "-p"], prompt, timeout=timeout)
    if shutil.which("codex"):
        return _codex_cli(prompt, task_type=task_type)
    raise RuntimeError(
        "ChatGPT CLI not available. Set CHATGPT_ASK_COMMAND, install a chatgpt "
        "command, or sign in to Codex with ChatGPT."
    )


def _copilot_cli(prompt: str, task_type: str = "score", **_):
    """GitHub Copilot CLI, when available.

    Supports COPILOT_ASK_COMMAND in .env, then `copilot`, then `gh copilot`.
    """
    timeout = 60 if task_type in ("score", "extract") else 150
    if COPILOT_ASK_COMMAND:
        base_cmd = shlex.split(COPILOT_ASK_COMMAND)
        if len(prompt) > 6000:
            return _copilot_cli_with_attachment(base_cmd, prompt, timeout=timeout)
        return _cli(base_cmd, prompt, timeout=timeout)
    if shutil.which("copilot"):
        cmd = ["copilot", "-s", "-p"]
        if len(prompt) > 6000:
            return _copilot_cli_with_attachment(cmd, prompt, timeout=timeout)
        return _cli(cmd, prompt, timeout=timeout)
    if shutil.which("gh"):
        if len(prompt) > 6000:
            return _copilot_cli_with_attachment(
                ["gh", "copilot", "--", "-s", "-p"], prompt, timeout=timeout
            )
        return _cli(["gh", "copilot", "--", "-s", "-p"], prompt, timeout=timeout)
    raise RuntimeError(
        "Copilot CLI not available. Install gh copilot or set COPILOT_ASK_COMMAND."
    )


def _copilot_cli_with_attachment(cmd: list[str], prompt: str, timeout: int) -> str:
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt", encoding="utf-8") as tmp:
        tmp.write(prompt)
        prompt_path = tmp.name
    try:
        short_prompt = (
            "Answer the job-agent prompt in the attached text file. "
            "Return only the requested final output."
        )
        base = _without_prompt_flag(cmd)
        return _cli(base + ["--attachment", prompt_path, "--prompt"],
                    short_prompt, timeout=timeout)
    finally:
        try:
            os.unlink(prompt_path)
        except OSError:
            pass


def _without_prompt_flag(cmd: list[str]) -> list[str]:
    cleaned: list[str] = []
    skip_next = False
    for part in cmd:
        if skip_next:
            skip_next = False
            continue
        if part in ("-p", "--prompt"):
            skip_next = True
            continue
        if part.startswith("--prompt="):
            continue
        cleaned.append(part)
    return cleaned


def _claude_cli(prompt: str, task_type: str = "score", **_):
    timeout = 75 if task_type in ("score", "extract") else 180
    return _cli(["claude", "-p"], prompt, timeout=timeout)


# ---------- routing policy ---------- #

# Each task type: ordered list of (provider, model_or_none).
# First success wins; failures cascade to the next entry.
POLICIES: dict[str, list[tuple[str, str | None]]] = {
    "score":   [("gemini_cli", None), ("copilot_cli", None),
                ("codex_cli", None),  ("claude_cli", None)],
    "tailor":  [("gemini_cli", None), ("copilot_cli", None),
                ("codex_cli", None),  ("claude_cli", None)],
    "cover":   [("gemini_cli", None), ("copilot_cli", None),
                ("codex_cli", None),  ("claude_cli", None)],
    "extract": [("gemini_cli", None), ("copilot_cli", None),
                ("codex_cli", None),  ("claude_cli", None)],
}

PROVIDER_FNS: dict[str, Callable] = {
    "codex_cli":   _codex_cli,
    "gemini_cli":  _gemini_cli,
    "chatgpt_cli": _chatgpt_cli,
    "copilot_cli": _copilot_cli,
    "claude_cli":  _claude_cli,
}


# ---------- cache ---------- #

def _cache_conn():
    con = sqlite3.connect(CACHE_DB)
    con.execute("CREATE TABLE IF NOT EXISTS cache (k TEXT PRIMARY KEY, v TEXT, ts TEXT)")
    return con


def _cache_key(prompt: str, task_type: str) -> str:
    return hashlib.sha1(f"{task_type}::{prompt}".encode()).hexdigest()


def _cache_get(key: str) -> str | None:
    con = _cache_conn()
    row = con.execute("SELECT v FROM cache WHERE k=?", (key,)).fetchone()
    con.close()
    return row[0] if row else None


def _cache_set(key: str, value: str) -> None:
    con = _cache_conn()
    con.execute("INSERT OR REPLACE INTO cache VALUES (?, ?, datetime('now'))", (key, value))
    con.commit()
    con.close()


# ---------- public API ---------- #

def ask(prompt: str, task_type: str = "score",
        json_mode: bool = False, use_cache: bool = True) -> str:
    if task_type not in POLICIES:
        raise ValueError(f"unknown task_type {task_type}")

    key = _cache_key(prompt, task_type)
    if use_cache and (hit := _cache_get(key)):
        return hit

    last_err: Exception | None = None
    for provider, _model in POLICIES[task_type]:
        if len(prompt) > 6000 and provider in {"gemini_cli", "copilot_cli", "claude_cli"}:
            last_err = RuntimeError(
                f"{provider} skipped because prompt is too long for CLI args"
            )
            continue
        cooldown_until = _PROVIDER_COOLDOWNS.get(provider, 0)
        if cooldown_until > time.time():
            last_err = RuntimeError(f"{provider} is cooling down after a recent failure")
            continue
        try:
            fn = PROVIDER_FNS[provider]
            out = fn(prompt, task_type=task_type)
            if out:
                _cache_set(key, out)
                return out
        except Exception as e:
            last_err = e
            if isinstance(e, TimeoutError) or "timed out" in str(e).lower():
                _PROVIDER_COOLDOWNS[provider] = time.time() + PROVIDER_COOLDOWN_SECONDS
            print(f"[llm] {provider} failed: {e}; trying next")
            time.sleep(1)

    raise RuntimeError(f"All providers failed for {task_type}: {last_err}")


def ask_json(prompt: str, task_type: str = "score", use_cache: bool = True) -> dict:
    """Convenience: ask + parse JSON, tolerant of stray ```json fences."""
    raw = ask(prompt, task_type=task_type, json_mode=True, use_cache=use_cache)
    cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(cleaned)
