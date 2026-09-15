import json
import tempfile
import unittest
from pathlib import Path

import pelican_gallery as gallery
import pelican_eval


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "gallery.html"
SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 80">
<circle cx="25" cy="25" r="12"/><path d="M10 60 L50 60 L30 30 Z"/>
</svg>"""


class GalleryTest(unittest.TestCase):
    def write_case(self, directory, manifest):
        root = Path(directory)
        for sample in manifest["samples"]:
            (root / sample.get("svg", f"{sample['key']}.svg")).write_text(SVG, encoding="utf-8")
        manifest_path = root / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return manifest_path

    def test_renders_dynamic_self_contained_gallery(self):
        with tempfile.TemporaryDirectory() as directory:
            samples = [
                {
                    "key": f"model-a-{attempt}",
                    "model": "Model A",
                    "effort": "low",
                    "channel": "direct",
                    "attempt": attempt,
                    "tokens": 100,
                    "tokens_exact": attempt != 1,
                    "plan_multiplier": 2.5,
                }
                for attempt in range(1, 5)
            ]
            samples.append({
                "key": "model-b-1",
                "model": "Model B",
                "effort": "xhigh",
                "channel": "direct",
                "tokens": 80,
                "weighted_tokens": 90,
            })
            manifest = {
                "title": "A < B",
                "prompt": "same prompt",
                "token_basis": {
                    "label": "Sol-equivalent",
                    "note": "Use <carefully>",
                    "source_url": "https://example.com/rates?a=1&b=2",
                    "source_label": "rate table",
                },
                "notes": ["Never render <script>alert(1)</script>"],
                "samples": samples,
            }
            manifest_path = self.write_case(directory, manifest)
            output = Path(directory) / "board.html"

            prepared, lanes = gallery.render(manifest_path, output, TEMPLATE, "zh")
            page = output.read_text(encoding="utf-8")

            self.assertEqual(len(prepared), 5)
            self.assertEqual(len(lanes), 2)
            self.assertIn("<strong>2</strong> 个模型", page)
            self.assertIn("--sample-count:4", page)
            self.assertIn("data:image/svg+xml;base64,", page)
            self.assertIn("≈250", page)
            self.assertIn("≈1.1k", page)
            self.assertIn("A &lt; B", page)
            self.assertIn("Use &lt;carefully&gt;", page)
            self.assertIn("https://example.com/rates?a=1&amp;b=2", page)
            self.assertIn("Never render &lt;script&gt;alert(1)&lt;/script&gt;", page)
            self.assertNotRegex(page, r"{{[A-Z_]+}}")

    def test_rejects_cheat_svg(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "bad.svg").write_text(
                '<svg xmlns="http://www.w3.org/2000/svg"><text>pelican</text></svg>',
                encoding="utf-8",
            )
            manifest_path = root / "manifest.json"
            manifest_path.write_text(
                json.dumps({"samples": [{"key": "bad", "svg": "bad.svg"}]}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(gallery.GalleryError, "disallowed SVG shortcut"):
                gallery.render(manifest_path, root / "board.html", TEMPLATE, "en")

    def test_rejects_duplicate_keys_and_bad_exactness(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "same.svg").write_text(SVG, encoding="utf-8")
            duplicate = root / "duplicate.json"
            duplicate.write_text(json.dumps({"samples": [
                {"key": "same", "svg": "same.svg"},
                {"key": "same", "svg": "same.svg"},
            ]}), encoding="utf-8")
            with self.assertRaisesRegex(gallery.GalleryError, "duplicate sample key"):
                gallery.render(duplicate, root / "board.html", TEMPLATE, "zh")

            invalid = root / "invalid.json"
            invalid.write_text(json.dumps({"samples": [
                {"key": "same", "svg": "same.svg", "tokens_exact": "yes"},
            ]}), encoding="utf-8")
            with self.assertRaisesRegex(gallery.GalleryError, "tokens_exact"):
                gallery.render(invalid, root / "board.html", TEMPLATE, "zh")

    def test_umbrella_cli_has_stable_commands(self):
        self.assertEqual(set(pelican_eval.COMMANDS), {"render", "proxy-check"})
        with self.assertRaisesRegex(SystemExit, "unknown command"):
            pelican_eval.main(["unknown"])


if __name__ == "__main__":
    unittest.main()
