"""gmon: Command line interface for monitoring Antigravity IDE sessions."""

from __future__ import annotations

import json
from typing import Optional

import click
from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from ml_mon.config import AntigravityConfig
from ml_mon.core.parser import ConversationParser
from ml_mon.core.scanner import ConversationScanner

console = Console()


def get_target_id(scanner: ConversationScanner, target: str) -> Optional[str]:
    """Resolve 'latest' or prefix to a full conversation ID."""
    if target.lower() in ("latest", "last", "current"):
        all_convs = scanner.scan_all()
        if not all_convs:
            return None
        return all_convs[0].id

    # If full ID or prefix
    all_ids = scanner.list_conversation_ids()
    for cid in all_ids:
        if cid == target:
            return cid
    # Check prefix
    matches = [cid for cid in all_ids if cid.startswith(target)]
    if len(matches) == 1:
        return matches[0]
    elif len(matches) > 1:
        console.print(f"[bold yellow]⚠️ Multiple conversations match prefix '{target}':[/bold yellow]")
        for m in matches:
            console.print(f"  • [green]{m}[/green]")
        return None
    return target


@click.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    epilog="""
[bold cyan]Quick Start Examples:[/bold cyan]
  gmon serve              ⚡ Start the real-time browser visualizer at http://127.0.0.1:8765
  gmon list               📋 List all conversations (shows LIVE status, steps, plans)
  gmon show latest        🔍 View full chronological timeline of the latest session
  gmon cot latest         🧠 Extract all Chain of Thought (reasoning) steps
  gmon plan latest        📄 Inspect implementation plan and walkthrough in terminal
  gmon show latest --json 📦 Output complete structured session data as JSON
""",
)
@click.option("--base-dir", "-b", help="Path to ~/.gemini/antigravity-ide base directory")
@click.pass_context
def main(ctx: click.Context, base_dir: Optional[str]):
    """⚡ gmon: Antigravity IDE conversation, Chain of Thought (CoT), and plan monitor."""
    ctx.ensure_object(dict)
    config = AntigravityConfig.discover(base_dir=base_dir)
    ctx.obj["config"] = config
    ctx.obj["scanner"] = ConversationScanner(config)
    ctx.obj["parser"] = ConversationParser(config)


@main.command("list")
@click.option("--limit", "-n", default=20, help="Number of conversations to display (0 for all)")
@click.option("--active", is_flag=True, help="Show only currently active conversations")
@click.option("--full-id", is_flag=True, help="Display full 36-character UUIDs instead of short prefixes")
@click.option("--json-output", "--json", is_flag=True, help="Output results as JSON")
@click.pass_context
def list_conversations(ctx: click.Context, limit: int, active: bool, full_id: bool, json_output: bool):
    """📋 List discovered conversations and their active status."""
    scanner: ConversationScanner = ctx.obj["scanner"]
    summaries = scanner.scan_all()

    if active:
        summaries = [s for s in summaries if s.is_active]

    total_count = len(summaries)
    if limit > 0:
        summaries = summaries[:limit]

    if json_output:
        click.echo(json.dumps([s.model_dump() for s in summaries], indent=2))
        return

    if not summaries:
        console.print("[dim]No conversations found in Antigravity storage.[/dim]")
        return

    table = Table(
        title="⚡ [bold cyan]Antigravity IDE Conversations[/bold cyan]",
        box=box.ROUNDED,
        header_style="bold cyan",
        show_lines=False,
    )
    table.add_column("Status", justify="center", width=8)
    table.add_column("ID", style="bold green", width=38 if full_id else 11)
    table.add_column("Objective / Title", style="white")
    table.add_column("Steps", justify="right", width=7)
    table.add_column("Plan", justify="center", width=6)
    table.add_column("Active", style="dim", width=14)

    live_count = 0
    for s in summaries:
        if s.is_active:
            live_count += 1
            status = "[bold green]● LIVE[/bold green]"
        else:
            status = "[dim]○ IDLE[/dim]"

        plan_badge = "[bold yellow]📋 Plan[/bold yellow]" if s.has_plan else ("[bold green]📝 Walk[/bold green]" if s.has_walkthrough else "[dim]─[/dim]")
        last_time = s.last_modified.replace("T", " ")[5:16] if s.last_modified else "-"
        id_display = s.id if full_id else s.id[:8] + "…"

        table.add_row(
            status,
            id_display,
            s.title[:45] + ("..." if len(s.title) > 45 else ""),
            f"[cyan]{s.step_count}[/cyan]",
            plan_badge,
            last_time,
        )

    console.print(table)
    console.print(
        f"[dim]📊 Showing {len(summaries)} of {total_count} conversations  •  "
        f"[bold green]{live_count} LIVE[/bold green]  •  "
        f"Storage: {scanner.config.base_dir}[/dim]\n"
    )


