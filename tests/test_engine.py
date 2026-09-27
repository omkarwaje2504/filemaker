"""Engine tests: preview, production, project files, path builder.

Run:  venv\\Scripts\\python.exe -m unittest discover -s tests -v
Fixtures (images, PDFs, data) are generated into a temp dir per test.
"""
import json
import os
import shutil
import tempfile
import unittest

import pandas as pd
import pymupdf as fitz
from PIL import Image

from filemaker.models.project import MODE_CALENDAR, EventIcon, PathBuilderSettings, Project
from filemaker.services import data_service, project_store
from filemaker.services.path_builder import build_paths
from filemaker.services.preview import PreviewRequest, PreviewUnavailable, render_preview
from filemaker.services.production import ProductionRun, check_readiness, is_ready

TEMPLATE_W, TEMPLATE_H = 400, 300


def make_image(path, size=(TEMPLATE_W, TEMPLATE_H), color=(200, 220, 255, 255)):
    Image.new("RGBA", size, color).save(path)
    return path


def make_pdf(path):
    doc = fitz.open()
    doc.new_page(width=TEMPLATE_W, height=TEMPLATE_H)
    doc.save(path)
    doc.close()
    return path


def make_design():
    return {
        "template": {
            "width": TEMPLATE_W,
            "height": TEMPLATE_H,
            "overlayImages": [
                {"src": "{{Photo}}", "x": 10, "y": 10, "width": 50, "height": 50, "calendar_image": False}
            ],
            "textBlocks": [{"text": "{{Name}}", "x": 100, "y": 100, "fontSize": 20, "fill": "#112233"}],
        }
    }


class EngineTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="filemaker_test_")
        self.photo = make_image(os.path.join(self.tmp, "photo.png"), (60, 60), (255, 0, 0, 255))
        self.base_png = make_image(os.path.join(self.tmp, "base.png"))
        self.out = os.path.join(self.tmp, "out")
        self.df = pd.DataFrame({
            "Name": ["Alice", "Bob"],
            "Photo": [self.photo, self.photo],
            "Code": ["A1", "B2"],
        })

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def normal_project(self, base_file=None):
        p = Project(design=make_design(), base_file=base_file or self.base_png, output_folder=self.out)
        p.mappings = data_service.build_mappings(p.design)
        data_service.auto_map(p.mappings, list(self.df.columns))
        p.filename_column = "Code"
        p.workers = 2
        return p

    def run_production(self, project, df=None):
        results = {}
        run = ProductionRun(
            project, df if df is not None else self.df,
            dispatch=lambda fn, *a: fn(*a),
            on_progress=lambda s: None,
            on_log=lambda line, level: results.setdefault("log", []).append(line),
            on_finished=lambda s: results.__setitem__("stats", s),
        )
        run.start()
        run._thread.join(timeout=60)
        return results


class MappingTests(EngineTestCase):
    def test_auto_map_matches_keys_to_columns(self):
        p = self.normal_project()
        self.assertEqual([m.column for m in p.mappings], ["Photo", "Name"])

    def test_auto_map_is_case_insensitive(self):
        mappings = data_service.build_mappings(make_design())
        data_service.auto_map(mappings, ["photo", "NAME"])
        self.assertEqual([m.column for m in mappings], ["photo", "NAME"])

    def test_rebuild_keeps_previous_choices(self):
        p = self.normal_project()
        p.mappings[1].column = "Code"
        rebuilt = data_service.build_mappings(p.design, p.mappings)
        self.assertEqual(rebuilt[1].column, "Code")


class PreviewTests(EngineTestCase):
    def test_normal_png_preview_matches_template_size(self):
        img = render_preview(PreviewRequest.from_project(self.normal_project(), self.df, 0, 1))
        self.assertEqual(img.size, (TEMPLATE_W, TEMPLATE_H))
        self.assertEqual(img.getpixel((20, 20))[:3], (255, 0, 0))  # overlay drawn

    def test_normal_pdf_preview_renders(self):
        p = self.normal_project(make_pdf(os.path.join(self.tmp, "base.pdf")))
        img = render_preview(PreviewRequest.from_project(p, self.df, 1, 1))
        self.assertGreater(img.width, 0)

    def test_preview_without_design_explains_why(self):
        p = self.normal_project()
        p.design = None
        with self.assertRaises(PreviewUnavailable):
            render_preview(PreviewRequest.from_project(p, self.df, 0, 1))

    def test_calendar_preview_uses_that_months_artwork(self):
        p = self.normal_project()
        p.mode = MODE_CALENDAR
        colors = {1: (255, 255, 255, 255), 3: (0, 255, 0, 255)}
        p.calendar.base_files = [
            make_image(os.path.join(self.tmp, f"m{m}.png"), color=colors.get(m, (9, 9, 9, 255)))
            for m in range(1, 4)
        ]
        img = render_preview(PreviewRequest.from_project(p, self.df, 0, 3))
        self.assertEqual(img.getpixel((TEMPLATE_W - 5, TEMPLATE_H - 5))[:3], (0, 255, 0))


