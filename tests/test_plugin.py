import importlib.util
import os
import sys
import tempfile
import types
import unittest

import csv_model


class Settings(dict):
    def set(self, key, value):
        self[key] = value

    def has(self, key):
        return key in self

    def erase(self, key):
        self.pop(key, None)


class View:
    def __init__(self, group=0):
        self.group = group
        self.options = Settings(color_scheme="original.tmTheme", syntax="original.sublime-syntax")
        self.text = ""
        self.read_only = True
        self.status = {}

    def id(self):
        return 1

    def is_valid(self):
        return True

    def settings(self):
        return self.options

    def style(self):
        return {"background": "#002b36", "foreground": "#839496"}

    def set_syntax_file(self, value):
        self.options["syntax"] = value

    def set_read_only(self, value):
        self.read_only = value

    def size(self):
        return len(self.text)

    def replace(self, edit, region, content):
        assert not self.read_only
        self.text = content

    def set_status(self, key, value):
        self.status[key] = value

    def erase_status(self, key):
        self.status.pop(key, None)


class Window:
    def __init__(self, layout):
        self.layout = layout
        self.views = []

    def id(self):
        return 2

    def is_valid(self):
        return True

    def get_layout(self):
        return self.layout

    def set_layout(self, layout):
        self.layout = layout

    def get_view_index(self, view):
        return view.group, 0

    def views_in_group(self, group):
        return [view for view in self.views if view.group == group]


