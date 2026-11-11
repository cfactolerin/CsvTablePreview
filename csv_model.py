import csv
import html
import io
import json
import re
import unicodedata


DARK_PALETTE = [
    "#e6b566", "#72c7b8", "#91b9ee", "#d9a0d2", "#b6cf7a",
    "#ef9b91", "#83cce0", "#c4afe8", "#cfc178", "#97c6a7",
]
LIGHT_PALETTE = [
    "#936000", "#087668", "#2865a0", "#96538e", "#546d15",
    "#a53d34", "#096f88", "#7650a4", "#766500", "#35774c",
]


def make_syntax(delimiter):
    escaped_delimiter = r"\t" if delimiter == "\t" else re.escape(delimiter)
    excluded = escaped_delimiter + r"\r\n"
    lines = ["%YAML 1.2", "---", "name: CSV Table Preview", "hidden: true",
             "scope: text.csv.csvpreview", "contexts:"]

    def rule(pattern, target):
        lines.append("    - match: " + json.dumps(pattern))
        lines.append("      set: " + target)

    for index in range(10):
        following = "field{}".format((index + 1) % 10)
        for context in (("main",) if index == 0 else ()) + ("field{}".format(index),):
            lines.append("  " + context + ":")
            lines.append("    - meta_scope: csvpreview.column{}".format(index))
            if context == "main":
                lines.append("    - match: '\\x{FEFF}'")
            if context != "main":
                rule("$", "main")
            rule(escaped_delimiter, following)
            rule('"', "quoted{}".format(index))
            rule('[^' + excluded + '\"]', "unquoted{}".format(index))
        lines.append("  unquoted{}:".format(index))
        lines.append("    - meta_scope: csvpreview.column{}".format(index))
        rule("$", "main")
        rule(escaped_delimiter, following)
        lines.append("    - match: " + json.dumps("[^" + excluded + "]+"))
        lines.append("  quoted{}:".format(index))
        lines.append("    - meta_scope: csvpreview.column{}".format(index))
        lines.append("    - match: '\"\"'")
        rule('"', "after{}".format(index))
        lines.append("  after{}:".format(index))
        lines.append("    - meta_scope: csvpreview.column{}".format(index))
        rule("$", "main")
        rule(escaped_delimiter, following)
    return "\n".join(lines) + "\n"


def bounded_int(settings, key, default, minimum, maximum):
    value = settings.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return max(minimum, min(maximum, value))