class ProductionTests(EngineTestCase):
    def test_normal_png_production_names_files_by_column(self):
        res = self.run_production(self.normal_project())
        self.assertEqual(sorted(os.listdir(self.out)), ["A1.png", "B2.png"])
        self.assertEqual(res["stats"].outputs_done, 2)
        self.assertEqual(res["stats"].errors, 0)

    def test_jpg_override(self):
        p = self.normal_project()
        p.output_format = "jpg"
        self.run_production(p)
        self.assertEqual(sorted(os.listdir(self.out)), ["A1.jpg", "B2.jpg"])

    def test_pdf_base_produces_pdf(self):
        p = self.normal_project(make_pdf(os.path.join(self.tmp, "base.pdf")))
        self.assertEqual(p.effective_output_format(), "pdf")
        self.run_production(p)
        self.assertEqual(sorted(os.listdir(self.out)), ["A1.pdf", "B2.pdf"])

    def test_missing_image_row_is_skipped_and_logged(self):
        df = self.df.copy()
        df.loc[1, "Photo"] = os.path.join(self.tmp, "nope.png")
        res = self.run_production(self.normal_project(), df)
        self.assertEqual(res["stats"].skipped, 1)
        self.assertTrue(os.path.exists(os.path.join(self.out, "production_log.txt")))

    def test_calendar_produces_twelve_outputs_per_row(self):
        p = self.normal_project()
        p.mode = MODE_CALENDAR
        p.calendar.base_files = [make_image(os.path.join(self.tmp, "jan.png"))]
        res = self.run_production(p)
        files = os.listdir(self.out)
        self.assertEqual(len(files), 24)
        self.assertIn("A1_01_January.png", files)
        self.assertIn("B2_12_December.png", files)
        self.assertEqual(res["stats"].outputs_done, 24)

    def test_calendar_event_texts_and_icons_render(self):
        p = self.normal_project()
        p.mode = MODE_CALENDAR
        p.calendar.base_files = [make_image(os.path.join(self.tmp, "jan.png"))]
        p.calendar.event_text_column = "Events"
        p.calendar.icons = [EventIcon(path=self.photo, excel_column="Birthday")]
        df = self.df.copy()
        df["Events"] = json.dumps([{"date": "24/01/1990", "value": "Birthday"}])
        df["Birthday"] = "1990-01-24"
        res = self.run_production(p, df)
        self.assertEqual(res["stats"].errors, 0)


class ProjectFileTests(EngineTestCase):
    def test_save_and_open_round_trip_keeps_mappings(self):
        p = self.normal_project()
        p.mappings[1].font_path = "C:/fonts/x.ttf"
        p.calendar.icons = [EventIcon(path="i.png", excel_column="Birthday", scale=0.5)]
        path = os.path.join(self.tmp, "p.tdtpl.json")
        project_store.save_project(path, p)
        loaded = project_store.load_project(path)
        self.assertEqual([m.column for m in loaded.mappings], ["Photo", "Name"])
        self.assertEqual(loaded.mappings[1].font_path, "C:/fonts/x.ttf")
        self.assertEqual(loaded.calendar.icons[0].scale, 0.5)
        self.assertEqual(loaded.slot_vars(), p.slot_vars())

    def test_opens_v1_template_from_old_app(self):
        v1 = {
            "version": "1.0",
            "product_type": "calendar",
            "design": make_design(),
            "product_config": {
                "calendar_start_x": 12,
                "calendar_base_files": ["a.png"],
                "calendar_event_text_style": {"x": 5, "color": "#123456"},
            },
            "slot_vars": {"OVL_0": {"value": None, "path": None}, "TXT_0_FONT": {"value": None, "path": "f.ttf"}},
        }
        path = os.path.join(self.tmp, "old.tdtpl.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(v1, f)
        p = project_store.load_project(path)
        self.assertTrue(p.is_calendar)
        self.assertEqual(p.calendar.start_x, 12)
        self.assertEqual(p.calendar.event_text_style.text_color, "#123456")
        self.assertEqual(p.mappings[1].font_path, "f.ttf")


class PathBuilderAndReadinessTests(EngineTestCase):
    def test_build_paths(self):
        s = PathBuilderSettings(base_folder="C:/img", folder1_column="Code", file_column="Name", suffix="_x")
        paths = build_paths(self.df, s)
        self.assertEqual(paths[0], os.path.normpath("C:/img/A1/Alice_x.png"))

    def test_readiness_blocks_without_output_folder(self):
        p = self.normal_project()
        self.assertTrue(is_ready(check_readiness(p, self.df)))
        p.output_folder = ""
        self.assertFalse(is_ready(check_readiness(p, self.df)))


if __name__ == "__main__":
    unittest.main()
