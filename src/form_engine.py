"""
Form Engine for ApexApply Job Agent
===================================
Reads the fields actually present on a live application form (label, type, required flag,
options), answers each one from the candidate profile (and the LLM for free-text questions),
fills them with Playwright, and verifies submission.

Every platform handler drives this engine; handlers only decide how to reach the form
(URL rewrites, iframes, "Apply" buttons) and which button submits it.
"""

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable

# JS executed in the page/frame: enumerates visible, fillable form controls.
# Radio and checkbox groups are collapsed into one field with options.
DISCOVER_JS = r"""
() => {
  const visible = (el) => {
    if (el.type === 'file') return true;  // file inputs are often visually hidden behind a button
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  const clean = (t) => (t || '').replace(/\s+/g, ' ').trim();
  const labelFor = (el) => {
    if (el.id) {
      const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (l) return clean(l.innerText);
    }
    const by = el.getAttribute('aria-labelledby');
    if (by) {
      const t = by.split(/\s+/).map(id => document.getElementById(id)).filter(Boolean).map(n => n.innerText).join(' ');
      if (clean(t)) return clean(t);
    }
    const anc = el.closest('label');
    if (anc) return clean(anc.innerText);
    if (el.getAttribute('aria-label')) return clean(el.getAttribute('aria-label'));
    // Greenhouse/Lever/Ashby wrap each question in a container with a label-ish first child
    const box = el.closest('.field, .application-question, .application-field, [class*="question"], [class*="Field"], fieldset, li');
    if (box) {
      const lab = box.querySelector('label, legend, .application-label, [class*="label"], [class*="Label"]');
      if (lab && clean(lab.innerText)) return clean(lab.innerText);
    }
    return clean(el.placeholder || el.name || el.id);
  };
  const out = [];
  const groups = {};
  let idx = 0;
  for (const el of document.querySelectorAll('input, textarea, select')) {
    const type = (el.type || el.tagName).toLowerCase();
    if (['hidden', 'submit', 'button', 'reset', 'image', 'search'].includes(type)) continue;
    if (el.disabled || !visible(el)) continue;
    const marker = `apx-${idx++}`;
    el.setAttribute('data-apx', marker);
    const label = labelFor(el);
    const required = el.required || el.getAttribute('aria-required') === 'true' || /\*\s*$/.test(label) || /\(required\)/i.test(label);
    if (type === 'radio' || type === 'checkbox') {
      const box = el.closest('fieldset, .field, .application-question, [class*="question"], li') || el.parentElement;
      const legend = box ? box.querySelector('legend, .application-label, label:not(:has(input))') : null;
      const key = el.name || (box && box.getAttribute('data-apx-group')) || marker;
      const optLabel = clean((el.closest('label') || {}).innerText) || labelFor(el) || el.value;
      if (!groups[key]) {
        groups[key] = { kind: type, name: key, label: clean(legend ? legend.innerText : label), required, options: [], markers: [], id: el.id, html_name: el.name };
        out.push(groups[key]);
      }
      groups[key].options.push(optLabel);
      groups[key].markers.push(marker);
      groups[key].required = groups[key].required || required;
      continue;
    }
    const f = { kind: el.tagName.toLowerCase() === 'select' ? 'select' : (type === 'file' ? 'file' : (el.tagName.toLowerCase() === 'textarea' ? 'textarea' : 'text')),
                label, required, marker, id: el.id || '', html_name: el.name || '', autocomplete: el.autocomplete || '',
                input_type: type, role: el.getAttribute('role') || '', options: [] };
    if (f.kind === 'select') f.options = Array.from(el.options).map(o => clean(o.text)).filter(t => t && !/^select|^--/i.test(t));
    out.push(f);
  }
  return out;
}
"""

CAPTCHA_SELECTORS = "iframe[src*='recaptcha'], iframe[src*='hcaptcha'], iframe[title*='captcha' i], .g-recaptcha, .h-captcha, iframe[src*='turnstile']"
CONFIRMATION_PATTERNS = re.compile(
    r"(thank you for (applying|your (application|interest))|application (has been )?(submitted|received)|"
    r"we('ve| have) received your application|successfully submitted)", re.I)
ERROR_SELECTORS = "[aria-invalid='true'], .field-error, .error-message, [class*='error' i]:not(:empty)"

