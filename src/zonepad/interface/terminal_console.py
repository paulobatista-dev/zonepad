from __future__ import annotations

import sys
from collections.abc import Sequence


class CalibrationCancelled(Exception):
    """Raised when the interactive user cancels or closes stdin."""


class TerminalConsole:
    @property
    def is_interactive(self) -> bool:
        return sys.stdin.isatty() and sys.stdout.isatty()

    def say(self, message: str) -> None:
        print(message, flush=True)

    def ask_choice(self, message: str, choices: Sequence[str]) -> int | None:
        for index, choice in enumerate(choices, 1):
            self.say(f"  {index}. {choice}")
        while True:
            value = self._read(f"{message} (q para cancelar): ").strip().lower()
            if value in {"q", "c", "cancelar"}:
                return None
            try:
                result = int(value) - 1
            except ValueError:
                self.say("Informe o número de uma opção.")
                continue
            if 0 <= result < len(choices):
                return result
            self.say("Opção fora da lista.")

    def ask_confirm(self, message: str, *, default: bool = False) -> bool:
        suffix = "S/n" if default else "s/N"
        while True:
            value = self._read(f"{message} [{suffix}]: ").strip().lower()
            if not value:
                return default
            if value in {"s", "sim", "y", "yes"}:
                return True
            if value in {"n", "nao", "não", "no"}:
                return False
            self.say("Responda s ou n.")

    def show_progress(self, message: str, seconds_left: float) -> None:
        self.say(f"{message}: {max(0.0, seconds_left):.0f} s restantes")

    @staticmethod
    def _read(prompt: str) -> str:
        try:
            return input(prompt)
        except EOFError as exc:
            raise CalibrationCancelled from exc
