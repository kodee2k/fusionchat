"""Terminal User Interface for fusionChat using Textual."""
from __future__ import annotations

from rich.markdown import Markdown
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Input, Label, RichLog, Static

from fusionchat.config import Config
from fusionchat.fusion import ChatMessage, FusionOrchestrator, FusionResult
from fusionchat.logging import SessionLogger


class _AboutScreen(ModalScreen[None]):
    """Simple modal showing config summary."""

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config = config

    def compose(self) -> ComposeResult:
        with Vertical(id="about"):
            yield Label("fusionChat", id="about-title")
            yield Label("Empero-style multi-model fusion.", id="about-sub")
            yield Label(f"Master: {self.config.master.model}")
            yield Label(f"Fusion models: {', '.join(m.model for m in self.config.fusion)}")
            yield Label(f"Effort: {self.config.effort}")
            yield Label(f"Log dir: {self.config.log_dir}")
            yield Button("Close", variant="primary", id="close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss()


class FusionChatTUI(App[None]):
    CSS = """
    Screen { align: center middle; }
    #main { width: 100%; height: 100%; background: #0b0c0f; }
    #chat-pane { width: 75%; height: 100%; border-right: solid #252830; }
    #side-pane { width: 25%; height: 100%; background: #111216; }
    #header { height: auto; background: #111216; color: #f0f0f5; padding: 1 2; border-bottom: solid #252830; }
    #header-title { text-style: bold; }
    #header-sub { color: #8b8f99; margin-top: 1; }
    #chat-log { width: 100%; height: 1fr; padding: 1 2; background: #0b0c0f; }
    #input-row { height: auto; padding: 1 2; background: #111216; border-top: solid #252830; }
    #msg-input { width: 1fr; margin-right: 1; }
    #send-btn { width: auto; }
    .user-bubble { background: #181a20; color: #f0f0f5; padding: 1 2; margin: 1 0; border: solid #252830; }
    .assistant-bubble { background: #111216; color: #f0f0f5; padding: 1 2; margin: 1 0; border: solid #252830; }
    .meta { color: #8b8f99; text-style: italic; margin-bottom: 1; }
    #about { width: 60; height: auto; background: #111216; border: solid #a855f7; padding: 2; }
    #about-title { text-style: bold; color: #a855f7; text-align: center; }
    #about-sub { color: #8b8f99; text-align: center; margin-bottom: 1; }
    #spinner { color: #a855f7; }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=True),
        Binding("ctrl+q", "quit", "Quit", show=False),
        Binding("ctrl+n", "new_session", "New chat", show=True),
        Binding("f1", "about", "About", show=True),
    ]

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config = config
        self.logger = SessionLogger(config.log_dir, log_prompts=config.log_prompts)
        self.logger.log_config(config)
        self.orchestrator = FusionOrchestrator(config)
        self.messages: list[ChatMessage] = []
        self.turn = 0

    def compose(self) -> ComposeResult:
        with Horizontal(id="main"):
            with Vertical(id="chat-pane"):
                yield Static(
                    f"[b]fusionChat[/b]  —  master {self.config.master.model}  ·  {len(self.config.fusion)} fusion model(s)  ·  effort {self.config.effort}",
                    id="header",
                )
                yield RichLog(id="chat-log", wrap=True, highlight=True)
                with Horizontal(id="input-row"):
                    yield Input(placeholder="Type a message…", id="msg-input")
                    yield Button("Send", variant="primary", id="send-btn")
            with Vertical(id="side-pane"):
                yield Static("[b]Session Log[/b]", classes="sidebar-heading")
                yield RichLog(id="log-view", wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#msg-input", Input).focus()
        self._log_info("Session started.")

    def _log_info(self, text: str) -> None:
        log = self.query_one("#log-view", RichLog)
        log.write(text)

    async def _append_user(self, text: str) -> None:
        chat = self.query_one("#chat-log", RichLog)
        chat.write("")
        chat.write(f"[b]You[/b]  ·  {self.config.effort}")
        chat.write(text)
        self._log_info(f"Turn {self.turn + 1}: user sent {len(text)} chars")

    async def _append_synthesis(self, result: FusionResult) -> None:
        chat = self.query_one("#chat-log", RichLog)
        panel_info = ", ".join(
            f"{p.model} ({len(p.content)} chars)" for p in result.responses
        )
        fallback = "  ·  [#ef4444]panel unavailable — direct answer[/#ef4444]" if result.used_fallback else ""
        chat.write("")
        chat.write(
            f"[b]Assistant[/b]  ·  context {result.master_context_used}  ·  panel: {panel_info}{fallback}"
        )
        chat.write(Markdown(result.synthesis))
        self._log_info(f"Synthesized {len(result.synthesis)} chars (per-fusion max {result.per_fusion_max_tokens} tokens)")

    async def _handle_send(self, text: str) -> None:
        if not text.strip():
            return
        input_widget = self.query_one("#msg-input", Input)
        input_widget.disabled = True
        send_btn = self.query_one("#send-btn", Button)
        send_btn.disabled = True
        spinner = Static("[#a855f7]●[/#a855f7] fusion panel is thinking…", id="spinner")
        await self.query_one("#chat-pane", Vertical).mount(spinner, before=self.query_one("#input-row", Horizontal))

        try:
            self.turn += 1
            await self._append_user(text)
            user_msg = ChatMessage(role="user", content=text)
            self.messages.append(user_msg)
            result = await self.orchestrator.run(self.messages)
            self.messages.append(ChatMessage(role="assistant", content=result.synthesis))
            self.logger.log_turn(self.turn, text, result)
            await self._append_synthesis(result)
        except Exception as exc:
            err = f"[#ef4444]Error: {exc}[/#ef4444]"
            self.query_one("#chat-log", RichLog).write(err)
            self.logger.log_error(self.turn, str(exc))
            self._log_info(f"ERROR: {exc}")
        finally:
            if spinner.is_attached:
                await spinner.remove()
            input_widget.value = ""
            input_widget.disabled = False
            send_btn.disabled = False
            input_widget.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "msg-input":
            self.run_worker(self._handle_send(event.value), exclusive=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "send-btn":
            inp = self.query_one("#msg-input", Input)
            self.run_worker(self._handle_send(inp.value), exclusive=True)

    def action_about(self) -> None:
        self.push_screen(_AboutScreen(self.config))

    def action_new_session(self) -> None:
        self.messages = []
        self.query_one("#chat-log", RichLog).clear()
        self._log_info("Started a new chat (conversation context cleared).")

    async def on_unmount(self) -> None:
        await self.orchestrator.close()


def run_tui(config: Config) -> None:
    app = FusionChatTUI(config)
    app.run()
