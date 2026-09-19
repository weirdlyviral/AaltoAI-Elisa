"""Safety layer for the Elisa anonymisation pipeline.

Everything that touches raw data or leaves the process goes through this module:

* :func:`load_raw` is the only sanctioned reader of the raw dataset and is the
  only place that populates the in-memory identifier registry ``_REGISTRY``.
* :func:`scrub` / :func:`check_text` / :func:`check_file` / :func:`leak_guard`
  detect and redact identifiers that escaped into artefacts.
* :func:`safe_write_json` / :func:`safe_write_df` stage every write inside
  ``$SECURE_DIR/tmp`` and only promote it to its target once it is proven clean.
* :func:`llm_gateway` is the only network egress and refuses to send anything
  that contains a registered identifier.

The registry is never persisted and never printed.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import json
import os
import re
import shutil
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlparse

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

SEED = 42
ID_COLUMNS: tuple[str, ...] = ("msisdn", "imsi", "imei")
TAC_LENGTH = 8
DEFAULT_DATASET_FILE = "elisa_aaltoai_hackathon_2026_mock.parquet"

#: The shipped dataset names the cell column ``enb_id``; the pipeline (and the
#: challenge brief) call it ``enb``. Normalise at load time so downstream code
#: has one spelling.
COLUMN_ALIASES = {"enb_id": "enb"}

FINDING_KINDS = frozenset({"registered_id", "long_digit_run"})

TABULAR_SUFFIXES = frozenset({".csv", ".parquet"})
# .ipynb is JSON, and a committed notebook carries its stored cell outputs -
# a direct route for raw rows to reach the repo - so it is scanned as text.
TEXT_SUFFIXES = frozenset(
    {".json", ".jsonl", ".md", ".html", ".txt", ".log", ".yaml", ".yml", ".ipynb"}
)
SCANNABLE_SUFFIXES = TABULAR_SUFFIXES | TEXT_SUFFIXES

_TOKEN_RE = re.compile(r"[A-Za-z0-9]{6,}")
_LONG_DIGIT_RE = re.compile(r"\d{10,}")

#: Distinct raw identifier values, in memory only. Never written, never printed.
_REGISTRY: set[str] = set()

LLM_TIMEOUT_SECONDS = 120.0
LLM_MAX_RETRIES = 2
LLM_BACKOFF_SECONDS = 5.0
LLM_LOG_PATH = Path("outputs") / "llm_calls.jsonl"


#: Significant digits kept for every float written to an artefact. Full float
#: repr produces long digit runs that the leak guard (correctly) treats as
#: suspicious, so we round at the boundary instead of loosening the guard.
FLOAT_SIGNIFICANT_DIGITS = 6


def round_float(value) -> float | None:
    """Coerce to a plain, rounded float (or ``None`` for null/non-finite)."""
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    import math

    if not math.isfinite(out):
        return None
    return float(f"{out:.{FLOAT_SIGNIFICANT_DIGITS}g}")


class LeakError(RuntimeError):
    """Raised when data that may contain an identifier would escape."""


# --------------------------------------------------------------------------- #
# Environment / paths
# --------------------------------------------------------------------------- #


def secure_dir() -> Path:
    """Return ``$SECURE_DIR`` as a resolved path."""
    value = os.environ.get("SECURE_DIR", "").strip()
    if not value:
        raise RuntimeError("SECURE_DIR is not set; add it to .env (see .env.example).")
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise RuntimeError("SECURE_DIR does not point at an existing directory.")
    return path


def secure_tmp_dir() -> Path:
    """Return ``$SECURE_DIR/tmp``, creating it if needed."""
    tmp = secure_dir() / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    return tmp


def dataset_path() -> Path:
    """Default raw dataset location: ``$SECURE_DIR/$DATASET_FILE``."""
    name = os.environ.get("DATASET_FILE", "").strip() or DEFAULT_DATASET_FILE
    return secure_dir() / name


def _assert_inside_secure_dir(path: Path) -> Path:
    resolved = Path(path).expanduser().resolve()
    root = secure_dir()
    if resolved != root and root not in resolved.parents:
        raise PermissionError("Refusing to read raw data from outside SECURE_DIR.")
    return resolved


# --------------------------------------------------------------------------- #
# 1. Raw loading + registry
# --------------------------------------------------------------------------- #


def register_identifiers(df: pd.DataFrame) -> int:
    """Add every distinct identifier value in ``df`` to the registry.

    Returns the registry size (a count only - values are never surfaced).
    """
    for column in ID_COLUMNS:
        if column not in df.columns:
            continue
        values = df[column].dropna().astype(str).unique()
        _REGISTRY.update(v.strip() for v in values if v.strip())
    return len(_REGISTRY)


def registry_size() -> int:
    """Number of registered identifier values (safe to print)."""
    return len(_REGISTRY)


def load_raw(path: str | os.PathLike[str] | None = None) -> pd.DataFrame:
    """Load the raw dataset from inside ``SECURE_DIR`` and register its ids.

    Identifier columns are read as strings so leading zeros survive;
    ``time_start`` is parsed as a datetime.
    """
    target = _assert_inside_secure_dir(Path(path) if path is not None else dataset_path())
    if not target.is_file():
        raise FileNotFoundError(f"Raw dataset not found at {target}")

    suffix = target.suffix.lower()
    if suffix == ".csv":
        df = pd.read_csv(
            target,
            dtype={column: "string" for column in ID_COLUMNS},
            keep_default_na=True,
            low_memory=False,
        )
    elif suffix == ".parquet":
        df = pd.read_parquet(target)
    else:
        raise ValueError(f"Unsupported raw format '{suffix}'; expected .csv or .parquet.")

    df = df.rename(columns={k: v for k, v in COLUMN_ALIASES.items() if k in df.columns})

    for column in ID_COLUMNS:
        if column in df.columns:
            df[column] = df[column].astype("string").str.strip()

    if "time_start" in df.columns:
        df["time_start"] = parse_time_start(df["time_start"])

    register_identifiers(df)
    return df


def parse_time_start(series: pd.Series) -> pd.Series:
    """Parse ``time_start`` to datetime, handling epoch-integer storage.

    The shipped parquet stores ``time_start`` as int64 epoch seconds. Passing
    those straight to ``pd.to_datetime`` would read them as nanoseconds and
    silently place every row in 1970, so the unit is chosen by magnitude.
    """
    if pd.api.types.is_datetime64_any_dtype(series):
        return series
    if pd.api.types.is_numeric_dtype(series):
        magnitude = pd.to_numeric(series, errors="coerce").abs().max()
        if pd.isna(magnitude):
            return pd.to_datetime(series, errors="coerce")
        for limit, unit in ((1e11, "s"), (1e14, "ms"), (1e17, "us")):
            if magnitude < limit:
                return pd.to_datetime(series, unit=unit, errors="coerce")
        return pd.to_datetime(series, unit="ns", errors="coerce")
    return pd.to_datetime(series, errors="coerce")


def add_tac(df: pd.DataFrame) -> pd.DataFrame:
    """Return ``df`` with the derived ``tac`` column (first 8 chars of imei)."""
    if "imei" not in df.columns:
        raise KeyError("imei column required to derive tac")
    out = df.copy()
    out["tac"] = out["imei"].astype("string").str.slice(0, TAC_LENGTH)
    return out


# --------------------------------------------------------------------------- #
# 2. Scrubbing
# --------------------------------------------------------------------------- #


def scrub(text: Any) -> str:
    """Redact registered identifiers, then any remaining long digit runs."""
    if text is None:
        return ""
    value = str(text)
    value = _TOKEN_RE.sub(
        lambda m: "[REDACTED]" if m.group(0) in _REGISTRY else m.group(0), value
    )
    return _LONG_DIGIT_RE.sub("[DIGITS]", value)


# --------------------------------------------------------------------------- #
# 3. Findings
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Finding:
    """A potential leak. Deliberately carries no copy of the matched value."""

    source: str
    location: str
    kind: str

    def __post_init__(self) -> None:
        if self.kind not in FINDING_KINDS:
            raise ValueError(f"Unknown finding kind: {self.kind!r}")
        # Defensive: even the coordinates get scrubbed so a repr can never leak.
        object.__setattr__(self, "source", scrub(self.source))
        object.__setattr__(self, "location", scrub(self.location))


def _scan_value(value: Any, source: str, location: str) -> list[Finding]:
    """Scan one scalar for registered ids and residual long digit runs."""
    findings: list[Finding] = []
    text = "" if value is None else str(value)
    if not text:
        return findings

    def _replace(match: re.Match[str]) -> str:
        if match.group(0) in _REGISTRY:
            findings.append(Finding(source, location, "registered_id"))
            return "[REDACTED]"
        return match.group(0)

    residual = _TOKEN_RE.sub(_replace, text)
    findings.extend(
        Finding(source, location, "long_digit_run") for _ in _LONG_DIGIT_RE.finditer(residual)
    )
    return findings


def check_text(text: Any, source: str) -> list[Finding]:
    """Scan free text; ``location`` is the 1-based line number."""
    if text is None:
        return []
    findings: list[Finding] = []
    for lineno, line in enumerate(str(text).splitlines(), start=1):
        findings.extend(_scan_value(line, source, f"line {lineno}"))
    return findings


def _check_tabular(path: Path) -> list[Finding]:
    source = str(path)
    if path.suffix.lower() == ".csv":
        frame = pd.read_csv(path, dtype=str, keep_default_na=False, low_memory=False)
    else:
        frame = pd.read_parquet(path).astype(str)

    findings: list[Finding] = []
    for column in frame.columns:
        findings.extend(_scan_value(column, source, "<header>"))
        series = frame[column].astype(str)
        for value in series.unique():
            findings.extend(_scan_value(value, source, str(column)))
    return findings


#: Notebook output MIME types whose payload is base64-encoded binary. A real
#: identifier cannot be read out of one, but the base64 alphabet throws up
#: incidental 10+ digit runs, so these payloads are skipped by value.
BINARY_MIME_PREFIXES = ("image/", "video/", "audio/", "application/pdf")


def _flatten(value: Any) -> str:
    """Notebook fields are either a string or a list of string chunks."""
    if isinstance(value, list):
        return "".join(str(chunk) for chunk in value)
    return "" if value is None else str(value)


def _check_notebook(path: Path) -> list[Finding]:
    """Scan a notebook cell by cell.

    Stored cell outputs are the real leak route here - a stray ``df.head()``
    lands raw rows straight into the committed file - so they are scanned along
    with the source. Base64 image payloads are skipped (see
    :data:`BINARY_MIME_PREFIXES`); everything else is treated as text.
    """
    source_name = str(path)
    raw = path.read_text(encoding="utf-8", errors="replace")
    try:
        notebook = json.loads(raw)
    except json.JSONDecodeError:
        # Not valid JSON - fall back to a conservative whole-file text scan.
        return check_text(raw, source_name)

    findings: list[Finding] = []
    for index, cell in enumerate(notebook.get("cells", []), start=1):
        if not isinstance(cell, dict):
            continue
        findings.extend(
            _scan_value(_flatten(cell.get("source")), source_name, f"cell {index} source")
        )
        for output in cell.get("outputs", []) or []:
            if not isinstance(output, dict):
                continue
            location = f"cell {index} output"
            findings.extend(_scan_value(_flatten(output.get("text")), source_name, location))
            findings.extend(
                _scan_value(_flatten(output.get("traceback")), source_name, location)
            )
            for mime, payload in (output.get("data") or {}).items():
                if str(mime).startswith(BINARY_MIME_PREFIXES):
                    continue
                findings.extend(_scan_value(_flatten(payload), source_name, location))
    return findings


def check_file(path: str | os.PathLike[str]) -> list[Finding]:
    """Scan a single artefact. Unsupported suffixes return no findings."""
    target = Path(path)
    suffix = target.suffix.lower()
    if suffix == ".ipynb":
        return _check_notebook(target)
    if suffix in TABULAR_SUFFIXES:
        return _check_tabular(target)
    if suffix in TEXT_SUFFIXES:
        return check_text(target.read_text(encoding="utf-8", errors="replace"), str(target))
    return []


# --------------------------------------------------------------------------- #
# 4. Leak guard
# --------------------------------------------------------------------------- #


def leak_guard(directory: str | os.PathLike[str] = "outputs") -> bool:
    """Scan ``directory`` recursively and print a summary table.

    Returns ``True`` when the directory is clean.
    """
    root = Path(directory)
    if not root.exists():
        print(f"leak_guard: {root} does not exist - nothing to scan.")
        return True

    counts: dict[tuple[str, str, str], int] = {}
    scanned = 0
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        if path.suffix.lower() not in SCANNABLE_SUFFIXES:
            continue
        scanned += 1
        for finding in check_file(path):
            key = (finding.source, finding.location, finding.kind)
            counts[key] = counts.get(key, 0) + 1

    print(f"leak_guard: scanned {scanned} file(s) under {root}")
    if not counts:
        print("leak_guard: CLEAN - no findings.")
        return True

    rows = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    width_file = max(len("file"), max(len(k[0]) for k, _ in rows))
    width_loc = max(len("location"), max(len(k[1]) for k, _ in rows))
    width_kind = max(len("kind"), max(len(k[2]) for k, _ in rows))
    header = f"{'file':<{width_file}}  {'location':<{width_loc}}  {'kind':<{width_kind}}  count"
    print(header)
    print("-" * len(header))
    for (src, loc, kind), count in rows:
        print(f"{src:<{width_file}}  {loc:<{width_loc}}  {kind:<{width_kind}}  {count}")
    print(f"leak_guard: FAIL - {sum(counts.values())} finding(s) in {len({k[0] for k, _ in rows})} file(s).")
    return False


# --------------------------------------------------------------------------- #
# 5. safe_main
# --------------------------------------------------------------------------- #


def safe_main(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap a CLI entry point so no exception can leak raw values."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except SystemExit:
            raise
        except BaseException as exc:  # noqa: BLE001 - deliberate catch-all
            formatted = traceback.format_exception(type(exc), exc, exc.__traceback__)
            print(f"ERROR [{type(exc).__name__}]: {scrub(exc)}", file=sys.stderr)
            print(scrub("".join(formatted)), file=sys.stderr)
            sys.exit(1)

    return wrapper


# --------------------------------------------------------------------------- #
# 6. Guarded writes
# --------------------------------------------------------------------------- #


def _staged_write(target: Path, writer: Callable[[Path], None]) -> Path:
    """Write via ``$SECURE_DIR/tmp``, scan, and promote only when clean."""
    target = Path(target)
    suffix = target.suffix.lower()
    if suffix not in SCANNABLE_SUFFIXES:
        raise ValueError(f"Refusing to write unscannable artefact type '{suffix}'.")

    stage = secure_tmp_dir() / f"stage.{os.getpid()}.{target.name}"
    writer(stage)
    try:
        findings = check_file(stage)
        if findings:
            kinds = sorted({f.kind for f in findings})
            raise LeakError(
                f"Refusing to write {target}: {len(findings)} finding(s) ({', '.join(kinds)})."
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(stage), str(target))
    finally:
        if stage.exists():
            stage.unlink()
    return target


def safe_write_json(obj: Any, path: str | os.PathLike[str]) -> Path:
    """Serialise ``obj`` to JSON at ``path`` only if it contains no identifiers."""

    def _write(stage: Path) -> None:
        stage.write_text(json.dumps(obj, indent=2, sort_keys=False, default=str), encoding="utf-8")

    return _staged_write(Path(path), _write)


def safe_write_text(text: str, path: str | os.PathLike[str]) -> Path:
    """Write text (yaml/md/txt/...) at ``path`` only if it contains no identifiers."""

    def _write(stage: Path) -> None:
        stage.write_text(text, encoding="utf-8")

    return _staged_write(Path(path), _write)


def safe_write_df(df: pd.DataFrame, path: str | os.PathLike[str]) -> Path:
    """Write ``df`` only if it carries no identifier column and no identifier values."""
    present = [column for column in ID_COLUMNS if column in df.columns]
    if present:
        raise LeakError(f"Refusing to write a DataFrame with identifier column(s): {present}.")

    target = Path(path)
    suffix = target.suffix.lower()
    if suffix not in TABULAR_SUFFIXES:
        raise ValueError(f"safe_write_df supports .csv/.parquet, got '{suffix}'.")

    def _write(stage: Path) -> None:
        if suffix == ".csv":
            df.to_csv(stage, index=False)
        else:
            df.to_parquet(stage, index=False)

    return _staged_write(target, _write)


# --------------------------------------------------------------------------- #
# 7. LLM gateway
# --------------------------------------------------------------------------- #


def _append_jsonl(record: dict[str, Any], path: Path | None = None) -> None:
    """Append one scrubbed JSON record, refusing if the line is not clean."""
    path = Path(path) if path is not None else Path(LLM_LOG_PATH)
    line = json.dumps(record, ensure_ascii=False, default=str)
    findings = check_text(line, str(path))
    if findings:
        raise LeakError(f"Refusing to log LLM call: {len(findings)} finding(s).")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _is_retryable(exc: BaseException) -> bool:
    import openai

    if isinstance(exc, (openai.APITimeoutError, openai.APIConnectionError)):
        return True
    if isinstance(exc, openai.APIStatusError):
        return getattr(exc, "status_code", 0) >= 500
    return False


def llm_gateway(prompt: str, purpose: str, system: str | None = None) -> str:
    """Send ``prompt`` to the configured LLM after proving it carries no ids."""
    import openai

    findings = check_text(prompt, f"llm_prompt:{purpose}")
    findings += check_text(system, f"llm_system:{purpose}")
    if findings:
        kinds = sorted({f.kind for f in findings})
        raise LeakError(
            f"Refusing LLM call '{purpose}': {len(findings)} finding(s) ({', '.join(kinds)})."
        )

    base_url = os.environ.get("LLM_BASE_URL", "").strip()
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    model = os.environ.get("LLM_MODEL", "").strip()
    if not (base_url and api_key and model):
        raise RuntimeError("LLM_BASE_URL, LLM_API_KEY and LLM_MODEL must all be set in .env.")

    client = openai.OpenAI(base_url=base_url, api_key=api_key, timeout=LLM_TIMEOUT_SECONDS)

    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    last_error: BaseException | None = None
    content: str | None = None
    for attempt in range(LLM_MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0,
                timeout=LLM_TIMEOUT_SECONDS,
            )
            content = response.choices[0].message.content or ""
            break
        except BaseException as exc:  # noqa: BLE001 - narrowed by _is_retryable
            last_error = exc
            if attempt < LLM_MAX_RETRIES and _is_retryable(exc):
                time.sleep(LLM_BACKOFF_SECONDS)
                continue
            raise

    if content is None:  # pragma: no cover - defensive
        raise RuntimeError(f"LLM call failed: {type(last_error).__name__}")

    _append_jsonl(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "purpose": purpose,
            "model": model,
            "endpoint_host": urlparse(base_url).hostname or "",
            "prompt": scrub(prompt if not system else f"[system]\n{system}\n[user]\n{prompt}"),
            "response": scrub(content),
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        }
    )
    return content


# --------------------------------------------------------------------------- #
# 8. Temp hygiene
# --------------------------------------------------------------------------- #


def wipe_secure_tmp() -> int:
    """Delete everything in ``$SECURE_DIR/tmp``; print names and a count only."""
    tmp = secure_tmp_dir()
    removed: list[str] = []
    for entry in sorted(tmp.iterdir()):
        removed.append(scrub(entry.name))
        if entry.is_dir():
            shutil.rmtree(entry)
        else:
            entry.unlink()
    for name in removed:
        print(f"  removed: {name}")
    print(f"wipe_secure_tmp: removed {len(removed)} entr(y/ies) from SECURE_DIR/tmp")
    return len(removed)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


@safe_main
def main(argv: Iterable[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m src.safety")
    subparsers = parser.add_subparsers(dest="command", required=True)

    guard = subparsers.add_parser("guard", help="Scan a directory for leaked identifiers.")
    guard.add_argument("--dir", default="outputs", help="Directory to scan (default: outputs)")

    subparsers.add_parser("wipe-tmp", help="Delete everything in $SECURE_DIR/tmp.")

    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.command == "guard":
        load_raw()  # registry only; no rows are inspected or printed
        print(f"registry: {registry_size()} distinct identifier values loaded")
        sys.exit(0 if leak_guard(args.dir) else 1)

    if args.command == "wipe-tmp":
        wipe_secure_tmp()
        sys.exit(0)


if __name__ == "__main__":
    main()
