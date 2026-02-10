"""Extract Typer CLI commands for Telegram bot integration."""

from __future__ import annotations

import inspect
import sys
from dataclasses import dataclass
from typing import Any, Callable

import typer
from telegram import BotCommand

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


@dataclass
class CommandInfo:
    """Information about a CLI command."""
    name: str
    callback: Callable
    description: str
    subcommand_group: str | None = None
    takes_args: bool = False


def extract_typer_commands(typer_app: typer.Typer, prefix: str = "") -> list[CommandInfo]:
    """
    Extract all commands from a Typer app recursively.

    Args:
        typer_app: The Typer app to extract from
        prefix: Prefix for nested command groups (e.g., "cron_", "channels_")

    Returns:
        List of CommandInfo objects
    """
    commands = []

    # Try different attribute names for different Typer versions
    # Typer stores registered commands differently in different versions
    registered_commands = getattr(typer_app, "registered_commands", None)
    registered_groups = getattr(typer_app, "registered_groups", None)

    # Fallback: check for 'apps' attribute (some Typer versions)
    if registered_commands is None:
        registered_commands = getattr(typer_app, "commands", [])
    if registered_groups is None:
        # Might be stored as 'apps' or similar
        registered_groups = getattr(typer_app, "registered_applications", [])
        if registered_groups is None:
            registered_groups = getattr(typer_app, "apps", [])

    # Extract top-level commands
    if registered_commands:
        for cmd_info in registered_commands:
            # Handle both tuple format (name, Command) and dict-like access
            if isinstance(cmd_info, (tuple, list)) and len(cmd_info) >= 2:
                name = cmd_info[0]
                command_obj = cmd_info[1]
            elif hasattr(cmd_info, "name"):
                name = cmd_info.name
                command_obj = cmd_info
            else:
                continue

            callback = getattr(command_obj, "callback", None)
            if callback is None:
                continue

            description = _extract_description(callback)

            commands.append(CommandInfo(
                name=f"{prefix}{name}",
                callback=callback,
                description=description,
                subcommand_group=prefix.rstrip("_") or None,
                takes_args=_has_args(callback)
            ))

    # Recursively extract sub-group commands
    if registered_groups:
        for group_info in registered_groups:
            # Handle different formats
            if isinstance(group_info, (tuple, list)) and len(group_info) >= 2:
                group_name = group_info[0]
                group_app = group_info[1]
            elif hasattr(group_info, "name") and hasattr(group_info, "typer"):
                group_name = group_info.name
                group_app = group_info.typer
            elif hasattr(group_info, "app"):
                group_name = getattr(group_info, "name", "group")
                group_app = group_info.app
            else:
                continue

            new_prefix = f"{prefix}{group_name}_"
            commands.extend(extract_typer_commands(group_app, prefix=new_prefix))

    return commands


def _extract_description(callback: Callable) -> str:
    """Extract description from function docstring or Typer help."""
    # Try docstring first
    doc = inspect.getdoc(callback)
    if doc:
        # Take first line
        first_line = doc.split("\n")[0].strip()
        return first_line if first_line else "No description"

    # Fallback
    return "Run command"


def _has_args(callback: Callable) -> bool:
    """Check if command takes arguments (not safe for Telegram slash commands)."""
    sig = inspect.signature(callback)
    # Skip 'self' if present (method)
    params = [p for p in sig.parameters.values() if p.name not in ("self", "cls")]

    # Check if there are required parameters
    for param in params:
        # Typer Option/Argument have defaults
        if param.default == inspect.Parameter.empty:
            return True

    return False


def build_safe_telegram_commands(
    commands: list[CommandInfo],
    allowlist: set[str] | None = None,
    blocklist: set[str] | None = None,
    require_no_args: bool = True,
) -> list[BotCommand]:
    """
    Build Telegram BotCommand list from CLI commands with filtering.

    Args:
        commands: List of CommandInfo from extract_typer_commands
        allowlist: If set, only include these commands (by name)
        blocklist: If set, exclude these commands (by name)
        require_no_args: If True, only include commands that take no arguments

    Returns:
        List of BotCommand objects ready for set_my_commands()
    """
    safe_commands = []

    for cmd in commands:
        # Check allowlist
        if allowlist is not None and cmd.name not in allowlist:
            continue

        # Check blocklist
        if blocklist is not None and cmd.name in blocklist:
            continue

        # Check args requirement
        if require_no_args and cmd.takes_args:
            continue

        # Build description
        desc = cmd.description
        if cmd.subcommand_group:
            desc = f"[{cmd.subcommand_group}] {desc}"

        safe_commands.append(BotCommand(cmd.name, desc))

    return safe_commands


# Default allowlist: safe, read-only commands
DEFAULT_ALLOWLIST = {
    "status",
    "channels_status",
    "cron_list",
    "help",
    "start",
}


def get_default_telegram_commands(typer_app: typer.Typer) -> list[BotCommand]:
    """
    Get default safe Telegram commands from a Typer app.

    Includes:
    - Basic bot commands (start, help)
    - Read-only status commands
    - Excludes commands that take arguments
    """
    commands = extract_typer_commands(typer_app)

    # Add basic bot commands
    basic_commands = [
        BotCommand("start", "Start the bot"),
        BotCommand("reset", "Reset conversation history"),
        BotCommand("help", "Show available commands"),
    ]

    # Add safe CLI commands
    cli_commands = build_safe_telegram_commands(
        commands,
        allowlist=DEFAULT_ALLOWLIST,
        require_no_args=True
    )

    return basic_commands + cli_commands


# Command execution wrapper
async def execute_cli_command(
    command_info: CommandInfo,
    args: list[str],
    context: dict[str, Any] | None = None
) -> str:
    """
    Execute a CLI command and return output as string.

    Args:
        command_info: The CommandInfo to execute
        args: Command arguments as strings
        context: Additional context (may include config, etc.)

    Returns:
        Command output as string
    """
    import io
    from contextlib import redirect_stdout, redirect_stderr

    # Prepare kwargs from args
    sig = inspect.signature(command_info.callback)
    kwargs = {}

    # Map positional args to function parameters
    param_names = [p for p in sig.parameters.keys() if p not in ("self", "cls")]
    for i, arg_value in enumerate(args):
        if i < len(param_names):
            kwargs[param_names[i]] = arg_value

    # Capture output
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()

    try:
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            result = command_info.callback(**kwargs)
            # Handle coroutines
            if inspect.iscoroutine(result):
                import asyncio
                result = await asyncio.wait_for(result, timeout=30)

        stdout_text = stdout_capture.getvalue()
        stderr_text = stderr_capture.getvalue()

        # Return result or captured output
        if result is not None:
            return str(result)
        if stdout_text:
            return stdout_text
        if stderr_text:
            return f"Error: {stderr_text}"

        return "Command executed."

    except Exception as e:
        return f"Error executing command: {e}"
