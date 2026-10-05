"""Monash Hub's own Chinese, read from its frontend source.

/ask answers Handbook questions with English text plus translation keys (``answer.assessment.noExam``,
``column_keys``, ``terms``); the website turns those into Chinese in the browser with two files:

- ``frontend/i18n/index.ts`` - the UI sentences, one object per locale;
- ``frontend/i18n/handbook-terms.ts`` - hand-checked Chinese for the Handbook's closed vocabularies
  (campuses, teaching periods, attendance modes, assessment types, ...).

This module parses those files and ports the lookup rules (AnswerBlocks.vue ``say``/``cell``,
``handbookTerm``, ``assessmentName``), so the bot says exactly what the website says. The one rule
that matters is the website's: a value with no entry stays in English, it is never guessed.
Copies of both files are refreshed by wechat-bot-mamo.service; see config.HUB_I18N_DIR.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

_STR = r"'(?:[^'\\]|\\.)*'"
_PAIR = re.compile(r"(?:'((?:[^'\\]|\\.)*)'|([A-Za-z_]\w*))\s*:\s*((?:" + _STR + r"\s*\+?\s*)+)")
_PART = re.compile(r"'((?:[^'\\]|\\.)*)'")
_PARAM = re.compile(r"\{(\w+)\}")

_TERM_CONSTS = {
    "zhCampus": "campus", "zhPeriod": "period", "zhMode": "mode", "zhFaculty": "faculty",
    "zhAssessmentType": "assessmentType", "zhHurdle": "hurdle", "zhRequisiteType": "requisiteType",
    "zhConnector": "connector", "zhActivityType": "activityType",
}
_MODE_CODE = re.compile(r"\(([A-Z][A-Z0-9-]*)\)\s*$")
_LEVEL = re.compile(r"^Level\s+(\d+)$", re.I)
_NUMBERED_ASSESSMENT = re.compile(r"^(\d+)\s*[-–]\s*(.+)$")


def _unescape(s: str) -> str:
    return re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), s)


def _strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return "\n".join(line for line in src.splitlines() if not line.lstrip().startswith("//"))


def _object_body(src: str, header: str) -> str:
    """Text between ``header`` (e.g. "const zh: Messages = {") and its closing brace."""
    start = src.find(header)
    if start < 0:
        return ""
    i, depth = src.index("{", start), 0
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[i + 1:j]
    return ""


def parse_object(body: str) -> dict[str, str]:
    out = {}
    for quoted, bare, value in _PAIR.findall(body):
        out[_unescape(quoted) if quoted else bare] = "".join(_unescape(p) for p in _PART.findall(value))
    return out


class HubI18n:
    def __init__(self, zh: dict[str, str], en: dict[str, str], terms: dict[str, dict[str, str]]):
        self.zh, self.en, self.terms = zh, en, terms

    @classmethod
    def empty(cls) -> "HubI18n":
        return cls({}, {}, {})

    @classmethod
    def parse(cls, index_ts: str, terms_ts: str) -> "HubI18n":
        index_ts, terms_ts = _strip_comments(index_ts), _strip_comments(terms_ts)
        zh = parse_object(_object_body(index_ts, "const zh: Messages = {"))
        en = parse_object(_object_body(index_ts, "const en: Messages = {"))
        terms = {kind: parse_object(_object_body(terms_ts, f"const {const}: Dictionary = {{"))
                 for const, kind in _TERM_CONSTS.items()}
        return cls(zh, en, terms)

    @classmethod
    def load(cls, directory: Path) -> "HubI18n":
        try:
            i18n = cls.parse((directory / "index.ts").read_text(encoding="utf-8"),
                             (directory / "handbook-terms.ts").read_text(encoding="utf-8"))
        except OSError as exc:
            log.warning("Monash Hub i18n files unavailable (%s); answers stay in English", exc)
            return cls.empty()
        log.info("loaded Monash Hub i18n: %d zh strings, %d term entries",
                 len(i18n.zh), sum(len(d) for d in i18n.terms.values()))
        return i18n

    # -- index.ts translate() ---------------------------------------------------------------------
    def t(self, key: str | None, params: dict | None = None) -> str | None:
        if not key:
            return None
        template = self.zh.get(key) or self.en.get(key)
        if template is None:
            return None
        params = params or {}
        return _PARAM.sub(lambda m: str(params[m.group(1)]) if m.group(1) in params else m.group(0), template)

    def say(self, key: str | None, text: str | None, params: dict | None = None,
            terms: dict[str, str] | None = None) -> str:
        """AnswerBlocks.vue say(): our sentence in Chinese, the English text when the key is unknown."""
        if not key:
            return text or ""
        resolved = dict(params or {})
        for name, kind in (terms or {}).items():
            if resolved.get(name) is not None:
                resolved[name] = self.term(kind, str(resolved[name]))
        return self.t(key, resolved) or text or ""

    # -- handbook-terms.ts ------------------------------------------------------------------------
    def term(self, kind: str, value: str | None) -> str:
        raw = (value or "").strip()
        if not raw:
            return raw
        if kind == "assessmentName":
            return self.assessment_name(raw)
        if kind == "level":
            m = _LEVEL.match(raw)
            return f"第 {m.group(1)} 级" if m else raw
        if kind == "mode":
            m = _MODE_CODE.search(raw)
            zh = self.terms.get("mode", {}).get(m.group(1)) if m else None
            return f"{zh}（{m.group(1)}）" if zh else raw
        if kind == "period":
            return self._period(raw)
        return self.terms.get(kind, {}).get(raw, raw)

    def _period(self, raw: str) -> str:
        periods = self.terms.get("period", {})
        body, suffix = raw, ""
        if body.endswith(" - alternate"):
            body, suffix = body[: -len(" - alternate")], "（替代开课）"
        if body in periods:
            return periods[body] + suffix
        if " to " in body:
            parts = [periods.get(p.strip()) for p in body.split(" to ")]
            if all(parts):
                return " 至 ".join(parts) + suffix
        return raw

    def assessment_name(self, raw: str) -> str:
        types = self.terms.get("assessmentType", {})
        m = _NUMBERED_ASSESSMENT.match(raw)
        if not m:
            return types.get(raw, raw)
        zh = types.get(m.group(2).strip())
        return f"第 {m.group(1)} 项 · {zh}" if zh else raw


class Cached:
    """Reload the i18n files when the sync job replaces them."""

    def __init__(self, directory: Path):
        self.directory = directory
        self._stamp: tuple[float, float] | None = None
        self._value = HubI18n.empty()

    def get(self) -> HubI18n:
        try:
            stamp = ((self.directory / "index.ts").stat().st_mtime,
                     (self.directory / "handbook-terms.ts").stat().st_mtime)
        except OSError:
            stamp = None
        if stamp != self._stamp:
            self._stamp = stamp
            self._value = HubI18n.load(self.directory) if stamp else HubI18n.empty()
        return self._value