def detect_delimiter(text, filename, override=None):
    if override is not None:
        if not isinstance(override, str) or len(override) != 1 or override in '\r\n"':
            raise ValueError("The delimiter must be one character other than a quote or newline.")
        return override
    if filename.lower().endswith((".tsv", ".tab")):
        return "\t"
    try:
        return csv.Sniffer().sniff(text[:8192], delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


def field_spans(raw, offset, delimiter):
    end = len(raw)
    if raw.endswith("\r\n"):
        end -= 2
    elif raw.endswith(("\r", "\n")):
        end -= 1
    if end == 0:
        return []
    spans = []
    start = 0
    position = 0
    quoted = False
    while position < end:
        char = raw[position]
        if quoted:
            if char == '"':
                if position + 1 < end and raw[position + 1] == '"':
                    position += 1
                else:
                    quoted = False
        elif position == start and char == '"':
            quoted = True
        elif char == delimiter:
            spans.append((offset + start, offset + position))
            start = position + 1
        position += 1
    spans.append((offset + start, offset + end))
    return spans


def parse_csv(text, filename, settings):
    max_rows = bounded_int(settings, "max_rows", 500, 1, 2000)
    max_columns = bounded_int(settings, "max_columns", 100, 1, 200)
    bom = 1 if text.startswith("\ufeff") else 0
    content = text[bom:]
    delimiter = detect_delimiter(content, filename, settings.get("delimiter"))
    line_ends = [match.end() for match in re.finditer(r"\r\n|\r|\n", content)]
    rows = []
    spans = []
    truncated_rows = False
    truncated_columns = False
    offset = 0
    reader = csv.reader(io.StringIO(content, newline=""), delimiter=delimiter, strict=True)
    for row in reader:
        if len(rows) == max_rows:
            truncated_rows = True
            break
        end = line_ends[reader.line_num - 1] if reader.line_num <= len(line_ends) else len(content)
        regions = field_spans(content[offset:end], offset + bom, delimiter)
        if len(regions) != len(row):
            raise ValueError("Could not map a CSV record to the source text.")
        truncated_columns = truncated_columns or len(row) > max_columns
        rows.append(row[:max_columns])
        spans.append(regions[:max_columns])
        offset = end
    return {
        "rows": rows, "spans": spans, "delimiter": delimiter,
        "columns": max([0] + [len(row) for row in rows]),
        "truncated_rows": truncated_rows, "truncated_columns": truncated_columns,
    }


def rgb(color):
    color = color.lstrip("#")[:6]
    if len(color) == 3:
        color = "".join(char * 2 for char in color)
    if len(color) != 6 or not re.match(r"^[0-9a-fA-F]+$", color):
        return (32, 32, 32)
    return tuple(int(color[index:index + 2], 16) for index in (0, 2, 4))


def mix(first, second, amount):
    return "#" + "".join("{:02x}".format(round(a * (1 - amount) + b * amount))
                         for a, b in zip(rgb(first), rgb(second)))


def palette_for(background):
    values = rgb(background)
    return list(DARK_PALETTE if sum(values) < 384 else LIGHT_PALETTE)


def display_width(value):
    return sum(0 if unicodedata.combining(char) else
               2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
               for char in value)


def clip_cell(value, width):
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = value.replace("\n", " ↵ ").replace("\t", " ⇥ ")
    value = "".join(char if not unicodedata.category(char).startswith("C") else "�"
                    for char in value)
    if display_width(value) <= width:
        return value
    result = []
    used = 0
    for char in value:
        size = display_width(char)
        if used + size > width - 1:
            break
        result.append(char)
        used += size
    return "".join(result) + "…"


def column_page(model, settings, start, available_chars):
    rows = model["rows"]
    count = model["columns"]
    if not count:
        return 0, [], 0
    start = max(0, min(count - 1, start))
    cap = bounded_int(settings, "max_cell_width", 32, 8, 80)
    widths = []
    used = 0
    for column in range(start, count):
        width = max([8] + [display_width(clip_cell(row[column], cap))
                           for row in rows if column < len(row)])
        # ST3 cannot size inline cells in pixels, so reserve space for CSS padding.
        width = min(width, max(8, available_chars - 6))
        if widths and used + width + 4 > available_chars:
            break
        widths.append(width)
        used += width + 4
    return start, widths, start + len(widths)


def copy_text(model):
    output = io.StringIO(newline="")
    # A CRLF writer quotes lone CRs in cells; replace only the record terminator.
    writer = csv.writer(output, delimiter="\t", lineterminator="\r\n")
    for row in model["rows"]:
        writer.writerow(row)
        output.seek(output.tell() - 2)
        output.truncate()
        output.write("\n")
    return output.getvalue()


def render_preview(model, filename, settings, colors, background, foreground,
                   start=0, available_chars=80, font_face="monospace"):
    start, widths, end = column_page(model, settings, start, available_chars)
    border = mix(background, foreground, 0.2)
    escaped = lambda value: html.escape(str(value), quote=True)
    body = [
        '<body id="csv-table-preview"><style>',
        'body { color: %s; margin: 8px; }' % foreground,
        '.meta { margin-bottom: 8px; }',
        '.row { margin: 0; padding: 0; }',
        '.cell { border-right: 1px solid %s; border-bottom: 1px solid %s;'
        ' padding: 5px 7px; font-family: "%s"; }' % (border, border, escaped(font_face)),
        'a { text-decoration: none; }',
        '</style>',
        '<div class="meta"><b>{}</b> · {} rows · {} columns</div>'.format(
            escaped(filename), len(model["rows"]), model["columns"]),
    ]
    if not model["columns"]:
        return "".join(body) + "<p>No data.</p></body>", start, end
    previous = '<a href="columns:{}">‹ Previous</a>'.format(max(0, start - len(widths))) if start else ""
    following = '<a href="columns:{}">Next ›</a>'.format(end) if end < model["columns"] else ""
    body.append('<div class="meta">{} &nbsp; Columns {}–{} of {} &nbsp; {}</div>'.format(
        previous, start + 1, end, model["columns"], following))
    body.append('<div class="meta">Read-only · click a cell to select its source · '
                '<a href="select-copy">Select &amp; copy</a> · '
                '<a href="refresh">Refresh</a> · <a href="close">Close preview</a></div>')
    if model["truncated_rows"] or model["truncated_columns"]:
        body.append('<div class="meta">Preview limit reached; the source is unchanged.</div>')
    header = settings.get("first_row_is_header", True)
    for row_index, row in enumerate(model["rows"]):
        body.append('<div class="row">')
        for index, width in enumerate(widths):
            column = start + index
            color = colors[column % len(colors)]
            tint = mix(background, color, 0.23 if header and row_index == 0 else 0.09)
            value = row[column] if column < len(row) else ""
            label = clip_cell(value, width)
            label += " " * (width - display_width(label))
            label = escaped(label).replace(" ", "&nbsp;") or "&nbsp;"
            style = 'color:{};background-color:{};'.format(color, tint)
            # Matching font weight keeps the padded columns aligned on older minihtml.
            body.append('<a class="cell" href="cell:{}:{}" style="{}">{}</a>'.format(
                row_index, column, style, label))
        body.append('</div>')
    body.append('</body>')
    return "".join(body), start, end
