#!/usr/bin/env python3
"""Nanobot mailkeeper skill wrapper.

职责：
- 定位 mailsweep 项目
- 调用 scripts/mailkeeper_run.py
- 读取 latest summary.json
- 生成适合聊天发送的 polished report
- 以 JSON 输出，方便 nanobot/LLM 进一步消费
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_PATH = Path.home() / ".nanobot" / "config.json"
DEFAULT_WORK_DIR = Path.home() / ".nanobot" / "workspace" / "mailkeeper"


def safe_name(value: str) -> str:
    import re
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value)


def _load_nanobot_config(config_path: str | None = None) -> dict[str, Any]:
    path = Path(config_path).expanduser() if config_path else DEFAULT_CONFIG_PATH
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _get_mailkeeper_config(config: dict[str, Any]) -> dict[str, Any]:
    tools = config.get("tools", {}) if isinstance(config, dict) else {}
    mk = tools.get("mailkeeper", {}) if isinstance(tools, dict) else {}
    return mk if isinstance(mk, dict) else {}


def _get_cfg_value(cfg: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in cfg:
            return cfg[key]
    return None


def find_project_dir(explicit: str | None, config_path: str | None = None) -> Path:
    cfg = _get_mailkeeper_config(_load_nanobot_config(config_path))
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())

    config_dir = _get_cfg_value(cfg, "projectDir", "project_dir")
    if config_dir:
        candidates.append(Path(str(config_dir)).expanduser())

    env_dir = os.environ.get("MAILKEEPER_PROJECT_DIR")
    if env_dir:
        candidates.append(Path(env_dir).expanduser())

    # Guess sibling repo: <nanobot>/../mailsweep
    here = Path(__file__).resolve()
    nanobot_repo = here.parents[4]
    candidates.append((nanobot_repo.parent / "mailsweep").resolve())

    for path in candidates:
        script = path / "scripts" / "mailkeeper_run.py"
        if script.exists():
            return path

    raise SystemExit(
        "Could not locate mailsweep project. Set tools.mailkeeper.projectDir in ~/.nanobot/config.json, "
        "or pass --project-dir, or set MAILKEEPER_PROJECT_DIR."
    )


def mailbox_key(account: str, folder: str) -> str:
    return f"{safe_name(account)}_{safe_name(folder)}"


def build_chat_report(summary: dict[str, Any]) -> str:
    planned = summary.get("planned_moves", {})
    candidate = summary.get("candidate_selection", {})
    lines: list[str] = []
    lines.append(f"Mailkeeper {summary.get('mode', 'run')} completed for {summary.get('account')} / {summary.get('source_folder')}.")
    lines.append(
        "Planned moves: "
        f"BOA {planned.get('BOA', 0)}, spam {planned.get('spam', 0)}, "
        f"newsletter {planned.get('newsletter', 0)}, ham {planned.get('ham', 0)}, review {planned.get('review', 0)}."
    )

    if candidate.get("bootstrap"):
        lines.append(
            "This mailbox is currently using bootstrap mode (no reliable incremental state yet); initialize state first for stable daily processing."
        )

    if summary.get("apply_block_reasons"):
        lines.append("Apply was blocked: " + "; ".join(summary["apply_block_reasons"]) + ".")

    newsletter = summary.get("newsletter_senders", [])[:5]
    if newsletter:
        lines.append(
            "Top newsletter senders: "
            + ", ".join(f"{item['sender']} ({item['count']})" for item in newsletter)
            + "."
        )

    ham = summary.get("ham_senders", [])[:5]
    if ham:
        lines.append(
            "Top ham senders: "
            + ", ".join(f"{item['sender']} ({item['count']})" for item in ham)
            + "."
        )

    boa_subjects = summary.get("boa_subjects", [])[:5]
    if boa_subjects:
        lines.append("BOA subjects: " + "; ".join(boa_subjects) + ".")

    ham_subjects = summary.get("ham_subjects", [])[:5]
    if ham_subjects:
        lines.append("Ham subjects: " + "; ".join(ham_subjects) + ".")

    review_subjects = summary.get("review_subjects", [])[:5]
    if review_subjects:
        lines.append("Review subjects: " + "; ".join(review_subjects) + ".")

    if summary.get("move_errors"):
        lines.append(f"Move errors: {summary['move_errors']}.")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Run mailsweep mailkeeper backend and emit JSON summary")
    parser.add_argument("--config", default=None, help="nanobot config path (default: ~/.nanobot/config.json)")
    parser.add_argument("--project-dir", default=None, help="Path to mailsweep project")
    parser.add_argument("--work-dir", default=None, help="Shared workspace for mailkeeper runs")
    parser.add_argument("--account", default="yahoo")
    parser.add_argument("--folder", default="INBOX")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--allow-bootstrap-apply", action="store_true")
    parser.add_argument("--initial-limit", type=int, default=100)
    parser.add_argument("--init-state", action="store_true")
    parser.add_argument("--allow-any-folder", action="store_true")
    parser.add_argument("--allow-uidvalidity-reset", action="store_true")
    parser.add_argument("--spam-threshold", type=float, default=None)
    parser.add_argument("--newsletter-threshold", type=float, default=None)
    parser.add_argument("--ham-threshold", type=float, default=None)
    parser.add_argument("--max-moves", type=int, default=None)
    parser.add_argument("--max-spam-moves", type=int, default=None)
    parser.add_argument("--max-review-moves", type=int, default=None)
    args = parser.parse_args()

    raw_cfg = _load_nanobot_config(args.config)
    mk_cfg = _get_mailkeeper_config(raw_cfg)

    project_dir = find_project_dir(args.project_dir, args.config)
    backend_script = project_dir / "scripts" / "mailkeeper_run.py"
    cfg_work_dir = _get_cfg_value(mk_cfg, "workDir", "work_dir")
    work_dir = Path(args.work_dir or cfg_work_dir or DEFAULT_WORK_DIR).expanduser()

    cmd = [
        "uv", "run", "--project", str(project_dir), "python", str(backend_script),
        "--account", args.account,
        "--folder", args.folder,
        "--work-dir", str(work_dir),
        "--initial-limit", str(args.initial_limit),
    ]
    mailbox = mailbox_key(args.account, args.folder)
    state_path = work_dir / "state" / f"{mailbox}.state.json"

    if args.apply and not args.allow_bootstrap_apply and not args.init_state and not state_path.exists():
        payload = {
            "success": False,
            "project_dir": str(project_dir),
            "work_dir": str(work_dir),
            "state_path": str(state_path),
            "error": "State not initialized for this mailbox. Run --init-state first, or intentionally pass --allow-bootstrap-apply.",
            "chat_report": (
                f"Mailkeeper apply was refused for {args.account} / {args.folder} because no state file exists yet. "
                "Run --init-state first, then retry apply. If you intentionally want a first-time bootstrap apply, pass --allow-bootstrap-apply."
            ),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        sys.exit(2)

    if args.apply:
        cmd.append("--apply")
    if args.allow_bootstrap_apply:
        cmd.append("--allow-bootstrap-apply")
    if args.init_state:
        cmd.append("--init-state")
    if args.allow_any_folder:
        cmd.append("--allow-any-folder")
    if args.allow_uidvalidity_reset:
        cmd.append("--allow-uidvalidity-reset")
    if args.spam_threshold is not None:
        cmd += ["--spam-threshold", str(args.spam_threshold)]
    if args.newsletter_threshold is not None:
        cmd += ["--newsletter-threshold", str(args.newsletter_threshold)]
    if args.ham_threshold is not None:
        cmd += ["--ham-threshold", str(args.ham_threshold)]
    if args.max_moves is not None:
        cmd += ["--max-moves", str(args.max_moves)]
    if args.max_spam_moves is not None:
        cmd += ["--max-spam-moves", str(args.max_spam_moves)]
    if args.max_review_moves is not None:
        cmd += ["--max-review-moves", str(args.max_review_moves)]

    result = subprocess.run(cmd, capture_output=True, text=True)
    mailbox = mailbox_key(args.account, args.folder)
    latest_dir = work_dir / "latest" / mailbox
    summary_path = latest_dir / "summary.json"
    metadata_path = latest_dir / "metadata.json"

    payload: dict[str, Any] = {
        "success": result.returncode == 0,
        "command": cmd,
        "project_dir": str(project_dir),
        "work_dir": str(work_dir),
        "latest_dir": str(latest_dir),
        "summary_path": str(summary_path),
        "metadata_path": str(metadata_path),
        "stdout": result.stdout[-4000:],
        "stderr": result.stderr[-4000:],
        "exit_code": result.returncode,
    }

    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        payload["summary"] = summary
        payload["chat_report"] = build_chat_report(summary)

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