@main.command("show")
@click.argument("conversation_id", default="latest")
@click.option("--cot/--no-cot", default=True, help="Show or hide Chain of Thought reasoning blocks")
@click.option("--tools/--no-tools", default=True, help="Show or hide tool invocations and results")
@click.option("--plan", "-p", is_flag=True, help="Show implementation plan and walkthrough")
@click.option("--json-output", "--json", is_flag=True, help="Output complete detail as JSON")
@click.pass_context
def show_conversation(
    ctx: click.Context,
    conversation_id: str,
    cot: bool,
    tools: bool,
    plan: bool,
    json_output: bool,
):
    """🔍 View conversation history, Chain of Thought (CoT), and plan."""
    scanner: ConversationScanner = ctx.obj["scanner"]
    parser: ConversationParser = ctx.obj["parser"]

    target_id = get_target_id(scanner, conversation_id)
    if not target_id:
        console.print(f"[bold red]✖ Error:[/bold red] Conversation '{conversation_id}' not found.")
        return

    detail = parser.parse_conversation(target_id)
    if not detail:
        console.print(f"[bold red]✖ Error:[/bold red] Could not load conversation '{target_id}'.")
        return

    if json_output:
        click.echo(json.dumps(detail.model_dump(), indent=2))
        return

    # Header Panel
    s = detail.summary
    status_str = "[bold green]● LIVE STREAMING[/bold green]" if s.is_active else "[dim]○ COMPLETED[/dim]"
    plan_info = "[bold yellow]📋 Plan Available[/bold yellow]" if s.has_plan else "[dim]No Plan[/dim]"
    last_mod = s.last_modified.replace("T", " ")[:19] if s.last_modified else "-"

    console.print(
        Panel(
            f"  [bold cyan]🆔 ID:[/bold cyan]            [green]{s.id}[/green]\n"
            f"  [bold cyan]📌 Title:[/bold cyan]         {s.title}\n"
            f"  [bold cyan]🟢 Status:[/bold cyan]        {status_str}\n"
            f"  [bold cyan]📊 Activity:[/bold cyan]      ⚡ [cyan]{s.step_count} Steps[/cyan]  │  🧠 [magenta]{len(detail.thoughts)} Thoughts[/magenta]  │  {plan_info}\n"
            f"  [bold cyan]🕒 Last Active:[/bold cyan]   [dim]{last_mod}[/dim]",
            title="⚡ [bold cyan]Antigravity Session Details[/bold cyan]",
            border_style="cyan",
            box=box.ROUNDED,
        )
    )

    # If --plan requested
    if plan and detail.plan:
        if detail.plan.plan_content:
            console.print(
                Panel(
                    Markdown(detail.plan.plan_content),
                    title="📋 [bold yellow]Implementation Plan[/bold yellow]",
                    subtitle=detail.plan.plan_last_modified or "",
                    border_style="yellow",
                    box=box.ROUNDED,
                )
            )
        if detail.plan.walkthrough_content:
            console.print(
                Panel(
                    Markdown(detail.plan.walkthrough_content),
                    title="📝 [bold green]Walkthrough[/bold green]",
                    subtitle=detail.plan.walkthrough_last_modified or "",
                    border_style="green",
                    box=box.ROUNDED,
                )
            )
        return

    # Timeline of steps
    for step in detail.steps:
        time_str = f" • 🕒 {step.created_at[11:19]}" if step.created_at and len(step.created_at) >= 19 else ""

        # User input
        if step.user_prompt:
            console.print(
                Panel(
                    Markdown(step.user_prompt),
                    title=f"👤 [bold blue]User Request[/bold blue] [dim](Step {step.step_index}{time_str})[/dim]",
                    border_style="blue",
                    box=box.ROUNDED,
                )
            )

        # Chain of Thought (CoT)
        if cot and step.thought:
            console.print(
                Panel(
                    Markdown(step.thought.content),
                    title=f"🧠 [bold magenta]Chain of Thought[/bold magenta] [dim](Step {step.step_index}{time_str})[/dim]",
                    subtitle=f"[dim]💭 {step.thought.character_count} chars[/dim]",
                    border_style="magenta",
                    box=box.ROUNDED,
                )
            )

        # Tool calls
        if tools and step.tool_calls:
            for tc in step.tool_calls:
                summary_text = f" → [italic]{tc.summary}[/italic]" if tc.summary else ""
                args_json = json.dumps(tc.args, indent=2)
                console.print(
                    Panel(
                        Syntax(args_json, "json", theme="monokai", word_wrap=True),
                        title=f"🛠️ [bold yellow]Tool Call: {tc.name}[/bold yellow]{summary_text} [dim](Step {step.step_index})[/dim]",
                        border_style="yellow",
                        box=box.ROUNDED,
                    )
                )

        # Tool result
        if tools and step.tool_result and step.tool_result.content:
            status_icon = "✔" if step.tool_result.exit_code in (0, None) else "✖"
            status_style = "green" if step.tool_result.exit_code in (0, None) else "red"
            exit_str = f" • [{status_style}]{status_icon} exit {step.tool_result.exit_code}[/{status_style}]" if step.tool_result.exit_code is not None else ""

            output_snippet = step.tool_result.content
            if len(output_snippet) > 800:
                output_snippet = output_snippet[:800] + f"\n... [dim][truncated {len(step.tool_result.content) - 800} chars][/dim]"
            console.print(
                Panel(
                    output_snippet,
                    title=f"📥 [dim]Result: {step.tool_result.tool_name}[/dim]{exit_str} [dim](Step {step.step_index})[/dim]",
                    border_style="dim",
                    box=box.ROUNDED,
                )
            )

        # Assistant final response
        if step.model_response:
            console.print(
                Panel(
                    Markdown(step.model_response),
                    title=f"🤖 [bold green]Assistant Response[/bold green] [dim](Step {step.step_index}{time_str})[/dim]",
                    border_style="green",
                    box=box.ROUNDED,
                )
            )