class PluginTests(unittest.TestCase):
    def setUp(self):
        self.callbacks = []
        self.resources = []
        self.directory = tempfile.TemporaryDirectory()
        os.mkdir(os.path.join(self.directory.name, "User"))
        sublime = types.ModuleType("sublime")
        sublime.set_timeout = lambda fn, delay=0: self.callbacks.append(fn)
        sublime.find_resources = lambda name: list(self.resources)
        sublime.packages_path = lambda: self.directory.name
        sublime.Region = lambda start, end=0: (start, end)
        commands = types.ModuleType("sublime_plugin")
        commands.TextCommand = type("TextCommand", (), {})
        commands.EventListener = type("EventListener", (), {})
        self.previous_modules = {name: sys.modules.get(name) for name in ("sublime", "sublime_plugin")}
        sys.modules["sublime"] = sublime
        sys.modules["sublime_plugin"] = commands
        package = types.ModuleType("preview_test")
        package.__path__ = []
        sys.modules["preview_test"] = package
        sys.modules["preview_test.csv_model"] = csv_model
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "plugin.py")
        spec = importlib.util.spec_from_file_location("preview_test.plugin", path)
        self.plugin = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.plugin)

    def tearDown(self):
        for name, module in self.previous_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
        sys.modules.pop("preview_test", None)
        sys.modules.pop("preview_test.csv_model", None)
        self.directory.cleanup()

    def test_waits_for_scheme_indexing(self):
        source = View()
        info = {"source": source, "previous_scheme": "original.tmTheme"}
        self.plugin.PREVIEWS[source.id()] = info
        self.plugin.install_palette(source, info)
        self.assertEqual(source.settings()["color_scheme"], "original.tmTheme")
        self.assertEqual(len(self.callbacks), 1)
        self.resources.append(info["scheme"])
        refreshed = []
        self.plugin.schedule_refresh = lambda view: refreshed.append(view)
        self.callbacks.pop(0)()
        self.assertTrue(source.settings()["color_scheme"].startswith("Packages/User/"))
        self.assertEqual(refreshed, [source])

    def test_indexing_callback_ignores_closed_preview(self):
        source = View()
        info = {"source": source, "previous_scheme": "original.tmTheme"}
        self.plugin.PREVIEWS[source.id()] = info
        self.plugin.install_palette(source, info)
        self.resources.append(info["scheme"])
        self.plugin.PREVIEWS.clear()
        self.callbacks.pop(0)()
        self.assertEqual(source.settings()["color_scheme"], "original.tmTheme")

    def test_creates_group_to_the_right(self):
        original = {"cols": [0.0, 1.0], "rows": [0.0, 1.0], "cells": [[0, 0, 1, 1]]}
        window = Window(original)
        self.assertEqual(self.plugin.right_group(window, View()), 1)
        self.assertEqual(window.get_layout()["cells"], [[0, 0, 1, 1], [1, 0, 2, 1]])
        self.plugin.restore_layout(window)
        self.assertEqual(window.get_layout(), original)

    def test_reuses_existing_right_group(self):
        layout = {"cols": [0.0, 0.5, 1.0], "rows": [0.0, 1.0],
                  "cells": [[0, 0, 1, 1], [1, 0, 2, 1]]}
        window = Window(layout)
        self.assertEqual(self.plugin.right_group(window, View()), 1)
        self.assertEqual(self.plugin.LAYOUTS, {})

    def test_keeps_other_views_when_preview_closes(self):
        original = {"cols": [0.0, 1.0], "rows": [0.0, 1.0], "cells": [[0, 0, 1, 1]]}
        window = Window(original)
        self.plugin.right_group(window, View())
        window.views.append(View(group=1))
        self.plugin.restore_layout(window)
        self.assertEqual(len(window.get_layout()["cells"]), 2)

    def test_leaves_user_layout_changes_alone(self):
        original = {"cols": [0.0, 1.0], "rows": [0.0, 1.0], "cells": [[0, 0, 1, 1]]}
        window = Window(original)
        self.plugin.right_group(window, View())
        changed = {"cols": [0.0, 0.3, 1.0], "rows": [0.0, 1.0],
                   "cells": [[0, 0, 1, 1], [1, 0, 2, 1]]}
        window.set_layout(changed)
        self.plugin.restore_layout(window)
        self.assertEqual(window.get_layout(), changed)

    def test_cleanup_restores_source_and_closes_only_preview(self):
        source = View()
        source.options.update(color_scheme="generated", syntax="generated-syntax")
        closed = []
        preview = types.SimpleNamespace(is_valid=lambda: True, close=lambda: closed.append(True))
        window = Window({"cols": [0.0, 1.0], "rows": [0.0, 1.0], "cells": [[0, 0, 1, 1]]})
        self.plugin.PREVIEWS[source.id()] = {
            "source": source, "preview": preview, "window": window,
            "scheme": "generated", "previous_scheme": "original.tmTheme",
            "syntax": "generated-syntax", "previous_syntax": "original-syntax",
        }
        self.plugin.cleanup(source.id())
        self.assertEqual(source.settings()["color_scheme"], "original.tmTheme")
        self.assertEqual(source.settings()["syntax"], "original-syntax")
        self.assertEqual(closed, [True])
        self.assertEqual(self.plugin.PREVIEWS, {})

    def navigation_info(self):
        source = View()
        selection = []
        class Selection(list):
            def add(self, item):
                self.append(item)
        selection = Selection()
        source.sel = lambda: selection
        source.change_count = lambda: 1
        source.show = lambda region: None
        source.window = lambda: types.SimpleNamespace(focus_view=lambda view: None)

        def run_command(name, args):
            self.assertEqual(name, "csv_table_preview_select_source")
            command = self.plugin.CsvTablePreviewSelectSourceCommand()
            command.view = source
            command.run(None, **args)

        source.run_command = run_command
        parsed = csv_model.parse_csv("a,b\nvalue,other", "example.csv", {})
        info = {"source": source, "model": parsed, "change_count": 1}
        self.plugin.PREVIEWS[source.id()] = info
        return source, info, selection

    def test_cell_click_selects_exact_source_field(self):
        source, info, selection = self.navigation_info()
        self.plugin.navigate(source.id(), "cell:1:1")
        self.assertEqual(selection, [])
        self.callbacks.pop(0)()
        self.assertEqual(selection, [info["model"]["spans"][1][1]])

    def test_repeated_visible_cell_clicks_each_run_selection_command(self):
        source, info, selection = self.navigation_info()
        focused = []
        selected_on_focus = []

        def focus(view):
            focused.append(view)
            selected_on_focus.append(list(selection))

        source.window = lambda: types.SimpleNamespace(focus_view=focus)
        for row, column in ((1, 0), (1, 1), (0, 1), (0, 0), (1, 0)):
            self.plugin.navigate(source.id(), "cell:{}:{}".format(row, column))
            self.callbacks.pop(0)()
            self.assertEqual(selection, [info["model"]["spans"][row][column]])
        self.assertEqual(focused, [source] * 5)
        self.assertEqual(selected_on_focus[0], [])
        self.assertEqual(selected_on_focus[1], [info["model"]["spans"][1][0]])

    def test_deferred_click_does_not_select_text_after_source_changes(self):
        source, info, selection = self.navigation_info()
        refreshed = []
        self.plugin.schedule_refresh = lambda view: refreshed.append(view)
        self.plugin.navigate(source.id(), "cell:1:1")
        source.change_count = lambda: 2
        self.callbacks.pop(0)()
        self.assertEqual(selection, [])
        self.assertEqual(refreshed, [source])

    def test_deferred_click_is_ignored_after_preview_closes(self):
        source, info, selection = self.navigation_info()
        self.plugin.navigate(source.id(), "cell:1:1")
        self.plugin.PREVIEWS.clear()
        self.callbacks.pop(0)()
        self.assertEqual(selection, [])

    def test_stale_click_refreshes_instead_of_selecting_wrong_text(self):
        source, info, selection = self.navigation_info()
        info["change_count"] = 0
        refreshed = []
        self.plugin.schedule_refresh = lambda view: refreshed.append(view)
        self.plugin.navigate(source.id(), "cell:1:1")
        self.assertEqual(refreshed, [source])
        self.assertEqual(selection, [])

    def test_column_navigation_updates_preview(self):
        source, info, selection = self.navigation_info()
        rendered = []
        self.plugin.draw_preview = lambda info: rendered.append(info["column"])
        self.plugin.navigate(source.id(), "columns:1")
        self.assertEqual(rendered, [1])

    def copy_info(self):
        source = View()
        source.change_count = lambda: 1
        preview = View()
        source.window = lambda: types.SimpleNamespace(focus_view=lambda view: None)
        preview.window = source.window
        preview.options["csv_preview_source"] = source.id()
        updated = []

        def run_command(name, args):
            self.assertEqual(name, "csv_table_preview_replace_content")
            command = self.plugin.CsvTablePreviewReplaceContentCommand()
            command.view = preview
            command.run(None, **args)

        preview.run_command = run_command
        info = {"source": source, "preview": preview, "copy_mode": True,
                "model": csv_model.parse_csv("a,b\n1,2", "example.csv", {}),
                "change_count": 1, "previous_scheme": "original.tmTheme",
                "scheme": "Packages/User/generated.sublime-color-scheme",
                "phantoms": types.SimpleNamespace(update=lambda values: updated.append(values))}
        self.plugin.PREVIEWS[source.id()] = info
        self.plugin.install_syntax = lambda *args, **kwargs: None
        return source, preview, info, updated

    def test_copy_mode_populates_a_read_only_native_buffer(self):
        source, preview, info, phantoms = self.copy_info()
        self.resources.append(info["scheme"])
        self.plugin.draw_copy_preview(info)
        self.assertEqual(preview.text, "a\tb\n1\t2\n")
        self.assertTrue(preview.read_only)
        self.assertEqual(preview.options["color_scheme"], info["scheme"])
        self.assertEqual(phantoms, [[]])

    def test_copy_mode_does_not_select_unindexed_scheme(self):
        source, preview, info, phantoms = self.copy_info()
        self.plugin.draw_copy_preview(info)
        self.assertEqual(preview.options["color_scheme"], "original.tmTheme")

    def test_source_changes_do_not_replace_copy_selection_snapshot(self):
        source, preview, info, phantoms = self.copy_info()
        self.plugin.draw_copy_preview(info)
        info["model"] = csv_model.parse_csv("a,b\n3,4", "example.csv", {})
        info["change_count"] = 2
        source.change_count = lambda: 2
        self.plugin.draw_copy_preview(info)
        self.assertEqual(preview.text, "a\tb\n1\t2\n")
        self.assertIn("Source changed", preview.status["csv_preview_copy"])

    def test_refresh_updates_copy_snapshot(self):
        source, preview, info, phantoms = self.copy_info()
        self.plugin.draw_copy_preview(info)
        info["model"] = csv_model.parse_csv("a,b\n3,4", "example.csv", {})
        info["change_count"] = 2
        source.change_count = lambda: 2
        info.pop("copy_change_count")
        self.plugin.draw_copy_preview(info)
        self.assertEqual(preview.text, "a\tb\n3\t4\n")
        self.assertNotIn("Source changed", preview.status["csv_preview_copy"])

    def test_leaving_copy_mode_clears_native_buffer_and_restores_rendering(self):
        source, preview, info, phantoms = self.copy_info()
        self.plugin.draw_copy_preview(info)
        rendered = []
        self.plugin.draw_preview = lambda value: rendered.append(value)
        self.plugin.set_copy_mode(info, False)
        self.assertEqual(preview.text, "")
        self.assertTrue(preview.read_only)
        self.assertEqual(preview.options["color_scheme"], "original.tmTheme")
        self.assertEqual(preview.status, {})
        self.assertEqual(rendered, [info])

    def test_parse_errors_leave_existing_copy_snapshot_available(self):
        source, preview, info, phantoms = self.copy_info()
        self.plugin.draw_copy_preview(info)
        self.plugin.apply_error(source, "Invalid CSV")
        self.assertEqual(preview.text, "a\tb\n1\t2\n")
        self.assertIn("Invalid CSV", preview.status["csv_preview_copy"])

    def test_copy_mode_reports_preview_limits(self):
        source, preview, info, phantoms = self.copy_info()
        info["model"]["truncated_rows"] = True
        self.plugin.draw_copy_preview(info)
        self.assertIn("Preview limits apply", preview.status["csv_preview_copy"])


if __name__ == "__main__":
    unittest.main()
