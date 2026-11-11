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
        parsed = csv_model.parse_csv("a,b\nvalue,other", "example.csv", {})
        info = {"source": source, "model": parsed, "change_count": 1}
        self.plugin.PREVIEWS[source.id()] = info
        return source, info, selection

    def test_cell_click_selects_exact_source_field(self):
        source, info, selection = self.navigation_info()
        self.plugin.navigate(source.id(), "cell:1:1")
        self.assertEqual(selection, [info["model"]["spans"][1][1]])

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


if __name__ == "__main__":
    unittest.main()
