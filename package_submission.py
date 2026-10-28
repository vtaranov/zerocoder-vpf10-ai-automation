"""Build a source-only homework ZIP from an explicit allowlist."""
from pathlib import Path
import re
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parent
FILES = ["README.md", "main.py", "run.sh", "check_live.py", "package_submission.py",
         "requirements.txt", "requirements-dev.txt", "requirements-lock.txt",
         ".gitignore", ".env.example", "reports/.gitkeep", "logs/.gitkeep"]
PATTERNS = [("utils", "*.py"), ("tests", "*.py"), ("templates", "*.html"), ("examples", "*.txt")]


def build() -> Path:
    files = [ROOT / name for name in FILES]
    for folder, pattern in PATTERNS:
        files.extend(sorted((ROOT / folder).glob(pattern)))
    for path in files:
        data = path.read_bytes()
        if re.search(rb"sk-[A-Za-z0-9_-]{20,}", data):
            raise SystemExit(f"Possible API key in {path.relative_to(ROOT)}; archive not built")
    target = ROOT.parent / "VPf10-ai-automation.zip"
    with ZipFile(target, "w", compression=ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, Path("VPf10-ai-automation") / path.relative_to(ROOT))
    with ZipFile(target) as archive:
        if archive.testzip() is not None:
            raise SystemExit("ZIP integrity check failed")
    print(f"Source ZIP: {target} ({len(files)} files)")
    return target


if __name__ == "__main__":
    build()
