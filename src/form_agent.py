"""
Form Agent for ApexApply Job Agent
==================================
Drives a real application form with Playwright:

1. Opens the posting's application page and waits for the form.
2. Discovers every visible field with its label, type, options and required flag.
3. Answers standard fields (name, contact, links, work authorization, sponsorship,
   EEO, consent) from the profile, and other questions with the LLM.
4. Uploads the candidate's real resume PDF and the generated cover letter.
5. Submits only when auto_submit is on AND every required field was answered
   AND no captcha is visible; then verifies the confirmation page.

Anything short of a verified confirmation is reported honestly
(PENDING_REVIEW / CAPTCHA_BLOCKED / FAILED) with the reason and screenshots.
"""

import re
import time
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable

from src.handlers.base_handler import FillResult
from src.llm import LLMInterface, LLMError, _best_option

USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")

CONFIRMATION_RE = re.compile(
    r"thank you for (applying|your application|your interest)|application (has been |was )?(submitted|received)|"
    r"we('ve| have) received your application|successfully submitted|thanks for applying",
    re.I,
)
DECLINE_RE = re.compile(r"decline|don.t wish|do not wish|prefer not|not to (say|answer|disclose|self)|i don.t want", re.I)
EEO_RE = re.compile(r"\b(gender|sex\b|race|ethnic|hispanic|latino|veteran|disabilit|sexual orientation|transgender|pronoun)", re.I)
CONSENT_RE = re.compile(r"\b(i agree|agree to|acknowledge|consent|certify|privacy (policy|notice)|terms)\b", re.I)

# Discovers form controls in the page, tags each with data-apex-id, and returns descriptors.
DISCOVER_JS = r"""
() => {
  const vis = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const txt = el => (el ? (el.innerText || el.textContent || '') : '').replace(/\s+/g, ' ').trim();
  const labelOf = el => {
    if (el.id) { const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`); if (l && txt(l)) return txt(l); }
    const lb = el.getAttribute('aria-labelledby');
    if (lb) { const t = lb.split(/\s+/).map(i => txt(document.getElementById(i))).join(' ').trim(); if (t) return t; }
    const al = el.getAttribute('aria-label'); if (al) return al.trim();
    const wrap = el.closest('label'); if (wrap && txt(wrap)) return txt(wrap);
    let p = el.parentElement;
    for (let i = 0; i < 6 && p; i++, p = p.parentElement) {
      const l = p.querySelector('label, legend, [class*="label"], .text');
      if (l && !l.contains(el) && txt(l)) return txt(l);
    }
    return el.placeholder || el.name || '';
  };
  const groupLabel = el => {
    const fs = el.closest('fieldset'); if (fs) { const lg = fs.querySelector('legend'); if (lg && txt(lg)) return txt(lg); }
    let p = el.parentElement;
    for (let i = 0; i < 6 && p; i++, p = p.parentElement) {
      const others = p.querySelectorAll(`input[name="${CSS.escape(el.name)}"]`);
      if (others.length > 1 || i > 2) {
        const l = p.querySelector('legend, [class*="label"]:not(label), .text, label:not(:has(input))');
        if (l && txt(l)) return txt(l);
      }
    }
    return el.name || '';
  };
  const isReq = (el, label) => el.required || el.getAttribute('aria-required') === 'true' || /\*\s*$|\*\s/.test(label || '');
  const out = []; const groups = {}; let n = 0;
  for (const el of document.querySelectorAll('input, textarea, select')) {
    const type = (el.type || el.tagName).toLowerCase();
    if (['hidden', 'submit', 'button', 'image', 'reset', 'search'].includes(type)) continue;
    if (type !== 'file' && !vis(el) && !(type === 'radio' || type === 'checkbox')) continue;
    if (el.closest('[aria-hidden="true"]') && type !== 'file') continue;
    const id = 'apex' + (n++); el.setAttribute('data-apex-id', id);
    if (type === 'radio' || type === 'checkbox') {
      const optLabel = labelOf(el);
      const visTarget = vis(el) || (el.labels && el.labels[0] && vis(el.labels[0]));
      if (!visTarget) continue;
      const key = (type === 'radio' || el.name.endsWith('[]')) && el.name ? `${type}:${el.name}` : null;
      if (key) {
        if (!groups[key]) { groups[key] = { key, kind: type === 'radio' ? 'radio' : 'checkboxgroup', label: groupLabel(el),
          required: false, options: [], ids: [] }; out.push(groups[key]); }
        const g = groups[key]; g.options.push(optLabel); g.ids.push(id); g.required = g.required || isReq(el, g.label);
      } else {
        out.push({ key: id, kind: 'checkbox', label: optLabel, required: isReq(el, optLabel), options: [], ids: [id] });
      }
      continue;
    }
    const label = labelOf(el);
    let kind = el.tagName === 'TEXTAREA' ? 'textarea' : el.tagName === 'SELECT' ? 'select' : type === 'file' ? 'file' : 'text';
    if (el.getAttribute('role') === 'combobox' && el.tagName === 'INPUT') kind = 'combobox';
    const options = el.tagName === 'SELECT' ? [...el.options].map(o => o.text.trim()).filter(t => t && !/^(select|choose|--|please select)/i.test(t)) : [];
    out.push({ key: id, kind, label, required: isReq(el, label), options, ids: [id],
      name: el.name || '', inputType: type, autocomplete: el.getAttribute('autocomplete') || '', accept: el.accept || '' });
  }
  return out;
}
"""

