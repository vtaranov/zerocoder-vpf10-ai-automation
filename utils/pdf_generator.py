import logging
import os
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateError, select_autoescape

from utils.errors import AppError
from utils.schema import DialogReport

ROOT = Path(__file__).resolve().parents[1]
LOG = logging.getLogger("vpf10")
MOODS = {"positive": "Положительный", "neutral": "Нейтральный",
         "negative": "Отрицательный", "mixed": "Смешанный", "unknown": "Недостаточно данных"}


def render_html(report: DialogReport, generated_at: str, report_id: str) -> str:
    env = Environment(loader=FileSystemLoader(ROOT / "templates"),
                      autoescape=select_autoescape(["html"]), undefined=StrictUndefined)
    try:
        return env.get_template("report_template.html").render(
            report=report, generated_at=generated_at, report_id=report_id,
            mood_label=MOODS[report.mood],
        )
    except (TemplateError, OSError):
        raise AppError("Не удалось заполнить HTML-шаблон отчета.") from None


def write_pdf(html: str, target: Path) -> None:
    # Keep Fontconfig's cache within the project, including in restricted shells.
    cache = ROOT / ".cache"
    cache.mkdir(exist_ok=True)
    os.environ.setdefault("XDG_CACHE_HOME", str(cache))
    # Homebrew's Pango is installed on this Mac; cffi needs its library directory.
    if sys.platform == "darwin" and "DYLD_FALLBACK_LIBRARY_PATH" not in os.environ:
        dirs = [str(p) for p in (Path("/opt/homebrew/lib"), Path("/usr/local/lib")) if p.is_dir()]
        if dirs:
            os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = ":".join(dirs)
    try:
        from weasyprint import HTML

        def deny_external_resources(url, *args, **kwargs):
            raise ValueError("External resources are disabled for this text-only template")

        HTML(string=html, url_fetcher=deny_external_resources).write_pdf(target)
    except (ImportError, OSError):
        raise AppError("WeasyPrint не смог создать PDF. Проверьте установку WeasyPrint и системной библиотеки Pango.") from None
    except Exception:
        raise AppError("Ошибка генерации PDF через WeasyPrint.") from None
    LOG.info("pdf_created file=%s bytes=%d", target.name, target.stat().st_size)