# Ordered (pattern, profile_key). Matched against "label id name autocomplete" (lowercased).
PROFILE_RULES = [
    (r"\b(first|given)[ _-]?name\b|given-name|\bfname\b", "first_name"),
    (r"\b(last|family|sur)[ _-]?name\b|family-name|\blname\b", "last_name"),
    (r"preferred (first )?name", "first_name"),
    (r"\bfull[ _-]?name\b|^name\b|^name$|your name|legal name", "full_name"),
    (r"e-?mail", "email"),
    (r"phone|mobile|\btel\b", "phone"),
    (r"linkedin", "linkedin_url"),
    (r"github", "github_url"),
    (r"website|portfolio|personal (site|url)|blog", "portfolio_url"),
    (r"\bcity\b|location|where are you (located|based)|current address|\baddress\b", "address"),
    (r"salary|compensation|pay expectation", "salary_expectation"),
    (r"years of (professional |relevant )?experience|how many years", "years_experience"),
    (r"current (company|employer)|most recent (company|employer)", "current_company"),
    (r"current (title|role|position)", "current_title"),
    (r"(legally )?authori[sz]ed to work|work authori[sz]ation|eligible to work", "work_authorization"),
    (r"(require|need).*(sponsor|visa)|sponsorship", "requires_sponsorship"),
    (r"how did you (hear|find)|referr?al source|source", "heard_about"),
    (r"pronouns", "pronouns"),
    (r"notice period|start date|when can you start|availability", "start_availability"),
    (r"relocat", "willing_to_relocate"),
]

# Voluntary self-identification questions: always answered with a decline option, never guessed.
EEO_PATTERN = re.compile(r"gender|race|ethnic|hispanic|latino|veteran|disabilit|sexual orientation|transgender", re.I)
DECLINE_PATTERN = re.compile(r"decline|prefer not|don.?t wish|do not wish|not to (say|answer|disclose)|choose not", re.I)


@dataclass
class FormField:
    kind: str
    label: str
    required: bool
    marker: Optional[str] = None
    markers: List[str] = field(default_factory=list)
    options: List[str] = field(default_factory=list)
    id: str = ""
    html_name: str = ""
    autocomplete: str = ""
    input_type: str = ""
    role: str = ""
    name: str = ""

    @property
    def key_text(self) -> str:
        return f"{self.label} {self.id} {self.html_name} {self.autocomplete}".lower()


@dataclass
class FormRun:
    fields: List[FormField] = field(default_factory=list)
    answers: Dict[str, Any] = field(default_factory=dict)      # label -> value actually filled
    unanswered_required: List[str] = field(default_factory=list)
    fill_errors: List[str] = field(default_factory=list)
    captcha: bool = False


def _yes_no(value: Any) -> str:
    v = str(value).strip().lower()
    if v in ("true", "yes", "y", "1") or v.startswith("yes") or "citizen" in v or "permanent resident" in v or "authorized" in v:
        return "Yes"
    return "No"


