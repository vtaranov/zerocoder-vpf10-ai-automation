"""CLI: UTF-8 dialog -> OpenAI JSON -> Jinja2 HTML -> WeasyPrint PDF."""
import argparse
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from utils.ai_processor import process_dialog_with_ai
from utils.errors import AppError
from utils.pdf_generator import render_html, write_pdf

ROOT = Path(__file__).resolve().parent
MAX_CHARS = 40_000
TIMEZONE = ZoneInfo("Europe/Moscow")
LOG = logging.getLogger("vpf10")


def setup_logging() -> None:
    (ROOT / "logs").mkdir(exist_ok=True)
    LOG.setLevel(logging.INFO)
    LOG.propagate = False
    for handler in LOG.handlers[:]:
        LOG.removeHandler(handler)
        handler.close()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for handler in (logging.StreamHandler(sys.stderr), RotatingFileHandler(
            ROOT / "logs" / "app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")):
        handler.setFormatter(formatter)
        LOG.addHandler(handler)


def read_dialog(source: str) -> str:
    try:
        if source == "-":
            text = sys.stdin.read(MAX_CHARS + 1)
        else:
            with Path(source).open(encoding="utf-8-sig") as stream:
                text = stream.read(MAX_CHARS + 1)
    except UnicodeError:
        raise AppError("Диалог должен быть текстовым файлом UTF-8.") from None
    except OSError:
        raise AppError("Не удалось прочитать файл диалога. Проверьте путь и права доступа.") from None
    if len(text) > MAX_CHARS:
        raise AppError(f"Слишком длинный диалог: допускается до {MAX_CHARS} символов.")
    if not text.strip():
        raise AppError("Диалог пуст. Добавьте текст разговора.")
    return text.strip()


def run(source: str, output_dir: Path) -> Path:
    text = read_dialog(source)
    LOG.info("input_read chars=%d", len(text))
    # Load only this project's .env, not an arbitrary parent file.
    load_dotenv(ROOT / ".env", override=False)
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        raise AppError("Не задан OPENAI_API_KEY. Заполните .env по образцу .env.example.")
    model = os.getenv("OPENAI_MODEL", "gpt-6-luna").strip()
    if not model or len(model) > 100 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._" for c in model):
        raise AppError("Некорректное имя OPENAI_MODEL в настройках.")
    # Fail before spending API credits if the output directory is not writable.
    output_dir.mkdir(parents=True, exist_ok=True)
    report_id = datetime.now(TIMEZONE).strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:8]
    prefix = output_dir / f"report_{report_id}"
    json_path = prefix.with_suffix(".json")
    html_path = prefix.with_suffix(".html")
    pdf_path = prefix.with_suffix(".pdf")
    probe = output_dir / (".write_probe_" + uuid4().hex)
    probe.touch(exist_ok=False)
    probe.unlink()
    report, api_metadata = process_dialog_with_ai(text, key, model)
    generated_at = datetime.now(TIMEZONE).isoformat(timespec="seconds")
    envelope = {"schema_version": 1, "generated_at": generated_at, "report_id": report_id,
                "input_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "api": api_metadata, "report": report.model_dump()}
    json_path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LOG.info("json_saved file=%s", json_path.name)
    html = render_html(report, generated_at, report_id)
    html_path.write_text(html, encoding="utf-8")
    LOG.info("html_rendered file=%s", html_path.name)
    # A temporary PDF prevents a partial PDF from looking like a completed report.
    temporary = prefix.with_suffix(".pdf.tmp")
    try:
        write_pdf(html, temporary)
        temporary.replace(pdf_path)
    finally:
        temporary.unlink(missing_ok=True)
    LOG.info("report_complete id=%s", report_id)
    return pdf_path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Создать PDF-отчет из диалога с клиентом через OpenAI.")
    parser.add_argument("dialog", help="Путь к UTF-8 файлу или - для стандартного ввода")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports", help="Папка результатов (по умолчанию reports/ проекта)")
    args = parser.parse_args(argv)
    try:
        setup_logging()
        pdf_path = run(args.dialog, args.output_dir.resolve())
        print(f"Отчет успешно создан: {pdf_path}")
        print("JSON и HTML сохранены рядом с PDF.")
        return 0
    except AppError as exc:
        LOG.error("pipeline_failed message=%s", exc)
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    except OSError:
        LOG.error("pipeline_failed type=filesystem")
        print("Ошибка доступа к файлам или папкам. Проверьте свободное место и права.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        LOG.warning("pipeline_cancelled")
        print("Операция отменена.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
