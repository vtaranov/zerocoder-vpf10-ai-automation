"""Paid integration check using the real OpenAI API and synthetic dialogs only."""
import json
from datetime import datetime
from pathlib import Path

from pypdf import PdfReader

from main import ROOT, TIMEZONE, run, setup_logging
from utils.schema import DialogReport


def check() -> None:
    setup_logging()
    results = []
    for filename in ("dialog.txt", "minimal_dialog.txt"):
        pdf = run(str(ROOT / "examples" / filename), ROOT / "reports")
        envelope = json.loads(pdf.with_suffix(".json").read_text(encoding="utf-8"))
        report = DialogReport.model_validate(envelope["report"])
        reader = PdfReader(pdf)
        text = "\n".join(page.extract_text() for page in reader.pages)
        checks = {"valid_json_schema": True, "pdf_readable": len(reader.pages) > 0,
                  "cyrillic": "Контекст разговора" in text,
                  "html_saved": pdf.with_suffix(".html").is_file(),
                  "page_numbers": all("Страница" in page.extract_text() for page in reader.pages)}
        if filename == "dialog.txt":
            checks.update(
                client_name="Марина" in (report.client_name or ""),
                budget="60" in (report.budget or ""),
                budget_not_final="не соглас" in (report.budget or "").lower(),
                separate_api_cost="отдельно" in (report.budget or "").lower(),
                deadline="две недели" in (report.deadline or "").lower() or "2 недели" in (report.deadline or ""),
                agreed_client_step=any(s.status == "agreed" and s.deadline and "завтра" in s.deadline.lower()
                                       for s in report.next_steps),
                agreed_consultant_step=any(s.status == "agreed" and "pdf" in s.action.lower()
                                           for s in report.next_steps),
                conditional_consultant_deadline=any(s.status == "agreed" and s.deadline and "получ" in s.deadline.lower()
                                                    for s in report.next_steps),
                crm_not_agreed=all(s.status != "agreed" for s in report.next_steps if "crm" in s.action.lower()),
            )
        else:
            checks.update(unknown_client=report.client_name is None, unknown_budget=report.budget is None,
                          unknown_deadline=report.deadline is None,
                          no_invented_agreement=all(s.status == "proposed" for s in report.next_steps),
                          only_requested_action=len(report.next_steps) == 1 and "подробност" in report.next_steps[0].action.lower())
        results.append({"input": filename, "pdf": str(pdf.relative_to(ROOT)), "pages": len(reader.pages),
                        "api": envelope["api"], "checks": checks, "passed": all(checks.values())})
    protocol = {"checked_at": datetime.now(TIMEZONE).isoformat(timespec="seconds"),
                "results": results, "passed": all(r["passed"] for r in results)}
    stamp = datetime.now(TIMEZONE).strftime("%Y%m%d_%H%M%S_%f")
    destination = ROOT / "local_checks" / f"live_check_{stamp}.json"
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(protocol, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (destination.parent / "live_check.json").write_text(destination.read_text(encoding="utf-8"), encoding="utf-8")
    for result in results:
        print(result["input"], result["checks"], "->", result["pdf"])
    print("Protocol:", destination)
    if not protocol["passed"]:
        raise SystemExit("Some live checks failed; inspect the retained JSON and PDF.")


if __name__ == "__main__":
    check()
