"""Window layout regression checks without changing Windows display settings."""

import os
import subprocess
import sys
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from collector import App


class LayoutTests(unittest.TestCase):
    def settle(self, app, milliseconds=80):
        # Windows applies window-manager geometry asynchronously.
        app.root.after(milliseconds, app.root.quit)
        app.root.mainloop()
        app.root.update()

    def test_layout_at_window_sizes_and_dpi_scales(self):
        selected_scale = os.environ.get('FANSCOPE_TEST_UI_SCALE')
        if selected_scale is None:
            # Each run starts with a fresh Tcl/CustomTkinter DPI tracker.
            for scale in (1, 1.25, 1.5, 2):
                with self.subTest(scale=scale):
                    environment = dict(os.environ, FANSCOPE_TEST_UI_SCALE=str(scale))
                    result = subprocess.run([sys.executable, '-m', 'unittest', 'test_ui', '-v'],
                                            env=environment, capture_output=True, text=True, timeout=120)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return
        original_tk = tk.Tk
        scale = float(selected_scale)
        with self.subTest(scale=scale), tempfile.TemporaryDirectory() as directory:
            class ScaledTk(original_tk):
                def __init__(self):
                    super().__init__()
                    self.tk.call('tk', 'scaling', scale * 96 / 72)

            with patch('collector.tk.Tk', ScaledTk):
                app = App(Path(directory))
            try:
                # Hosted Windows runners use small virtual desktops. Allow the
                # off-screen test window to exercise large logical layouts.
                app.root.maxsize(app.px(3000), app.px(2000))
                self.settle(app)
                for width, height in ((1160, 800), (980, 720), (800, 600), (740, 460),
                                      (520, 460), (1160, 800)):
                    with self.subTest(window=(width, height)):
                        app.root.geometry(f'{app.px(width)}x{app.px(height)}')
                        self.settle(app)
                        actual_width = app.page.winfo_width()
                        self.assertEqual(app.layout_columns, 2 if actual_width < app.px(840) else 4)
                        self.assertEqual(app.controls.grid_info()['row'],
                                         1 if actual_width < app.px(720) else 0)
                        last_card = app.metric_cards[app.layout_columns - 1]
                        self.assertGreaterEqual(last_card.winfo_x() + last_card.winfo_width(),
                                                app.metrics.winfo_width() - 1)
                        controls = [*app.action_buttons, app.import_button, app.status_label,
                                    app.scope_control, app.view_export_button, app.speed_control]
                        for widget in controls:
                            self.assertTrue(widget.winfo_ismapped(), str(widget))
                            self.assertGreaterEqual(widget.winfo_width(), widget.winfo_reqwidth())
                            self.assertLessEqual(widget.winfo_x() + widget.winfo_width(),
                                                 widget.master.winfo_width())
                        app.page.yview_moveto(1)
                        app.root.update()
                        self.assertGreaterEqual(app.page.canvasy(0) + app.page.winfo_height(),
                                                app.content.winfo_height() - 2)
                        app.page.yview_moveto(0)
                # Long counts must fit when four cards share a narrow window.
                app.root.geometry(f'{app.px(980)}x{app.px(720)}')
                app.events.put(('count', dict.fromkeys(app.count_values, 123456789)))
                self.settle(app, 200)
                for number in app.metric_numbers:
                    self.assertLessEqual(number.winfo_reqwidth(),
                                         number.master.winfo_width() - app.px(32))
                # Tab focus reveals controls below the current page viewport.
                app.root.geometry(f'{app.px(740)}x{app.px(460)}')
                self.settle(app)
                app.page.yview_moveto(0)
                app.speed_control.focus_force()
                app.root.update()
                self.assertGreater(app.page.canvasy(0), 0)
            finally:
                app.close()
                app.root.mainloop()


if __name__ == '__main__':
    unittest.main()
