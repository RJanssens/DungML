"""/docs — serve bundled markdown documentation.

The docs live at the repo root in `docs/`. We find them at import time
by walking up from this package, the same trick `samples.py` uses.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Response, status

router = APIRouter(prefix="/docs", tags=["docs"])


def _find_docs_dir() -> Path | None:
    here = Path(__file__).resolve().parent
    for parent in [here, *here.parents]:
        candidate = parent / "docs"
        if candidate.is_dir() and any(candidate.glob("*.md")):
            return candidate
    return None


_DOCS_DIR = _find_docs_dir()

# Whitelist of doc ids we serve, mapped to filenames inside `_DOCS_DIR`.
# Restricting the set prevents arbitrary-file reads via the id path
# parameter.
_DOCS: dict[str, str] = {
    "dsl": "dsl.md",
    "dsl-map": "dsl-map.md",
    "dsl-features": "dsl-features.md",
    "dsl-geometry": "dsl-geometry.md",
    "dsl-tooling": "dsl-tooling.md",
}


@router.get("", response_model=list[dict])
def list_docs() -> list[dict]:
    """List available doc ids with their titles."""
    out: list[dict] = []
    for doc_id, fname in _DOCS.items():
        if _DOCS_DIR is None:
            continue
        path = _DOCS_DIR / fname
        if not path.is_file():
            continue
        # The title is the first `# ` heading, falling back to the id.
        title = doc_id
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                break
        out.append({"id": doc_id, "title": title})
    return out


@router.get("/{doc_id}")
def get_doc(doc_id: str) -> Response:
    """Return the raw markdown source of a known doc."""
    if _DOCS_DIR is None or doc_id not in _DOCS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="doc not found"
        )
    path = _DOCS_DIR / _DOCS[doc_id]
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="doc not found"
        )
    return Response(
        content=path.read_text(encoding="utf-8"),
        media_type="text/markdown; charset=utf-8",
    )