@main.command("cot")
@click.argument("conversation_id", default="latest")
@click.pass_context
def show_cot(ctx: click.Context, conversation_id: str):
    """🧠 Extract and display all Chain of Thought (reasoning) steps."""
    scanner: ConversationScanner = ctx.obj["scanner"]
    parser: ConversationParser = ctx.obj["parser"]

    target_id = get_target_id(scanner, conversation_id)
    if not target_id:
        console.print(f"[bold red]✖ Error:[/bold red] Conversation '{conversation_id}' not found.")
        return

    detail = parser.parse_conversation(target_id)
    if not detail or not detail.thoughts:
        console.print(f"[yellow]⚠️ No Chain of Thought entries found for session {target_id}.[/yellow]")
        return

    total_chars = sum(t.character_count for t in detail.thoughts)
    avg_chars = total_chars // len(detail.thoughts) if detail.thoughts else 0

    console.print(
        Panel(
            f"  [bold magenta]Session:[/bold magenta] {target_id}\n"
            f"  [bold magenta]Total Thoughts:[/bold magenta] {len(detail.thoughts)} reasoning steps\n"
            f"  [bold magenta]Volume:[/bold magenta] {total_chars:,} characters (avg {avg_chars:,} chars/step)",
            title="🧠 [bold magenta]Chain of Thought Timeline[/bold magenta]",
            border_style="magenta",
            box=box.ROUNDED,
        )
    )

    for i, t in enumerate(detail.thoughts, 1):
        time_str = f" • 🕒 {t.created_at[11:19]}" if t.created_at and len(t.created_at) >= 19 else ""
        console.print(
            Panel(
                Markdown(t.content),
                title=f"🧠 [bold magenta]Thought {i}/{len(detail.thoughts)}[/bold magenta] [dim](Step {t.step_index}{time_str})[/dim]",
                subtitle=f"[dim]💭 {t.character_count} chars[/dim]",
                border_style="magenta",
                box=box.ROUNDED,
            )
        )


