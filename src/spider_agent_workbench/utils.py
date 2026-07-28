

def _render(cell) -> str:
    if cell is None:
        return "NULL"
    return str(cell)

def format_result_table(headers: list[str], rows: list[tuple]) -> str:
    """Format rows as a pipe-separated text table (LLM-friendly, monospace-safe)."""
    str_rows = [[_render(cell) for cell in row] for row in rows]
    widths = [max(len(str(h)), *(len(cell) for cell in col)) for h, col in zip(headers, zip(*str_rows))]
    header_line = " | ".join(str(h).ljust(w) for h, w in zip(headers, widths))
    sep_line = "-+-".join("-" * w for w in widths)
    body_lines = [" | ".join(cell.ljust(w) for cell, w in zip(row, widths)) for row in str_rows]
    return "\n".join([header_line, sep_line, *body_lines])