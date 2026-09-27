"""Build an image-path column from other data columns.

base_folder / <folder 1 value> / <folder 2 value> / <prefix><file value><suffix><ext>
"""
import os

from ..models.project import PathBuilderSettings
from ..utils.text import safe_str


def build_paths(df, s: PathBuilderSettings) -> list:
    if df is None:
        raise ValueError("Load a data file first.")
    if not s.base_folder:
        raise ValueError("Choose the base folder the images live in.")
    if not s.file_column:
        raise ValueError("Choose the column that holds the file name / code.")

    ext = (s.extension or ".png").strip()
    paths = []
    for _, row in df.iterrows():
        parts = [s.base_folder]
        for col in (s.folder1_column, s.folder2_column):
            if col:
                value = safe_str(row[col])
                if value:
                    parts.append(value)
        filename = f"{s.prefix}{safe_str(row[s.file_column])}{s.suffix}"
        if not filename.lower().endswith(ext.lower()):
            filename += ext
        parts.append(filename)
        paths.append(os.path.normpath(os.path.join(*parts)))
    return paths


def example_path(df, s: PathBuilderSettings) -> str:
    """The path the first row would get - shown live while editing."""
    if df is None or df.empty or not s.base_folder or not s.file_column:
        return ""
    try:
        return build_paths(df.head(1), s)[0]
    except Exception:
        return ""