@main.command("plan")
@click.argument("conversation_id", default="latest")
@click.pass_context
def show_plan(ctx: click.Context, conversation_id: str):
    """📄 View the implementation plan and walkthrough for a conversation."""
    scanner: ConversationScanner = ctx.obj["scanner"]
    parser: ConversationParser = ctx.obj["parser"]

    target_id = get_target_id(scanner, conversation_id)
    if not target_id:
        console.print(f"[bold red]✖ Error:[/bold red] Conversation '{conversation_id}' not found.")
        return

    plan_asset = parser.parse_plan_asset(target_id)
    if not plan_asset or (not plan_asset.plan_content and not plan_asset.walkthrough_content):
        console.print(f"[yellow]⚠️ No implementation plan or walkthrough found for {target_id}.[/yellow]")
        return

    if plan_asset.plan_content:
        console.print(
            Panel(
                Markdown(plan_asset.plan_content),
                title=f"📋 [bold yellow]Implementation Plan[/bold yellow] [dim]({target_id[:8]}…)[/dim]",
                subtitle=plan_asset.plan_last_modified or "",
                border_style="yellow",
                box=box.ROUNDED,
            )
        )
    if plan_asset.walkthrough_content:
        console.print(
            Panel(
                Markdown(plan_asset.walkthrough_content),
                title=f"📝 [bold green]Walkthrough[/bold green] [dim]({target_id[:8]}…)[/dim]",
                subtitle=plan_asset.walkthrough_last_modified or "",
                border_style="green",
                box=box.ROUNDED,
            )
        )


@main.command("context")
@click.argument("conversation_id", default="latest")
@click.option("--all-frames/--active-only", "all_frames", default=False, help="Show all frames or only active post-compaction context")
@click.option("--json-out", is_flag=True, help="Export context report as JSON")
@click.pass_context
def context_cmd(ctx: click.Context, conversation_id: str, all_frames: bool, json_out: bool):
    """🔍 Inspect the LLM context window, compaction boundary, and token usage."""
    scanner: ConversationScanner = ctx.obj["scanner"]
    parser: ConversationParser = ctx.obj["parser"]

    resolved_id = get_target_id(scanner, conversation_id)
    if not resolved_id:
        console.print(f"[bold red]✖ Error:[/bold red] Conversation '{conversation_id}' not found.")
        sys.exit(1)

    report = parser.extract_context_window(resolved_id)
    if not report:
        console.print(f"[bold red]✖ Error:[/bold red] No transcript found for '{resolved_id}'.")
        sys.exit(1)

    if json_out:
        print(json.dumps(report.model_dump(), indent=2))
        return

    compaction_status = (
        f"[bold yellow]Compacted ({report.compaction_count}x)[/bold yellow] • Active Window from Step {report.active_window_start_step}"
        if report.has_compaction
        else "[bold green]Full History (No Compaction)[/bold green]"
    )

    console.print(
        Panel(
            f"  [bold cyan]Conversation ID:[/bold cyan]  {resolved_id}\n"
            f"  [bold cyan]Active Tokens:[/bold cyan]    [bold yellow]{report.total_active_tokens:,}[/bold yellow] est. tokens ([dim]{report.total_active_chars:,} chars[/dim])\n"
            f"  [bold cyan]Total Session:[/bold cyan]    {report.total_session_tokens:,} est. tokens ([dim]{report.total_session_chars:,} chars[/dim])\n"
            f"  [bold cyan]Compaction:[/bold cyan]       {compaction_status}",
            title="🔍 [bold cyan]LLM Context Window & Usage[/bold cyan]",
            border_style="cyan",
            box=box.ROUNDED,
        )
    )

    breakdown_table = Table(
        title="Active Context Window Usage Breakdown",
        box=box.ROUNDED,
        border_style="dim",
        header_style="bold cyan",
    )
    breakdown_table.add_column("Category", style="bold")
    breakdown_table.add_column("Tokens (Est.)", justify="right", style="yellow")
    breakdown_table.add_column("Characters", justify="right", style="dim")
    breakdown_table.add_column("Share", justify="right", style="green")

    for b in report.breakdown:
        if b.est_tokens > 0:
            breakdown_table.add_row(
                b.label,
                f"{b.est_tokens:,}",
                f"{b.char_count:,}",
                f"{b.percentage:.1f}%",
            )
    console.print(breakdown_table)

    frames_to_show = report.frames if all_frames else [f for f in report.frames if f.is_active]
    frame_title = f"Context Frames ({len(frames_to_show)} {'total' if all_frames else 'active'})"

    frames_table = Table(
        title=frame_title,
        box=box.ROUNDED,
        border_style="dim",
        header_style="bold magenta",
    )
    frames_table.add_column("#", justify="right", style="dim")
    frames_table.add_column("Step", justify="right", style="bold")
    frames_table.add_column("Type", style="cyan")
    frames_table.add_column("Tokens", justify="right", style="yellow")
    frames_table.add_column("Preview", style="white")

    for f in frames_to_show:
        active_mark = "" if f.is_active else " [dim](pruned)[/dim]"
        frames_table.add_row(
            str(f.index),
            str(f.step_index),
            f"{f.frame_type}{active_mark}",
            f"{f.est_tokens:,}",
            f.preview.replace("\n", " ")[:70],
        )
    console.print(frames_table)


