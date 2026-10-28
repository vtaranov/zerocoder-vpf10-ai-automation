import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import httpx
from openai import AuthenticationError, APITimeoutError, RateLimitError
from pydantic import ValidationError
from pypdf import PdfReader

import main
from utils.ai_processor import process_dialog_with_ai
from utils.errors import AppError
from utils.pdf_generator import render_html, write_pdf
from utils.schema import DialogReport


def sample(**changes):
    data = dict(client_name=None, topic="Обсуждение автоматизации", main_request="PDF из текста",
                mood="unknown", deadline=None, budget=None, requirements=["Кириллица"],
                next_steps=[], open_questions=["Уточнить сроки"])
    data.update(changes)
    return DialogReport(**data)


class InputTests(unittest.TestCase):
    def test_empty_missing_encoding_and_oversize(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "input.txt"
            for content in (b" \n", b"\xff", b"x" * (main.MAX_CHARS + 1)):
                path.write_bytes(content)
                with self.assertRaises(AppError):
                    main.read_dialog(str(path))
            with self.assertRaises(AppError):
                main.read_dialog(str(path) + "missing")

    def test_bom_and_stdin(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "input.txt"
            path.write_text("Диалог", encoding="utf-8-sig")
            self.assertEqual(main.read_dialog(str(path)), "Диалог")
        with patch("sys.stdin", io.StringIO("Привет\n")):
            self.assertEqual(main.read_dialog("-"), "Привет")


class AiTests(unittest.TestCase):
    def setUp(self):
        self.patcher = patch("utils.ai_processor.OpenAI")
        self.factory = self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.client = self.factory.return_value.__enter__.return_value
        self.response = SimpleNamespace(status="completed", output=[], output_parsed=sample(),
                                        usage=None, id="resp_test", model="gpt-4o-mini")
        self.client.responses.parse.return_value = self.response

    def test_direct_endpoint_schema_and_store_false(self):
        report, metadata = process_dialog_with_ai("Диалог", "secret-test", "gpt-4o-mini")
        self.assertEqual(report.topic, "Обсуждение автоматизации")
        self.assertEqual(metadata["response_id"], "resp_test")
        self.assertEqual(self.factory.call_args.kwargs["base_url"], "https://api.openai.com/v1")
        args = self.client.responses.parse.call_args.kwargs
        self.assertIs(args["store"], False)
        self.assertIs(args["text_format"], DialogReport)

    def test_refusal_incomplete_and_missing_parsed(self):
        for status, output, parsed in (
                ("incomplete", [], sample()),
                ("completed", [SimpleNamespace(content=[SimpleNamespace(type="refusal")])], None),
                ("completed", [], None)):
            self.response.status, self.response.output, self.response.output_parsed = status, output, parsed
            with self.assertRaises(AppError):
                process_dialog_with_ai("Диалог", "secret-test", "gpt-4o-mini")

    def test_api_errors_do_not_expose_response_or_secret(self):
        request = httpx.Request("POST", "https://api.openai.com/v1/responses")
        for error in (
                AuthenticationError("secret-test", response=httpx.Response(401, request=request), body=None),
                RateLimitError("secret-test", response=httpx.Response(429, request=request), body=None),
                APITimeoutError(request=request), ValueError("secret-test")):
            self.client.responses.parse.side_effect = error
            with self.assertRaises(AppError) as caught:
                process_dialog_with_ai("Диалог", "secret-test", "gpt-4o-mini")
            self.assertNotIn("secret-test", str(caught.exception))

    def test_schema_rejects_missing_extra_fields_and_wrong_types(self):
        for data in ({}, {**sample().model_dump(), "extra": "oops"},
                     {**sample().model_dump(), "requirements": "not a list"}):
            with self.assertRaises(ValidationError):
                DialogReport.model_validate(data)


class RenderingTests(unittest.TestCase):
    def test_template_escapes_untrusted_text(self):
        html = render_html(sample(topic='<script>alert("x")</script>',
                                  requirements=['<img src="file:///etc/passwd">']), "2026-10-28", "test")
        self.assertNotIn("<script>", html)
        self.assertNotIn("<img ", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("Не указано", html)

    def test_real_weasyprint_pdf_and_multipage(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "test.pdf"
            html = render_html(sample(requirements=[f"Требование {i}: проверка кириллицы и переноса текста." for i in range(80)]),
                               "2026-10-28", "test")
            write_pdf(html, target)
            reader = PdfReader(target)
            self.assertGreaterEqual(len(reader.pages), 2)
            text = "\n".join(page.extract_text() for page in reader.pages)
            self.assertIn("Требование 79", text)
            self.assertIn("Обсуждение автоматизации", text)
            for page in reader.pages:
                self.assertIn("Страница", page.extract_text())


class PipelineTests(unittest.TestCase):
    def test_missing_key_no_api_request(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict("os.environ", {}, clear=True), \
                patch("main.load_dotenv"), patch("main.process_dialog_with_ai") as ai:
            path = Path(folder) / "input.txt"
            path.write_text("Диалог", encoding="utf-8")
            with self.assertRaisesRegex(AppError, "OPENAI_API_KEY"):
                main.run(str(path), Path(folder) / "reports")
            ai.assert_not_called()

    def test_complete_pipeline_keeps_json_html_pdf_and_unique_names(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict("os.environ", {"OPENAI_API_KEY": "secret-test"}), \
                patch("main.load_dotenv"), patch("main.process_dialog_with_ai", return_value=(sample(), {})):
            path = Path(folder) / "input.txt"
            path.write_text("Диалог", encoding="utf-8")
            pdfs = [main.run(str(path), Path(folder) / "reports") for _ in range(2)]
            self.assertNotEqual(*pdfs)
            for pdf in pdfs:
                self.assertEqual(len(PdfReader(pdf).pages), 1)
                data = json.loads(pdf.with_suffix(".json").read_text(encoding="utf-8"))
                self.assertEqual(data["report"]["mood"], "unknown")
                self.assertNotIn("secret-test", pdf.with_suffix(".json").read_text())
                self.assertTrue(pdf.with_suffix(".html").exists())

    def test_failed_pdf_keeps_json_html_but_no_partial_pdf(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict("os.environ", {"OPENAI_API_KEY": "secret-test"}), \
                patch("main.load_dotenv"), patch("main.process_dialog_with_ai", return_value=(sample(), {})), \
                patch("main.write_pdf", side_effect=AppError("Test rendering failure")):
            path = Path(folder) / "input.txt"
            path.write_text("Диалог", encoding="utf-8")
            out = Path(folder) / "reports"
            with self.assertRaises(AppError):
                main.run(str(path), out)
            self.assertEqual(len(list(out.glob("*.json"))), 1)
            self.assertEqual(len(list(out.glob("*.html"))), 1)
            self.assertEqual(list(out.glob("*.pdf*")), [])


if __name__ == "__main__":
    unittest.main()
