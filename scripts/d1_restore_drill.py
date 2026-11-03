"""Prepare a D1 SQL export for local restore when one row exceeds the statement limit.

Cloudflare's export can contain a large JSON value in one
``portal_collection_chunks`` INSERT. This utility rewrites only oversized chunk
rows as an empty insert followed by bounded append updates. It never changes
the source export.
"""

from __future__ import annotations

import argparse
from pathlib import Path


DEFAULT_MAX_STATEMENT_CHARS = 100_000
DEFAULT_APPEND_CHARS = 20_000


def _sql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _read_quoted(text: str, position: int) -> tuple[str, int]:
    if position >= len(text) or text[position] != "'":
        raise ValueError("Expected a SQL string literal.")
    position += 1
    value: list[str] = []
    while position < len(text):
        character = text[position]
        if character != "'":
            value.append(character)
            position += 1
            continue
        if position + 1 < len(text) and text[position + 1] == "'":
            value.append("'")
            position += 2
            continue
        return "".join(value), position + 1
    raise ValueError("Unterminated SQL string literal.")


def _split_chunk_insert(line: str) -> tuple[str, str, int, str] | None:
    prefix = 'INSERT INTO "portal_collection_chunks" ("name","version_id","chunk_no","value_json") VALUES('
    if not line.startswith(prefix) or not line.endswith(");"):
        return None
    position = len(prefix)
    name, position = _read_quoted(line, position)
    if line[position] != ",":
        raise ValueError("Invalid collection chunk name separator.")
    version, position = _read_quoted(line, position + 1)
    if line[position] != ",":
        raise ValueError("Invalid collection chunk version separator.")
    number_end = line.index(",", position + 1)
    chunk_no = int(line[position + 1:number_end])
    value, position = _read_quoted(line, number_end + 1)
    if line[position:] != ");":
        raise ValueError("Unexpected trailing SQL after collection chunk.")
    return name, version, chunk_no, value


def prepare_export(source: Path, target: Path, *, max_statement_chars: int = DEFAULT_MAX_STATEMENT_CHARS, append_chars: int = DEFAULT_APPEND_CHARS) -> int:
    if source.resolve() == target.resolve():
        raise ValueError("The prepared export must be written to a different file.")
    if max_statement_chars < 1 or append_chars < 1:
        raise ValueError("Statement and append limits must be positive.")
    rewritten = 0
    output: list[str] = []
    for line in source.read_text(encoding="utf-8").splitlines():
        if len(line) <= max_statement_chars:
            output.append(line)
            continue
        parsed = _split_chunk_insert(line)
        if parsed is None:
            raise ValueError("An oversized SQL statement is not a portal collection chunk insert.")
        name, version, chunk_no, value = parsed
        output.append(
            'INSERT INTO "portal_collection_chunks" '
            '("name","version_id","chunk_no","value_json") VALUES('
            f"{_sql_quote(name)},{_sql_quote(version)},{chunk_no},'');"
        )
        for start in range(0, len(value), append_chars):
            output.append(
                'UPDATE "portal_collection_chunks" SET value_json = value_json || '
                f"{_sql_quote(value[start:start + append_chars])} "
                f"WHERE name = {_sql_quote(name)} AND version_id = {_sql_quote(version)} AND chunk_no = {chunk_no};"
            )
        rewritten += 1
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(output) + "\n", encoding="utf-8")
    return rewritten


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Private SQL export path")
    parser.add_argument("--output", type=Path, required=True, help="Prepared SQL path")
    parser.add_argument("--max-statement-chars", type=int, default=DEFAULT_MAX_STATEMENT_CHARS)
    parser.add_argument("--append-chars", type=int, default=DEFAULT_APPEND_CHARS)
    arguments = parser.parse_args()
    rewritten = prepare_export(
        arguments.input,
        arguments.output,
        max_statement_chars=arguments.max_statement_chars,
        append_chars=arguments.append_chars,
    )
    print(f"Prepared export with {rewritten} oversized collection row(s) rewritten.")


if __name__ == "__main__":
    main()