@main.command("prompt")
@click.argument("conversation_id", default="latest")
@click.option("--section", "-s", type=click.Choice(["all", "system", "tools", "skills", "memory", "history"]), default="all", help="Display only a specific prompt section")
@click.option("--raw", is_flag=True, help="Print raw plaintext prompt without Rich formatting")
@click.option("--json-out", is_flag=True, help="Output reconstructed prompt as structured JSON")
@click.option("--save-to", "-o", type=click.Path(), default=None, help="Save reconstructed prompt to file")
@click.pass_context
def prompt(ctx: click.Context, conversation_id: str, section: str, raw: bool, json_out: bool, save_to: Optional[str]):
    """📄 Reconstruct the complete model prompt with system instructions, tools, and history."""
    config: AntigravityConfig = ctx.obj["config"]
    scanner = ConversationScanner(config)

    if conversation_id.lower() == "latest":
        summaries = scanner.scan_all()
        if not summaries:
            console.print("[red]No conversations found.[/red]")
            return
        conv_summary = summaries[0]
        conversation_id = conv_summary.id
    else:
        conv_summary = scanner.get_summary(conversation_id)
        if not conv_summary:
            console.print(f"[red]Conversation '{conversation_id}' not found.[/red]")
            return

    from ml_mon.core.prompt_reconstructor import PromptReconstructor
    reconstructor = PromptReconstructor(config)
    reconstructed = reconstructor.reconstruct(conversation_id)

    if not reconstructed:
        console.print(f"[red]Unable to reconstruct prompt for '{conversation_id}'.[/red]")
        return

    if save_to:
        Path(save_to).write_text(reconstructed.raw_prompt_text, encoding="utf-8")
        console.print(f"[green]Saved raw prompt to:[/green] {save_to}")

    if json_out:
        import sys
        sys.stdout.write(reconstructed.model_dump_json(indent=2) + "\n")
        return

    if raw:
        import sys
        if section == "all":
            sys.stdout.write(reconstructed.raw_prompt_text + "\n")
        else:
            sec_map = {
                "system": "sec-base-persona",
                "skills": "sec-skills-plugins",
                "tools": "sec-tool-declarations",
                "memory": "sec-compaction-memory",
                "history": "sec-dynamic-history",
            }
            target_id = sec_map.get(section)
            sec = next((s for s in reconstructed.sections if s.id == target_id), None)
            if sec:
                sys.stdout.write(sec.content + "\n")
            else:
                console.print(f"[yellow]Section '{section}' not found in prompt.[/yellow]")
        return

    # Rich formatted overview
    title_text = f"📄 Reconstructed Model Prompt — {conv_summary.title or conversation_id[:8]}"
    summary_panel = Panel(
        f"  [bold]Conversation ID:[/bold]     [cyan]{conversation_id}[/cyan]\n"
        f"  [bold]Target Model:[/bold]        [yellow]{reconstructed.model_name or 'Gemini'}[/yellow]\n"
        f"  [bold]Snapshot Step:[/bold]       [white]Step {reconstructed.snapshot_step}[/white]\n"
        f"  [bold]Total Payload Size:[/bold]  [bold green]{reconstructed.total_chars:,} chars[/bold green] (~[bold yellow]{reconstructed.total_est_tokens:,} tokens[/bold yellow])\n"
        f"  [bold]Declared Tools:[/bold]      [cyan]{len(reconstructed.tools)} IDE tools registered[/cyan]\n"
        f"  [bold]Semantic Sections:[/bold]   [white]{len(reconstructed.sections)} sections reconstructed[/white]",
        title=title_text,
        border_style="magenta",
        box=box.ROUNDED,
    )
    console.print(summary_panel)

    table = Table(title="Prompt Component Breakdown", box=box.ROUNDED, header_style="bold cyan")
    table.add_column("Section", style="white")
    table.add_column("Category", style="dim")
    table.add_column("Characters", justify="right", style="cyan")
    table.add_column("Tokens", justify="right", style="bold yellow")
    table.add_column("Share", justify="right", style="green")

    for s in reconstructed.sections:
        pct = (s.est_tokens / reconstructed.total_est_tokens) * 100 if reconstructed.total_est_tokens > 0 else 0
        table.add_row(
            s.title,
            s.category,
            f"{s.char_count:,}",
            f"{s.est_tokens:,}",
            f"{pct:.1f}%",
        )
    console.print(table)


