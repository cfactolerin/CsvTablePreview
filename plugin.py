import csv
import binascii
import hashlib
import json
import os

import sublime
import sublime_plugin

from .csv_model import bounded_int, make_syntax, palette_for, parse_csv, render_preview


SETTINGS = "CsvTablePreview.sublime-settings"
PREVIEWS = {}
PENDING = set()
REVISIONS = {}
LAYOUTS = {}
UNLOADING = False
WATCH_EPOCH = 0


def is_source(view):
    return (not view.settings().has("csv_preview_source")
            and os.path.splitext(view.file_name() or "")[1].lower() in (".csv", ".tsv", ".tab"))


def source_for(view):
    source_id = view.settings().get("csv_preview_source")
    if source_id is None:
        return view
    info = PREVIEWS.get(source_id)
    return info["source"] if info else None


def options():
    settings = sublime.load_settings(SETTINGS)
    keys = ("max_rows", "max_columns", "max_cell_width", "max_source_chars",
            "first_row_is_header", "delimiter")
    return {key: settings.get(key) for key in keys if settings.has(key)}


def install_palette(source, info):
    style = source.style()
    background = style.get("background", "#202020")
    foreground = style.get("foreground", "#dddddd")
    colors = palette_for(background)
    globals_ = {key: style[key] for key in (
        "background", "foreground", "caret", "selection", "selection_foreground",
        "line_highlight", "find_highlight", "find_highlight_foreground", "invisibles"
    ) if key in style}
    scheme = {"name": "CSV Table Preview", "globals": globals_, "rules": [
        {"scope": "csvpreview.column{}".format(index), "foreground": color}
        for index, color in enumerate(colors)
    ]}
    data = json.dumps(scheme, sort_keys=True)
    filename = "CsvTablePreview-{}.sublime-color-scheme".format(
        hashlib.sha256(data.encode("utf-8")).hexdigest()[:16])
    path = os.path.join(sublime.packages_path(), "User", filename)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(data)
    resource = "Packages/User/" + filename
    info.update(colors=colors, background=background, foreground=foreground,
                scheme=resource)

    def apply_when_indexed(attempt=0):
        if not source.is_valid() or PREVIEWS.get(source.id()) is not info:
            return
        # ST3 discovers new color-scheme resources asynchronously after a file write.
        if resource in sublime.find_resources(filename):
            source.settings().set("csv_preview_original_scheme", info["previous_scheme"])
            source.settings().set("color_scheme", resource)
            schedule_refresh(source)
        elif attempt < 40:
            sublime.set_timeout(lambda: apply_when_indexed(attempt + 1), 100)
        else:
            apply_error(source, "Sublime has not indexed the preview color scheme. Close and reopen the preview.")

    apply_when_indexed()


def install_syntax(source, info, delimiter):
    syntax_text = make_syntax(delimiter)
    filename = "CsvTablePreview-{}-{}.sublime-syntax".format(
        binascii.hexlify(delimiter.encode("utf-8")).decode("ascii"),
        hashlib.sha256(syntax_text.encode("utf-8")).hexdigest()[:8])
    resource = "Packages/User/" + filename
    if source.settings().get("syntax") == resource:
        return
    path = os.path.join(sublime.packages_path(), "User", filename)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(syntax_text)
    info["syntax"] = resource

    def apply_when_indexed(attempt=0):
        if not source.is_valid() or PREVIEWS.get(source.id()) is not info or info.get("syntax") != resource:
            return
        if resource in sublime.find_resources(filename):
            source.settings().set("csv_preview_original_syntax", info["previous_syntax"])
            source.set_syntax_file(resource)
        elif attempt < 40:
            sublime.set_timeout(lambda: apply_when_indexed(attempt + 1), 100)
        else:
            apply_error(source, "Sublime has not indexed the CSV syntax. Close and reopen the preview.")

    apply_when_indexed()


def right_group(window, source):
    layout = window.get_layout()
    group = window.get_view_index(source)[0]
    cell = layout["cells"][group]
    candidates = []
    for index, candidate in enumerate(layout["cells"]):
        if candidate[0] >= cell[2] and candidate[1] < cell[3] and candidate[3] > cell[1]:
            candidates.append((candidate[0], index))
    if candidates:
        return min(candidates)[1]
    width = len(layout["cols"])
    created = {
        "cols": [coordinate * 0.5 for coordinate in layout["cols"]] + [1.0],
        "rows": list(layout["rows"]),
        "cells": [list(value) for value in layout["cells"]]
                 + [[width - 1, 0, width, len(layout["rows"]) - 1]],
    }
    if window.id() not in LAYOUTS:
        LAYOUTS[window.id()] = {"original": layout, "created": created,
                                "group": len(layout["cells"])}
    window.set_layout(created)
    return len(layout["cells"])


def restore_layout(window):
    entry = LAYOUTS.get(window.id())
    if not entry or not window.is_valid():
        return
    if any(info["window"].id() == window.id() for info in PREVIEWS.values()):
        return
    LAYOUTS.pop(window.id(), None)
    if window.get_layout() == entry["created"] and not window.views_in_group(entry["group"]):
        window.set_layout(entry["original"])


