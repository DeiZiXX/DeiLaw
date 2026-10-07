from __future__ import annotations

import json
import re


class GroundingValidator:
    """Validate model output against the exact candidate articles supplied to it."""

    ARTICLE_REF_RE = re.compile(r"(?:(?:статья|ст\.)\s*)?(\d+(?:\.\d+)*)", re.I)
    DANGEROUS_ACTION_RE = re.compile(r"оруж|огнестр|стрел|открыть огонь|примен(?:ить|ение) силы|спецсред", re.I)

    def __init__(self, candidates, mode="general"):
        self.candidates = list(candidates or [])
        self.mode = str(mode or "general")
        self.by_number = {}
        for c in self.candidates:
            number = self._norm_number(c.get("article_number"))
            self.by_number.setdefault(number, []).append(c)

    @staticmethod
    def _norm_number(value):
        return str(value or "").strip().rstrip(".")

    @staticmethod
    def _norm_text(value):
        return " ".join(re.findall(r"[а-яa-z0-9]+", str(value or "").lower().replace("ё", "е")))

    @classmethod
    def law_code(cls, title):
        t = cls._norm_text(title)
        if "административ" in t and "кодекс" in t:
            return "коап"
        if "уголовно процесс" in t:
            return "упк"
        if "уголовный кодекс" in t:
            return "ук"
        if "правила дорожного движения" in t or t == "пдд":
            return "пдд"
        if "процессуальный кодекс" in t:
            return "пк"
        if "трудовой кодекс" in t:
            return "тк"
        return t

    def resolve(self, document, article):
        number = self._norm_number(article)
        matches = self.by_number.get(number, [])
        if not matches:
            return None
        if len(matches) == 1 and not str(document or "").strip():
            return matches[0]
        wanted = self.law_code(document)
        for candidate in matches:
            c_code = self.law_code(candidate.get("law_title", ""))
            if wanted and (wanted == c_code or wanted in c_code or c_code in wanted):
                return candidate
        if len(matches) == 1:
            return matches[0]
        return None

    @staticmethod
    def _numbers(text):
        return set(re.findall(r"\d+(?:[.,]\d+)?", str(text or "")))

    def _responsibility_supported(self, item, source):
        text = str(item.get("text", "")).strip()
        if not text:
            return False
        source_text = str(source.get("content", ""))
        claimed = self._numbers(text)
        available = self._numbers(source_text)
        if claimed and not claimed.issubset(available):
            return False
        return True

    def _action_supported(self, item, source):
        text = str(item.get("text", "")).strip()
        if not text:
            return False
        if self.DANGEROUS_ACTION_RE.search(text):
            source_text = str(source.get("content", ""))
            if not self.DANGEROUS_ACTION_RE.search(source_text):
                return False
        return True

    def _validate_sourced_list(self, items, kind):
        valid = []
        for raw in items or []:
            if not isinstance(raw, dict):
                continue
            source = self.resolve(raw.get("document"), raw.get("article"))
            if source is None:
                continue
            item = dict(raw)
            item["document"] = source.get("law_title", "")
            item["article"] = str(source.get("article_number", ""))
            code = self.law_code(source.get("law_title", ""))

            # In the qualification mode a civilian can be charged only under
            # UK or KoAP. PDD/PK/FZ/etc. can explain the duty, authority or
            # procedure, but must never be rendered as an imputed offence.
            if self.mode == "qualification" and kind in {"primary", "responsibility"}:
                if code not in {"ук", "коап"}:
                    continue

            if kind == "responsibility" and not self._responsibility_supported(item, source):
                continue
            if kind == "actions" and not self._action_supported(item, source):
                continue
            valid.append(item)
        return valid


    @staticmethod
    def _primary_reason_for_candidate(source):
        reason = str(source.get("_strong_issue_reason") or "").strip()
        if reason:
            return reason
        tags = list(source.get("_strong_issue_tags") or [])
        labels = {
            "failure_to_stop": "эпизод: игнорирование требования об остановке",
            "oncoming_lane": "эпизод: встречная полоса",
            "collision_damage": "эпизод: повреждение дорожной инфраструктуры",
            "leave_crash_scene": "эпизод: оставление места ДТП",
            "noncompliance": "эпизод: неповиновение законному требованию",
        }
        return "; ".join(labels.get(x, x) for x in tags) or "прямое совпадение с фактическим эпизодом"

    @staticmethod
    def _extract_sanction(source):
        text = str(source.get("content") or "").strip()
        if not text:
            return ""
        normalized = text.replace("\r\n", "\n")
        match = re.search(r"(?is)(влеч[её]т\s+.+)$", normalized)
        if not match:
            return ""
        sanction = match.group(1).strip()
        # Keep only the first sanction paragraph / sentence block.
        sanction = re.split(r"\n\s*\n|(?=\n(?:Статья|Глава|РАЗДЕЛ)\b)", sanction, maxsplit=1, flags=re.I)[0]
        sanction = " ".join(sanction.split())
        return sanction[:700]

    def _ensure_strong_qualification_coverage(self, result):
        if self.mode != "qualification":
            return result

        existing_primary = {
            (self.law_code(x.get("document", "")), self._norm_number(x.get("article")))
            for x in result.get("primary") or []
        }
        existing_resp = {
            (self.law_code(x.get("document", "")), self._norm_number(x.get("article")))
            for x in result.get("responsibility") or []
        }

        strong_sources = []
        seen = set()
        for source in self.candidates:
            if not source.get("_strong_issue_tags"):
                continue
            code = self.law_code(source.get("law_title", ""))
            if code not in {"ук", "коап"}:
                continue
            key = (code, self._norm_number(source.get("article_number")))
            if key in seen:
                continue
            seen.add(key)
            strong_sources.append(source)

        for source in strong_sources:
            code = self.law_code(source.get("law_title", ""))
            number = self._norm_number(source.get("article_number"))
            key = (code, number)
            if key not in existing_primary:
                result.setdefault("primary", []).append({
                    "document": source.get("law_title", ""),
                    "article": number,
                    "reason": self._primary_reason_for_candidate(source),
                })
                existing_primary.add(key)

            if key not in existing_resp:
                sanction = self._extract_sanction(source)
                if sanction:
                    result.setdefault("responsibility", []).append({
                        "document": source.get("law_title", ""),
                        "article": number,
                        "text": sanction,
                    })
                    existing_resp.add(key)

        return result

    def validate(self, payload):
        if not isinstance(payload, dict):
            payload = {}
        result = {
            "summary": str(payload.get("summary", "")).strip(),
            "primary": self._validate_sourced_list(payload.get("primary"), "primary"),
            "additional": self._validate_sourced_list(payload.get("additional"), "additional"),
            "responsibility": self._validate_sourced_list(payload.get("responsibility"), "responsibility"),
            "actions": self._validate_sourced_list(payload.get("actions"), "actions"),
            "clarifications": [str(x).strip() for x in (payload.get("clarifications") or []) if str(x).strip()],
            "confidence": str(payload.get("confidence", "low")).strip().lower(),
        }
        result = self._ensure_strong_qualification_coverage(result)
        if result["confidence"] not in {"high", "medium", "low"}:
            result["confidence"] = "low"
        if not result["primary"]:
            result["confidence"] = "low"
            if not result["summary"]:
                if self.mode == "qualification":
                    result["summary"] = "По переданным нормам УК/КоАП состав нарушения надёжно не подтверждён."
                elif self.mode == "authority":
                    result["summary"] = "В переданных нормах не удалось надёжно подтвердить прямое правовое основание."
                else:
                    result["summary"] = "В переданных нормах не удалось надёжно подтвердить основной вывод."
        return result

    def render(self, payload):
        if self.mode == "article_lookup":
            return self._render_article(payload)
        if self.mode == "qualification":
            return self._render_qualification(payload)
        if self.mode == "authority":
            return self._render_authority(payload)
        return self._render_general(payload)

    @staticmethod
    def _append_items(lines, items, relation_label):
        for item in items or []:
            lines.append(f"• {item['document']} — статья {item['article']}")
            reason = str(item.get("reason", "")).strip()
            if reason:
                lines.append(f"  {relation_label}: {reason}")

    @staticmethod
    def _short_law_name(document):
        code = GroundingValidator.law_code(document)
        labels = {
            "ук": "УК",
            "коап": "КоАП",
            "упк": "УПК",
            "пк": "ПК",
            "пдд": "ПДД",
            "тк": "ТК",
        }
        return labels.get(code, str(document or "").strip() or "Норма")

    @classmethod
    def _article_label(cls, item):
        return f"Статья {str(item.get('article', '')).strip()} {cls._short_law_name(item.get('document', ''))}".strip()

    @classmethod
    def _responsibility_map(cls, payload):
        out = {}
        for item in payload.get("responsibility") or []:
            key = (cls.law_code(item.get("document", "")), cls._norm_number(item.get("article")))
            text = str(item.get("text", "")).strip()
            if text:
                out[key] = text
        return out

    def _render_article(self, payload):
        primary = payload.get("primary") or []
        responsibility = self._responsibility_map(payload)
        lines = ["📖 ЮРИДИЧЕСКАЯ СПРАВКА", ""]

        if primary:
            for index, item in enumerate(primary, 1):
                label = self._article_label(item)
                lines.append(label if len(primary) == 1 else f"{index}. {label}")
                reason = str(item.get("reason", "")).strip()
                if reason:
                    lines.append(f"Суть: {reason}")
                key = (self.law_code(item.get("document", "")), self._norm_number(item.get("article")))
                sanction = responsibility.get(key)
                if sanction:
                    lines.append(f"⚖ Что грозит: {sanction}")
                else:
                    lines.append("⚖ Что грозит: санкция в тексте переданной статьи не извлечена.")
                if index != len(primary):
                    lines.append("")
        else:
            lines.append("Точная статья среди переданных источников не подтверждена.")

        summary = str(payload.get("summary") or "").strip()
        if summary:
            lines.extend(["", "Коротко", summary])

        additional = payload.get("additional") or []
        if additional:
            lines.extend(["", "📚 Связанные нормы"])
            for item in additional:
                lines.append(f"• {self._article_label(item)}")
                reason = str(item.get("reason", "")).strip()
                if reason:
                    lines.append(f"  {reason}")
        return "\n".join(lines).strip()

    def _render_qualification(self, payload):
        primary = payload.get("primary") or []
        responsibility = self._responsibility_map(payload)
        lines = ["⚖ ЮРИДИЧЕСКИЙ РАЗБОР", ""]

        summary = str(payload.get("summary") or "").strip()
        if summary:
            lines.extend(["Краткий вывод", summary, ""])

        lines.append("🚨 ВЫЯВЛЕННЫЕ НАРУШЕНИЯ")
        if primary:
            for index, item in enumerate(primary, 1):
                lines.append("")
                lines.append(f"{index}. {self._article_label(item)}")
                reason = str(item.get("reason", "")).strip()
                if reason:
                    lines.append(f"Что нарушено: {reason}")
                key = (self.law_code(item.get("document", "")), self._norm_number(item.get("article")))
                sanction = responsibility.get(key)
                if sanction:
                    lines.append(f"Наказание: {sanction}")
                else:
                    lines.append("Наказание: санкция из переданного текста статьи не извлечена.")
        else:
            lines.append("• Подтверждённых составов УК/КоАП не установлено.")

        additional = payload.get("additional") or []
        if additional:
            lines.extend(["", "📚 ДОПОЛНИТЕЛЬНЫЕ ПРАВОВЫЕ НОРМЫ"])
            for item in additional:
                lines.append(f"• {self._article_label(item)}")
                reason = str(item.get("reason", "")).strip()
                if reason:
                    lines.append(f"  {reason}")

        actions = payload.get("actions") or []
        lines.extend(["", "👮 ЧТО ДЕЛАТЬ СОТРУДНИКУ"])
        if actions:
            for item in actions:
                action = str(item.get("text", "")).strip()
                lines.append(f"• {action}")
                if item.get("article"):
                    lines.append(f"  Основание: {self._article_label(item)}")
        else:
            lines.append("• Отдельный порядок действий из переданных норм не подтверждён.")

        clarifications = payload.get("clarifications") or []
        if clarifications:
            lines.extend(["", "❓ ЧТО НУЖНО УТОЧНИТЬ"])
            lines.extend(f"• {x}" for x in clarifications)

        confidence = str(payload.get("confidence") or "").lower()
        confidence_labels = {"high": "высокая", "medium": "средняя", "low": "низкая"}
        if confidence in confidence_labels:
            lines.extend(["", f"Уверенность разбора: {confidence_labels[confidence]}"])
        return "\n".join(lines).strip()

    def _render_authority(self, payload):
        lines = ["⚖ ПРАВОВОЕ ЗАКЛЮЧЕНИЕ", ""]
        summary = str(payload.get("summary") or "").strip()
        lines.extend(["Короткий ответ", summary or "Прямой вывод не подтверждён.", ""])

        primary = payload.get("primary") or []
        lines.append("📌 ОСНОВНОЕ ПРАВОВОЕ ОСНОВАНИЕ")
        if primary:
            for index, item in enumerate(primary, 1):
                prefix = f"{index}. " if len(primary) > 1 else ""
                lines.append(f"{prefix}{self._article_label(item)}")
                reason = str(item.get("reason", "")).strip()
                if reason:
                    lines.append(f"Почему применяется: {reason}")
        else:
            lines.append("• Прямая разрешающая/обязывающая норма среди источников не подтверждена.")

        actions = payload.get("actions") or []
        lines.extend(["", "👮 ПОРЯДОК ДЕЙСТВИЙ СОТРУДНИКА"])
        if actions:
            for item in actions:
                action = str(item.get("text", "")).strip()
                lines.append(f"• {action}")
                if item.get("article"):
                    lines.append(f"  Основание: {self._article_label(item)}")
        else:
            lines.append("• Отдельный порядок действий из переданных норм не извлечён.")

        additional = payload.get("additional") or []
        if additional:
            lines.extend(["", "📚 ДОПОЛНИТЕЛЬНЫЕ НОРМЫ / УСЛОВИЯ"])
            for item in additional:
                lines.append(f"• {self._article_label(item)}")
                reason = str(item.get("reason", "")).strip()
                if reason:
                    lines.append(f"  {reason}")

        responsibility = payload.get("responsibility") or []
        if responsibility:
            lines.extend(["", "🚨 ОТВЕТСТВЕННОСТЬ ЗА НЕВЫПОЛНЕНИЕ"])
            for item in responsibility:
                lines.append(f"• {self._article_label(item)}")
                text = str(item.get("text", "")).strip()
                if text:
                    lines.append(f"  {text}")

        clarifications = payload.get("clarifications") or []
        if clarifications:
            lines.extend(["", "❓ ЧТО НУЖНО УТОЧНИТЬ"])
            lines.extend(f"• {x}" for x in clarifications)
        return "\n".join(lines).strip()

    def _render_general(self, payload):
        lines = ["⚖ ЮРИДИЧЕСКАЯ КОНСУЛЬТАЦИЯ", ""]
        summary = str(payload.get("summary") or "").strip()
        lines.extend(["Краткий ответ", summary or "Нет уверенного вывода."])

        primary = payload.get("primary") or []
        if primary:
            lines.extend(["", "📌 ОСНОВНЫЕ НОРМЫ"])
            for item in primary:
                lines.append(f"• {self._article_label(item)}")
                reason = str(item.get("reason", "")).strip()
                if reason:
                    lines.append(f"  {reason}")

        responsibility = payload.get("responsibility") or []
        if responsibility:
            lines.extend(["", "🚨 ОТВЕТСТВЕННОСТЬ"])
            for item in responsibility:
                lines.append(f"• {self._article_label(item)}: {str(item.get('text', '')).strip()}")

        actions = payload.get("actions") or []
        if actions:
            lines.extend(["", "👮 ДЕЙСТВИЯ СОТРУДНИКА"])
            for item in actions:
                lines.append(f"• {str(item.get('text', '')).strip()}")
                if item.get("article"):
                    lines.append(f"  Основание: {self._article_label(item)}")

        additional = payload.get("additional") or []
        if additional:
            lines.extend(["", "📚 ДОПОЛНИТЕЛЬНЫЕ НОРМЫ"])
            for item in additional:
                lines.append(f"• {self._article_label(item)}")
                reason = str(item.get("reason", "")).strip()
                if reason:
                    lines.append(f"  {reason}")
        return "\n".join(lines).strip()

    @staticmethod
    def parse_json(text):
        raw = str(text or "").strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
            raw = re.sub(r"\s*```$", "", raw)
        try:
            return json.loads(raw)
        except Exception:
            match = re.search(r"\{.*\}", raw, flags=re.S)
            if match:
                try:
                    return json.loads(match.group(0))
                except Exception:
                    pass
        return {}