@main.command("serve")
@click.option("--host", default="127.0.0.1", help="Host interface to bind to (default: 127.0.0.1)")
@click.option("--port", "-p", default=8765, help="Port to listen on (default: 8765)")
@click.option("--open-browser/--no-open", "open_browser", default=True, help="Automatically open browser on startup")
@click.pass_context
def serve(ctx: click.Context, host: str, port: int, open_browser: bool):
    """⚡ Start the real-time web visualizer and API server."""
    import threading
    import webbrowser
    import uvicorn
    from ml_mon.api.app import create_app

    config: AntigravityConfig = ctx.obj["config"]
    app = create_app(config)

    url = f"http://{host}:{port}"
    console.print(
        Panel(
            f"  [bold green]🌐 Web Dashboard:[/bold green]     [bold cyan]{url}[/bold cyan]\n"
            f"  [bold green]📡 Streaming:[/bold green]         [cyan]Active (Server-Sent Events)[/cyan]\n"
            f"  [bold green]📁 Data Source:[/bold green]       [dim]{config.base_dir}[/dim]\n"
            f"  [bold green]🛑 To Stop:[/bold green]           [dim]Press Ctrl+C[/dim]",
            title="⚡ [bold green]gmon Real-Time Server[/bold green]",
            border_style="green",
            box=box.ROUNDED,
        )
    )

    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    uvicorn.run(app, host=host, port=port, log_level="info")


@main.command("server", hidden=True)
@click.option("--host", default="127.0.0.1", help="Host interface to bind to")
@click.option("--port", "-p", default=8765, help="Port to listen on")
@click.option("--open-browser/--no-open", "open_browser", default=True, help="Automatically open browser")
@click.pass_context
def server_alias(ctx: click.Context, host: str, port: int, open_browser: bool):
    """Alias for 'serve'."""
    ctx.invoke(serve, host=host, port=port, open_browser=open_browser)


if __name__ == "__main__":
    main()