def draw_preview(info):
    source, preview = info["source"], info["preview"]
    if not source.is_valid() or not preview.is_valid():
        return
    model = info.get("model")
    if model is None:
        return
    available = max(16, int((preview.viewport_extent()[0] - 44) / max(1, preview.em_width())))
    content, start, end = render_preview(
        model, os.path.basename(source.file_name() or "Untitled.csv"), options(),
        info["colors"], info["background"], info["foreground"],
        info.get("column", 0), available, preview.settings().get("font_face", "Menlo")
    )
    info.update(column=start, end_column=end, width=available)
    info["phantoms"].update([sublime.Phantom(
        sublime.Region(0), content, sublime.LAYOUT_BLOCK,
        lambda href: navigate(source.id(), href)
    )])


def watch_sizes(epoch):
    if UNLOADING or not PREVIEWS or epoch != WATCH_EPOCH:
        return
    for info in list(PREVIEWS.values()):
        preview = info["preview"]
        if preview.is_valid() and info.get("model") is not None:
            available = max(16, int((preview.viewport_extent()[0] - 44) / max(1, preview.em_width())))
            if available != info.get("width"):
                draw_preview(info)
    sublime.set_timeout(lambda: watch_sizes(epoch), 500)


def navigate(source_id, href):
    info = PREVIEWS.get(source_id)
    if not info:
        return
    if href == "close":
        info["preview"].close()
    elif href == "refresh":
        schedule_refresh(info["source"])
    elif href.startswith("columns:"):
        info["column"] = int(href.split(":")[1])
        draw_preview(info)
    elif href.startswith("cell:") and info.get("model"):
        row, column = map(int, href.split(":")[1:])
        model = info["model"]
        if row >= len(model["spans"]) or column >= len(model["spans"][row]):
            return
        source = info["source"]
        if source.change_count() != info.get("change_count"):
            schedule_refresh(source)
            return
        start, end = model["spans"][row][column]
        change_count = info["change_count"]

        def select_source():
            if PREVIEWS.get(source_id) is not info or not source.is_valid():
                return
            source.run_command("csv_table_preview_select_source", {
                "start": start, "end": end, "change_count": change_count
            })

        # ST3 may not repaint an in-view selection changed inside a phantom callback.
        sublime.set_timeout(select_source, 0)


class CsvTablePreviewSelectSourceCommand(sublime_plugin.TextCommand):
    def run(self, edit, start, end, change_count):
        source = self.view
        if source.id() not in PREVIEWS or not source.window():
            return
        if source.change_count() != change_count:
            schedule_refresh(source)
            return
        source.window().focus_view(source)
        region = sublime.Region(start, end)
        source.sel().clear()
        source.sel().add(region)
        source.show(region)


def schedule_refresh(source, delay=0):
    if source.id() not in PREVIEWS:
        return
    revision = REVISIONS.get(source.id(), 0) + 1
    REVISIONS[source.id()] = revision

    def capture():
        if not source.is_valid() or source.id() not in PREVIEWS or REVISIONS.get(source.id()) != revision:
            return
        settings = options()
        maximum = bounded_int(settings, "max_source_chars", 2000000, 1000, 10000000)
        if source.size() > maximum:
            apply_error(source, "File exceeds the preview size limit; the source is unchanged.")
            return
        text = source.substr(sublime.Region(0, source.size()))
        change_count = source.change_count()
        filename = source.file_name() or "Untitled.csv"

        def parse():
            try:
                model = parse_csv(text, filename, settings)
                error = None
            except (csv.Error, ValueError) as exception:
                model, error = None, str(exception)

            def apply():
                if (not source.is_valid() or source.id() not in PREVIEWS
                        or REVISIONS.get(source.id()) != revision or source.change_count() != change_count):
                    return
                if error is not None:
                    apply_error(source, "Could not parse CSV: " + error)
                    return
                info = PREVIEWS[source.id()]
                info.update(model=model, change_count=change_count)
                install_syntax(source, info, model["delimiter"])
                draw_preview(info)

            sublime.set_timeout(apply, 0)

        sublime.set_timeout_async(parse, 0)

    sublime.set_timeout(capture, delay)


def apply_error(source, message):
    import html
    info = PREVIEWS.get(source.id())
    if info is None:
        return
    info["model"] = None
    content = '<body><p>{}</p><a href="refresh">Refresh</a></body>'.format(html.escape(message))
    info["phantoms"].update([sublime.Phantom(sublime.Region(0), content,
                                            sublime.LAYOUT_BLOCK,
                                            lambda href: navigate(source.id(), href))])