# Standard questions answered straight from the profile: (label regex, profile key)
STANDARD_FIELDS = [
    (r"\bpreferred (first )?name\b", "first_name"),
    (r"\b(first|given|legal first) name\b", "first_name"),
    (r"\b(last|family|legal last) name\b|\bsurname\b", "last_name"),
    (r"^\s*(full |your )?name\s*\*?\s*$|\bfull name\b", "full_name"),
    (r"e-?mail", "email"),
    (r"\bphone|mobile\b", "phone"),
    (r"linkedin", "linkedin_url"),
    (r"github", "github_url"),
    (r"\b(website|portfolio|personal site|blog)\b", "portfolio_url"),
    (r"\bcurrent (company|employer)\b|most recent (company|employer)\b|^company\b|^org(anization)?\b", "current_company"),
    (r"\bcurrent (job )?(title|role|position)\b", "current_title"),
    (r"\b(salary|compensation|pay) (expectation|requirement|range)|desired (salary|compensation)|expected (salary|compensation)", "salary_expectation"),
    (r"(legally )?(authori[sz]ed|eligible) to work|work authori[sz]ation|right to work", "work_authorized"),
    (r"sponsor", "requires_sponsorship"),
    (r"relocat", "willing_to_relocate"),
    (r"how did you (hear|find|learn)|where did you (hear|find|learn)|referral source|source of application", "how_did_you_hear"),
    (r"years of (relevant |professional |product )?(work )?experience", "years_experience"),
    (r"\b(current )?(location|city)\b|where are you (located|based)|^address", "location"),
    (r"notice period|earliest start|when can you start|start date", "start_availability"),
]


def profile_values(profile: Dict[str, Any]) -> Dict[str, str]:
    """Flattens the profile and its custom answers into one lookup."""
    custom = profile.get("custom_field_answers") or {}
    full = (profile.get("full_name") or "").strip()
    vals = {
        "full_name": full,
        "first_name": profile.get("first_name") or (full.split()[0] if full else ""),
        "last_name": profile.get("last_name") or (full.split()[-1] if full else ""),
        "email": profile.get("email", ""),
        "phone": profile.get("phone", ""),
        "linkedin_url": profile.get("linkedin_url", ""),
        "portfolio_url": profile.get("portfolio_url", ""),
        "salary_expectation": profile.get("salary_expectation", ""),
        "years_experience": str(profile.get("years_experience") or ""),
        "location": custom.get("location") or profile.get("address", ""),
    }
    for k, v in custom.items():
        if isinstance(v, (str, int, float)) and str(v).strip():
            vals.setdefault(k, str(v).strip())
    return {k: str(v) for k, v in vals.items() if v not in (None, "")}


