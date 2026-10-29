"""
Candidate Resume Store for ApexApply Job Agent
==============================================
The candidate's real, reviewed resume PDFs are the only resumes ever uploaded.
Each variant lives in data/base_resumes/ as <variant>.pdf plus <variant>.txt
(text extracted from the PDF, used for scoring and for LLM context).

Variants:
- general: Forward Deployed PM, general AI/enterprise
- fintech: Forward Deployed PM, fintech / financial services
"""

import re
from pathlib import Path
from typing import Dict, Any, Optional

DEFAULT_DATA_DIR = Path(__file__).parent.parent / "data"
VARIANTS = ("general", "fintech")

FINTECH_SIGNALS = re.compile(
    r"\b(fintech|financial services|banking|bank|payments?|lending|credit|underwriting|kyc|aml|"
    r"wealth|brokerage|insurance|insurtech|capital markets|treasury|compliance|fraud|reconciliation|"
    r"fp&a|accounting)\b",
    re.I,
)


class ResumeStore:
    def __init__(self, data_dir: Optional[Path] = None):
        self.dir = (data_dir or DEFAULT_DATA_DIR) / "base_resumes"
        self.dir.mkdir(parents=True, exist_ok=True)

    def pdf_path(self, variant: str) -> Path:
        return self.dir / f"{variant}.pdf"

    def text_path(self, variant: str) -> Path:
        return self.dir / f"{variant}.txt"

    def available(self) -> Dict[str, bool]:
        return {v: self.pdf_path(v).exists() for v in VARIANTS}

    def save_pdf(self, variant: str, content: bytes) -> Dict[str, Any]:
        if variant not in VARIANTS:
            raise ValueError(f"Unknown resume variant '{variant}' (use {', '.join(VARIANTS)})")
        if not content.startswith(b"%PDF"):
            raise ValueError("Uploaded file is not a PDF")
        self.pdf_path(variant).write_bytes(content)
        text = extract_pdf_text(self.pdf_path(variant))
        self.text_path(variant).write_text(text, encoding="utf-8")
        return {"variant": variant, "chars": len(text)}

    def choose_variant(self, job: Dict[str, Any]) -> str:
        """Picks the fintech resume when the role is clearly financial-services, else general."""
        haystack = f"{job.get('title', '')} {job.get('company', '')} {job.get('description_raw', '')}"
        hits = len(FINTECH_SIGNALS.findall(haystack))
        variant = "fintech" if hits >= 3 else "general"
        if not self.pdf_path(variant).exists():
            other = "general" if variant == "fintech" else "fintech"
            if self.pdf_path(other).exists():
                return other
        return variant

    def get(self, variant: str) -> Optional[Dict[str, Any]]:
        pdf = self.pdf_path(variant)
        if not pdf.exists():
            return None
        txt = self.text_path(variant)
        if not txt.exists():
            txt.write_text(extract_pdf_text(pdf), encoding="utf-8")
        return {"variant": variant, "pdf_path": str(pdf), "text": txt.read_text(encoding="utf-8")}


def extract_pdf_text(pdf_path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    return "\n".join((page.extract_text() or "") for page in reader.pages).strip()
