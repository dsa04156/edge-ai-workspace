import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "docs_editor_server.py"


def load_module():
    spec = importlib.util.spec_from_file_location("docs_editor_server", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class DocsEditorServerTest(unittest.TestCase):
    def test_resolve_doc_path_accepts_markdown_under_docs(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as td:
            docs = Path(td) / "docs"
            target = docs / "ops" / "runbook.md"
            target.parent.mkdir(parents=True)
            target.write_text("# runbook\n", encoding="utf-8")

            resolved = module.resolve_doc_path(docs, "ops/runbook.md")

            self.assertEqual(resolved, target.resolve())

    def test_resolve_doc_path_rejects_path_traversal(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as td:
            docs = Path(td) / "docs"
            docs.mkdir()
            outside = Path(td) / "secret.md"
            outside.write_text("secret", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "docs"):
                module.resolve_doc_path(docs, "../secret.md")

    def test_save_markdown_only_writes_existing_md_and_returns_text(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as td:
            docs = Path(td) / "docs"
            target = docs / "project-context.md"
            target.parent.mkdir(parents=True)
            target.write_text("# old\n", encoding="utf-8")

            saved = module.save_markdown(docs, "project-context.md", "# new\n")

            self.assertEqual(saved, "# new\n")
            self.assertEqual(target.read_text(encoding="utf-8"), "# new\n")


if __name__ == "__main__":
    unittest.main()
