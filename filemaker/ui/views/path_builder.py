"""Tool - Path builder: generate an image-path column from other columns."""
import os
from tkinter import messagebox, ttk

from ...services.path_builder import build_paths, example_path
from ..theme import Sym, px
from ..widgets import ChoiceField, EmptyState, Form, Notice, PathField, TextField
from .base import BaseView

EXTENSIONS = [".png", ".jpg", ".jpeg", ".pdf"]


class PathBuilderView(BaseView):
    key = "paths"
    title = "Path builder"
    subtitle = ("Build a column of image file paths from other columns - "
                "base folder / folder 1 / folder 2 / prefix + file + suffix + extension.")

    def __init__(self, parent, state, app):
        super().__init__(parent, state, app)
        self.build()
        for topic in ("project", "data"):
            state.subscribe(topic, lambda **_: self.rebuild())

    def status(self):
        return "todo"

    def build(self):
        if self.state.df is None:
            card = self.card()
            EmptyState(card.body, "Load data first",
                       "The path builder combines columns from your spreadsheet.",
                       "Go to Data", lambda: self.app.show_view("data")).pack(fill="x")
            return

        s = self.state.project.path_builder
        cols = self.state.columns
        card = self.card("Parts")
        form = Form(card.body, columns=1, label_width=140)
        form.add("Base folder", PathField(form, s.base_folder, self._set("base_folder"), mode="folder",
                                          placeholder="Folder the images live in",
                                          title="Choose base folder"))
        form.add("Folder level 1", ChoiceField(form, cols, s.folder1_column, self._set("folder1_column")),
                 hint="Optional sub-folder taken from this column.")
        form.add("Folder level 2", ChoiceField(form, cols, s.folder2_column, self._set("folder2_column")),
                 hint="Optional second sub-folder.")
        form.add("File / code column", ChoiceField(form, cols, s.file_column, self._set("file_column")))
        form.add("Prefix", TextField(form, s.prefix, self._set("prefix")))
        form.add("Suffix", TextField(form, s.suffix, self._set("suffix")))
        form.add("Extension", ChoiceField(form, EXTENSIONS, s.extension, self._set("extension"),
                                          allow_none=False, width=10))
        form.add("New column name", TextField(form, s.output_column, self._set("output_column")),
                 hint="An existing column with this name is replaced.")
        form.pack(fill="x")

        result = self.card("Result")
        self._example = ttk.Frame(result.body)
        self._example.pack(fill="x", pady=(0, px(12)))
        ttk.Button(result.body, text="Generate column", style="Primary.TButton",
                   command=self.generate).pack(anchor="w")
        ttk.Label(result.body, style="Subtle.TLabel", wraplength=px(620), justify="left",
                  text="The new column lives in memory for this session (your spreadsheet file is not "
                       "changed). These settings are saved with the project, so after reopening just "
                       "press Generate again.").pack(anchor="w", pady=(px(10), 0))
        self._refresh_example()

    def _set(self, attr):
        s = self.state.project.path_builder

        def set_(value):
            setattr(s, attr, value)
            self.state.changed("paths")
            self._refresh_example()

        return set_

    def _refresh_example(self):
        frame = getattr(self, "_example", None)
        if frame is None or not frame.winfo_exists():
            return
        for child in frame.winfo_children():
            child.destroy()
        path = example_path(self.state.df, self.state.project.path_builder)
        if not path:
            Notice(frame, "Choose a base folder and a file column to see the first row's path.").pack(fill="x")
        elif os.path.exists(path):
            Notice(frame, f"Row 1 {Sym.arrow} {path}\nFile found.", "success").pack(fill="x")
        else:
            Notice(frame, f"Row 1 {Sym.arrow} {path}\nNo file at this path yet.", "warning").pack(fill="x")

    def generate(self):
        s = self.state.project.path_builder
        name = s.output_column.strip() or "IMAGE_PATH"
        try:
            paths = build_paths(self.state.df, s)
        except ValueError as e:
            messagebox.showwarning("Path builder", str(e), parent=self)
            return
        df = self.state.df.copy()
        df[name] = paths
        found = sum(1 for p in paths if os.path.exists(p))
        self.state.replace_df(df, f"Column '{name}' built: {len(paths)} paths, {found} files found")
