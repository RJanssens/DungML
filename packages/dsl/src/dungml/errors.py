"""Error types raised by the parser and validator.

Each carries a source location so the editor can render squigglies.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DmapError(Exception):
    message: str
    line: int = 0
    column: int = 0
    end_line: int = 0
    end_column: int = 0

    def __str__(self) -> str:
        if self.line:
            return f"{self.message} (line {self.line}, col {self.column})"
        return self.message


class DmapParseError(DmapError):
    """Lark/grammar-level parse failure."""


@dataclass
class Diagnostic:
    """A single validator finding."""
    severity: str  # "error" | "warning"
    message: str
    line: int = 0
    column: int = 0
    end_line: int = 0
    end_column: int = 0

    def __str__(self) -> str:
        return f"[{self.severity}] {self.message} (line {self.line}, col {self.column})"


@dataclass
class DmapValidationError(DmapError):
    diagnostics: list[Diagnostic] = field(default_factory=list)
