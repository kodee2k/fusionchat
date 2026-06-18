"""CLI entry point for fusionChat."""
from __future__ import annotations

import argparse
import dataclasses
import sys
from pathlib import Path

from fusionchat.api import run_api
from fusionchat.config import config_template, load_config
from fusionchat.tui import run_tui
from fusionchat.web import run_web


def _ensure_config_interactive(path: Path) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(config_template(), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fusionchat",
        description="Empero fusionChat — master model + up to 3 fusion models.",
    )
    parser.add_argument("--config", "-c", type=Path, help="Path to fusionchat.yml config file")
    parser.add_argument("--web", action="store_true", help="Run the web chat interface")
    parser.add_argument(
        "--api",
        action="store_true",
        help="Run an OpenAI-compatible API endpoint (/v1/chat/completions) for harnesses",
    )
    parser.add_argument("--hostname", "-H", default="127.0.0.1", help="Server hostname (default 127.0.0.1)")
    parser.add_argument("--port", "-p", type=int, default=8000, help="Server port (default 8000)")
    parser.add_argument("--effort", "-e", choices=["low", "mid", "high"], help="Override effort level")
    parser.add_argument(
        "--no-log-prompts",
        action="store_true",
        help="Do not write prompts/responses to session logs (metadata only)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except FileNotFoundError:
        default = Path.home() / ".config" / "fusionchat" / "fusionchat.yml"
        _ensure_config_interactive(default)
        print(f"Created default config at {default}. Please edit it and run fusionchat again.")
        return 1
    except Exception as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 1

    overrides: dict[str, object] = {}
    if args.effort:
        overrides["effort"] = args.effort
    if args.no_log_prompts:
        overrides["log_prompts"] = False
    if overrides:
        config = dataclasses.replace(config, **overrides)  # type: ignore[arg-type]

    if (args.web or args.api) and config.web_password is None and args.hostname not in ("127.0.0.1", "localhost", "::1"):
        surface = "API" if args.api else "web UI"
        print(
            f"Warning: serving the {surface} on {args.hostname} without 'web_password' set — "
            "anyone who can reach this host can use your API keys.",
            file=sys.stderr,
        )

    try:
        if args.api:
            run_api(config, args.hostname, args.port)
        elif args.web:
            run_web(config, args.hostname, args.port)
        else:
            run_tui(config)
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