def cleanup(source_id, close_preview=True):
    global WATCH_EPOCH
    info = PREVIEWS.pop(source_id, None)
    REVISIONS.pop(source_id, None)
    if info is None:
        return
    if not PREVIEWS:
        WATCH_EPOCH += 1
    source = info["source"]
    if source.is_valid():
        if source.settings().get("color_scheme") == info.get("scheme"):
            source.settings().set("color_scheme", info["previous_scheme"])
        if source.settings().get("syntax") == info.get("syntax"):
            source.set_syntax_file(info["previous_syntax"])
        source.settings().erase("csv_preview_original_scheme")
        source.settings().erase("csv_preview_original_syntax")
    if close_preview and info["preview"].is_valid():
        info["preview"].close()
    sublime.set_timeout(lambda: restore_layout(info["window"]), 0)


class CsvTablePreviewOpenCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        global WATCH_EPOCH
        source = source_for(self.view)
        if source is None or not is_source(source) or not source.window():
            return
        info = PREVIEWS.get(source.id())
        if info and info["preview"].is_valid():
            info["window"].focus_view(info["preview"])
            return
        window = source.window()
        target = right_group(window, source)
        # In ST3, moving a new view with index -1 can leave it in the source group.
        window.focus_group(target)
        preview = window.new_file()
        preview.set_name("Preview: " + os.path.basename(source.file_name()))
        preview.set_scratch(True)
        preview.set_read_only(True)
        preview.set_syntax_file("Packages/Text/Plain text.tmLanguage")
        for key, value in {
            "csv_preview_source": source.id(), "word_wrap": False,
            "line_numbers": False, "gutter": False, "draw_white_space": "none",
            "spell_check": False, "highlight_line": False, "draw_centered": False,
            "margin": 0, "font_face": "Menlo" if sublime.platform() == "osx" else "monospace",
            "font_size": 11,
        }.items():
            preview.settings().set(key, value)
        window.set_view_index(preview, target, len(window.views_in_group(target)) - 1)
        info = {"source": source, "preview": preview, "window": window,
                "previous_scheme": source.settings().get("color_scheme"), "column": 0,
                "previous_syntax": source.settings().get("syntax"),
                "phantoms": sublime.PhantomSet(preview, "csv_table_preview")}
        PREVIEWS[source.id()] = info
        install_palette(source, info)
        schedule_refresh(source, 100)
        if len(PREVIEWS) == 1:
            WATCH_EPOCH += 1
            epoch = WATCH_EPOCH
            sublime.set_timeout(lambda: watch_sizes(epoch), 500)
        PENDING.discard(source.id())
        window.focus_view(source)

    def is_enabled(self):
        source = source_for(self.view)
        return source is not None and is_source(source)


class CsvTablePreviewToggleCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        source = source_for(self.view)
        if source and source.id() in PREVIEWS:
            cleanup(source.id())
        elif source:
            source.run_command("csv_table_preview_open")

    def is_enabled(self):
        source = source_for(self.view)
        return source is not None and is_source(source)


class CsvTablePreviewListener(sublime_plugin.EventListener):
    def on_load(self, view):
        if is_source(view):
            PENDING.add(view.id())
            sublime.set_timeout(lambda: self.open_pending(view), 200)

    def on_activated(self, view):
        if view.id() in PENDING:
            sublime.set_timeout(lambda: self.open_pending(view), 200)

    def open_pending(self, view):
        if UNLOADING or not view.is_valid() or view.id() not in PENDING or view.is_loading():
            return
        window = view.window()
        if not window or window.active_view() != view or window.get_view_index(view)[1] < 0:
            return
        PENDING.discard(view.id())
        if sublime.load_settings(SETTINGS).get("auto_preview", False):
            view.run_command("csv_table_preview_open")

    def on_modified(self, view):
        if view.id() in PREVIEWS:
            schedule_refresh(view, 250)

    def on_post_save(self, view):
        if view.id() in PREVIEWS:
            schedule_refresh(view)

    def on_close(self, view):
        PENDING.discard(view.id())
        source_id = view.settings().get("csv_preview_source", view.id())
        cleanup(source_id, close_preview=source_id == view.id())

    def on_query_context(self, view, key, operator, operand, match_all):
        if key != "csv_table_preview_available":
            return None
        source = source_for(view)
        available = source is not None and is_source(source)
        if operator == sublime.OP_EQUAL:
            return available == operand
        if operator == sublime.OP_NOT_EQUAL:
            return available != operand
        return False


def plugin_loaded():
    for window in sublime.windows():
        for view in list(window.views()):
            if view.settings().has("csv_preview_source"):
                view.close()
                continue
            previous = view.settings().get("csv_preview_original_scheme")
            if previous:
                view.settings().set("color_scheme", previous)
                view.settings().erase("csv_preview_original_scheme")
            previous_syntax = view.settings().get("csv_preview_original_syntax")
            if previous_syntax:
                view.set_syntax_file(previous_syntax)
                view.settings().erase("csv_preview_original_syntax")
            if is_source(view):
                PENDING.add(view.id())
                sublime.set_timeout(lambda view=view: CsvTablePreviewListener().open_pending(view), 200)


def plugin_unloaded():
    global UNLOADING
    UNLOADING = True
    for source_id in list(PREVIEWS):
        cleanup(source_id)
    PENDING.clear()