class FormAgent:
    def __init__(
        self,
        llm: Optional[LLMInterface] = None,
        submit_selectors: str = "button[type='submit'], input[type='submit']",
        form_ready_selector: str = "form input, form textarea",
        nav_timeout_ms: int = 45000,
        confirm_timeout_s: int = 25,
    ):
        self.llm = llm or LLMInterface()
        self.submit_selectors = submit_selectors
        self.form_ready_selector = form_ready_selector
        self.nav_timeout_ms = nav_timeout_ms
        self.confirm_timeout_s = confirm_timeout_s

    # ─────────────────────────────────────────────────────────────
    # Answering
    # ─────────────────────────────────────────────────────────────
    def resolve(self, field: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        """Returns {"value": ..., "source": profile|rule|llm|file|skip, "confident": bool}."""
        label = field.get("label") or ""
        low = label.lower()
        kind = field["kind"]
        options = field.get("options") or []
        vals = ctx["values"]

        if kind == "file":
            if "cover" in low or "cover" in field.get("name", "").lower():
                path = ctx["cover_letter"]().get("file_path")
                return {"value": path, "source": "file", "confident": bool(path)}
            if re.search(r"resume|cv\b|curriculum", low + " " + field.get("name", "").lower()) or not ctx["resume_uploaded"]:
                return {"value": ctx["resume_pdf"], "source": "file", "confident": True}
            return {"value": None, "source": "skip", "confident": False}

        if EEO_RE.search(low) and options:
            decline = next((o for o in options if DECLINE_RE.search(o)), None)
            if decline:
                return {"value": decline, "source": "rule", "confident": True}

        if kind == "checkbox":
            if CONSENT_RE.search(low):
                return {"value": True, "source": "rule", "confident": True}
            return {"value": None, "source": "skip", "confident": not field["required"]}

        if kind == "textarea" and re.search(r"cover letter|additional information|anything else", low):
            body = ctx["cover_letter"]().get("body", "")
            return {"value": body, "source": "llm", "confident": bool(body)}

        for pattern, key in STANDARD_FIELDS:
            if re.search(pattern, low):
                v = vals.get(key)
                if v is None:
                    break
                if options:
                    match = _best_option(v, options)
                    if match:
                        return {"value": match, "source": "profile", "confident": True}
                    break
                return {"value": v, "source": "profile", "confident": True}

        if not field["required"] and kind in ("text",) and not options:
            # Optional short fields we have no fact for are left blank rather than guessed
            return {"value": None, "source": "skip", "confident": True}

        try:
            ans = self.llm.answer_question(label, kind, options, ctx["profile"], ctx["resume_text"], ctx["job"])
        except LLMError as e:
            return {"value": None, "source": "llm", "confident": False, "error": str(e)}
        if not ans["answer"]:
            return {"value": None, "source": "llm", "confident": False}
        return {"value": ans["answer"], "source": "llm", "confident": ans["confident"]}

    # ─────────────────────────────────────────────────────────────
    # Filling
    # ─────────────────────────────────────────────────────────────
    def _fill(self, page, field: Dict[str, Any], value: Any) -> bool:
        kind = field["kind"]
        sel = f"[data-apex-id='{field['ids'][0]}']"
        try:
            if kind == "file":
                page.set_input_files(sel, value)
            elif kind in ("text", "textarea"):
                page.fill(sel, str(value))
            elif kind == "select":
                page.select_option(sel, label=str(value))
            elif kind == "combobox":
                page.click(sel)
                page.fill(sel, str(value))
                page.wait_for_timeout(600)
                opt = page.locator("[role='option']", has_text=str(value)).first
                if opt.count():
                    opt.click()
                else:
                    page.keyboard.press("Enter")
            elif kind == "checkbox":
                page.check(sel, force=True)
            elif kind in ("radio", "checkboxgroup"):
                wanted = [str(value)] if kind == "radio" else [v.strip() for v in str(value).split(",")]
                hit = False
                for opt_label, opt_id in zip(field["options"], field["ids"]):
                    if any(_best_option(w, [opt_label]) for w in wanted):
                        page.check(f"[data-apex-id='{opt_id}']", force=True)
                        hit = True
                return hit
            return True
        except Exception:
            return False

    def _combobox_options(self, page, field: Dict[str, Any]) -> List[str]:
        sel = f"[data-apex-id='{field['ids'][0]}']"
        try:
            page.click(sel)
            page.wait_for_timeout(500)
            opts = [t.strip() for t in page.locator("[role='option']").all_inner_texts() if t.strip()]
            page.keyboard.press("Escape")
            return opts[:80]
        except Exception:
            return []

    def _captcha_visible(self, page) -> bool:
        for frame_sel in ("iframe[src*='hcaptcha.com'][src*='challenge']", "iframe[src*='recaptcha'][src*='bframe']",
                          "iframe[title*='challenge' i]"):
            loc = page.locator(frame_sel)
            for i in range(loc.count()):
                try:
                    if loc.nth(i).is_visible():
                        return True
                except Exception:
                    pass
        return False

    # ─────────────────────────────────────────────────────────────
    # Main entry
    # ─────────────────────────────────────────────────────────────
    def run(
        self,
        platform: str,
        url: str,
        job: Dict[str, Any],
        profile: Dict[str, Any],
        resume_pdf: str,
        resume_text: str,
        cover_letter: Callable[[], Dict[str, Any]],
        screenshot_path: str,
        auto_submit: bool,
        html_fixture: Optional[str] = None,
    ) -> FillResult:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

        Path(screenshot_path).parent.mkdir(parents=True, exist_ok=True)
        after_path = str(Path(screenshot_path).with_name(Path(screenshot_path).stem + "_after.png"))
        mode = "auto" if auto_submit else "manual_confirm"
        filled: Dict[str, Any] = {}
        unanswered: List[str] = []
        letter_cache: Dict[str, Any] = {}

        def get_letter() -> Dict[str, Any]:
            if "v" not in letter_cache:
                try:
                    letter_cache["v"] = cover_letter() or {}
                except Exception as e:
                    letter_cache["v"] = {"error": str(e)}
            return letter_cache["v"]

        ctx = {"values": profile_values(profile), "profile": profile, "resume_pdf": resume_pdf,
               "resume_text": resume_text, "job": job, "cover_letter": get_letter, "resume_uploaded": False}

        # Written before the browser opens: rendering the letter PDF needs its own Playwright session
        get_letter()

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_context(user_agent=USER_AGENT, viewport={"width": 1280, "height": 1000}).new_page()
                if html_fixture is not None:
                    page.set_content(html_fixture)
                else:
                    page.goto(url, timeout=self.nav_timeout_ms, wait_until="domcontentloaded")
                try:
                    page.wait_for_selector(self.form_ready_selector, timeout=20000)
                except PWTimeout:
                    page.screenshot(path=screenshot_path, full_page=True)
                    return FillResult("FAILED", platform, filled, screenshot_path, submission_mode=mode,
                                      error_message=f"Application form did not load at {url}")

                fields = page.evaluate(DISCOVER_JS)
                for f in fields:
                    if f["kind"] == "combobox":
                        f["options"] = self._combobox_options(page, f)

                for f in fields:
                    label = f.get("label") or f.get("name") or f["key"]
                    res = self.resolve(f, ctx)
                    if res["value"] in (None, "", False):
                        if f["required"]:
                            unanswered.append(label + (f" ({res['error']})" if res.get("error") else ""))
                        continue
                    if f["required"] and not res["confident"]:
                        unanswered.append(f"{label} (unsure: '{str(res['value'])[:60]}')")
                        continue
                    if self._fill(page, f, res["value"]):
                        if f["kind"] == "file" and res["value"] == resume_pdf:
                            ctx["resume_uploaded"] = True
                        filled[label[:120]] = (Path(res["value"]).name if f["kind"] == "file" else res["value"])
                    elif f["required"]:
                        unanswered.append(f"{label} (could not set value)")

                if "error" in letter_cache.get("v", {}):
                    unanswered.append(f"Cover letter generation failed: {letter_cache['v']['error']}")

                page.wait_for_timeout(500)
                page.screenshot(path=screenshot_path, full_page=True)

                if not auto_submit:
                    return FillResult("PENDING_REVIEW", platform, filled, screenshot_path, submission_mode=mode,
                                      error_message=_summary("Review mode: filled, not submitted", unanswered))
                if unanswered:
                    return FillResult("PENDING_REVIEW", platform, filled, screenshot_path, submission_mode=mode,
                                      error_message=_summary("Not submitted, needs your answers", unanswered))
                if self._captcha_visible(page):
                    return FillResult("CAPTCHA_BLOCKED", platform, filled, screenshot_path, captcha_detected=True,
                                      submission_mode=mode, error_message="Captcha shown before submit")

                submit = page.locator(self.submit_selectors).first
                if not submit.count():
                    return FillResult("FAILED", platform, filled, screenshot_path, submission_mode=mode,
                                      error_message="Submit button not found")
                submit.click()

                deadline = time.time() + self.confirm_timeout_s
                status, err = "PENDING_REVIEW", "Clicked submit but no confirmation appeared"
                while time.time() < deadline:
                    page.wait_for_timeout(1000)
                    body = page.inner_text("body") if page.locator("body").count() else ""
                    if CONFIRMATION_RE.search(body) or re.search(r"/confirmation|/thanks|/success", page.url):
                        status, err = "SUBMITTED", None
                        break
                    if self._captcha_visible(page):
                        status, err = "CAPTCHA_BLOCKED", "Captcha challenge appeared after submit"
                        break
                    if re.search(r"security code|verification code", body, re.I):
                        status, err = "PENDING_REVIEW", "Site emailed a security code; enter it to finish"
                        break
                page.screenshot(path=after_path, full_page=True)
                return FillResult(status, platform, filled, after_path, captcha_detected=status == "CAPTCHA_BLOCKED",
                                  submission_mode=mode, error_message=err)
            except PWTimeout as e:
                return FillResult("FAILED", platform, filled, None, submission_mode=mode,
                                  error_message=f"Timed out loading {url}: {e}")
            except Exception as e:
                return FillResult("FAILED", platform, filled, None, submission_mode=mode,
                                  error_message=f"{type(e).__name__}: {e}")
            finally:
                browser.close()


def _summary(prefix: str, unanswered: List[str]) -> str:
    if not unanswered:
        return prefix
    return f"{prefix}. Unanswered required fields: " + "; ".join(unanswered[:12])