class FormEngine:
    def __init__(self, profile: Dict[str, Any], resume_path: str = "", cover_letter_path: str = "",
                 question_answerer: Optional[Callable[[List[Dict[str, Any]]], Dict[str, str]]] = None):
        self.profile = profile
        self.resume_path = resume_path
        self.cover_letter_path = cover_letter_path
        self.question_answerer = question_answerer
        self.custom = profile.get("custom_field_answers") or {}

    # ── Discovery ──────────────────────────────────────────────
    def discover(self, frame) -> List[FormField]:
        raw = frame.evaluate(DISCOVER_JS)
        allowed = set(FormField.__dataclass_fields__)
        return [FormField(**{k: v for k, v in r.items() if k in allowed}) for r in raw]

    # ── Answering ──────────────────────────────────────────────
    def profile_value(self, key: str) -> Optional[str]:
        p = self.profile
        full = p.get("full_name") or ""
        if key == "first_name":
            return p.get("first_name") or (full.split()[0] if full else None)
        if key == "last_name":
            return p.get("last_name") or (full.split()[-1] if full else None)
        if key == "work_authorization":
            wa = p.get("work_authorization")
            return wa if wa else None
        if key == "requires_sponsorship":
            v = p.get("requires_sponsorship")
            if v is None:
                v = self.custom.get("requires_sponsorship")
            return None if v is None else ("Yes" if _yes_no(v) == "Yes" else "No")
        v = p.get(key)
        if v in (None, ""):
            v = self.custom.get(key)
        return None if v in (None, "") else str(v)

    def match_profile_key(self, f: FormField) -> Optional[str]:
        text = f.key_text
        for pattern, key in PROFILE_RULES:
            if re.search(pattern, text):
                return key
        return None

    def answer_for(self, f: FormField) -> Optional[str]:
        if f.kind == "file":
            if re.search(r"cover", f.key_text):
                return self.cover_letter_path or None
            if re.search(r"resume|cv|curriculum", f.key_text) or not f.label:
                return self.resume_path or None
            return None

        if EEO_PATTERN.search(f.label):
            decline = next((o for o in f.options if DECLINE_PATTERN.search(o)), None)
            return decline  # leave free-text EEO fields blank

        # Exact custom answer for this question text wins.
        for k, v in self.custom.items():
            if k.strip().lower() == f.label.strip().lower().rstrip("*").strip():
                return str(v)

        key = self.match_profile_key(f)
        if key:
            v = self.profile_value(key)
            if v is None:
                return None
            if f.options or f.kind in ("radio", "checkbox"):
                if key in ("work_authorization", "requires_sponsorship", "willing_to_relocate"):
                    return _yes_no(v) if key != "requires_sponsorship" else v
            return v
        return None

    def resolve_answers(self, fields: List[FormField], job_context: Dict[str, Any]) -> Dict[int, str]:
        answers: Dict[int, str] = {}
        open_questions = []
        for i, f in enumerate(fields):
            a = self.answer_for(f)
            if a is not None:
                answers[i] = a
            elif f.kind != "file" and not EEO_PATTERN.search(f.label) and f.label:
                open_questions.append({"index": i, "question": f.label, "kind": f.kind,
                                       "options": f.options, "required": f.required})
        if open_questions and self.question_answerer:
            try:
                llm_answers = self.question_answerer(open_questions) or {}
            except Exception:
                llm_answers = {}
            for q in open_questions:
                a = llm_answers.get(str(q["index"])) or llm_answers.get(q["question"])
                if a:
                    answers[q["index"]] = str(a)
        return answers

    # ── Filling ────────────────────────────────────────────────
    @staticmethod
    def best_option(options: List[str], answer: str) -> Optional[str]:
        a = answer.strip().lower()
        for o in options:
            if o.strip().lower() == a:
                return o
        for o in options:
            ol = o.strip().lower()
            if ol.startswith(a) or a.startswith(ol):
                return o
        for o in options:
            if a in o.lower() or o.lower() in a:
                return o
        return None

    def fill(self, frame, fields: List[FormField], answers: Dict[int, str]) -> FormRun:
        run = FormRun(fields=fields)
        for i, f in enumerate(fields):
            answer = answers.get(i)
            display = f.label or f.html_name or f.id or f"field_{i}"
            if answer is None or answer == "":
                if f.required:
                    run.unanswered_required.append(display)
                continue
            try:
                if f.kind == "file":
                    if not Path(answer).exists():
                        raise FileNotFoundError(answer)
                    frame.locator(f"[data-apx='{f.marker}']").set_input_files(answer)
                    run.answers[display] = Path(answer).name
                elif f.kind == "select":
                    opt = self.best_option(f.options, answer)
                    if not opt:
                        raise ValueError(f"no option matching '{answer}'")
                    frame.locator(f"[data-apx='{f.marker}']").select_option(label=opt)
                    run.answers[display] = opt
                elif f.kind in ("radio", "checkbox"):
                    opt = self.best_option(f.options, answer)
                    if not opt and len(f.options) == 1 and _yes_no(answer) == "Yes":
                        opt = f.options[0]  # single consent checkbox
                    if not opt:
                        raise ValueError(f"no option matching '{answer}'")
                    frame.locator(f"[data-apx='{f.markers[f.options.index(opt)]}']").check(force=True)
                    run.answers[display] = opt
                else:
                    loc = frame.locator(f"[data-apx='{f.marker}']")
                    loc.fill(str(answer))
                    if f.role == "combobox" or f.input_type == "search":
                        # React-select style dropdowns (new Greenhouse boards): pick the first match.
                        frame.wait_for_timeout(400)
                        loc.press("Enter")
                    run.answers[display] = answer
            except Exception as e:
                run.fill_errors.append(f"{display}: {e}")
                if f.required:
                    run.unanswered_required.append(display)
        return run

    # ── Submission / verification ──────────────────────────────
    @staticmethod
    def has_captcha(frame) -> bool:
        try:
            return frame.locator(CAPTCHA_SELECTORS).count() > 0
        except Exception:
            return False

    @staticmethod
    def page_shows_confirmation(page) -> bool:
        try:
            if re.search(r"confirm|thank|success|submitted", page.url, re.I):
                return True
            for fr in page.frames:
                try:
                    if CONFIRMATION_PATTERNS.search(fr.inner_text("body", timeout=1000)):
                        return True
                except Exception:
                    continue
        except Exception:
            pass
        return False

    def submit_and_verify(self, page, frame, submit_selector: str, timeout_ms: int = 20000) -> Dict[str, Any]:
        """Clicks submit and waits for real evidence of success (confirmation text/URL that was not there before)."""
        try:
            before = CONFIRMATION_PATTERNS.search(frame.inner_text("body", timeout=2000)) is not None
        except Exception:
            before = False
        btn = frame.locator(submit_selector)
        if btn.count() == 0:
            return {"submitted": False, "error": "Submit button not found"}
        btn.first.click()
        deadline = time.time() + timeout_ms / 1000
        while time.time() < deadline:
            page.wait_for_timeout(500)
            if not before and self.page_shows_confirmation(page):
                return {"submitted": True, "error": None}
            if self.has_captcha(frame):
                return {"submitted": False, "error": "CAPTCHA challenge appeared after submit", "captcha": True}
        errors = []
        try:
            errs = frame.locator(ERROR_SELECTORS)
            for j in range(min(errs.count(), 5)):
                t = errs.nth(j).inner_text().strip()
                if t:
                    errors.append(t[:120])
        except Exception:
            pass
        msg = "No confirmation detected after submit"
        if errors:
            msg += f"; form errors: {errors}"
        return {"submitted": False, "error": msg}
