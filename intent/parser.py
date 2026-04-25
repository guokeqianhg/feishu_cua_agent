from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from core.schemas import Product, TestCase


IntentName = Literal[
    "im_search_only",
    "im_send_message",
    "docs_create_doc",
    "docs_open_smoke",
    "calendar_create_event",
    "unknown",
]


class ParsedIntent(BaseModel):
    intent: IntentName = "unknown"
    product: Product = "unknown"
    plan_template: str | None = None
    target: str | None = None
    message: str | None = None
    search_text: str | None = None
    doc_title: str | None = None
    doc_body: str | None = None
    event_title: str | None = None
    event_time: str | None = None
    attendees: list[str] = Field(default_factory=list)
    safety_guard_required: bool = False
    no_send: bool = False
    confidence: float = 0.0
    reason: str = ""
    warnings: list[str] = Field(default_factory=list)

    def to_metadata(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "parsed_intent": self.intent,
            "intent_confidence": self.confidence,
            "intent_reason": self.reason,
            "safety_guard_required": self.safety_guard_required,
        }
        if self.plan_template:
            data["plan_template"] = self.plan_template
        if self.target:
            data["target"] = self.target
        if self.message:
            data["message"] = self.message
        if self.search_text:
            data["search_text"] = self.search_text
        if self.doc_title:
            data["doc_title"] = self.doc_title
        if self.doc_body:
            data["doc_body"] = self.doc_body
        if self.event_title:
            data["event_title"] = self.event_title
        if self.event_time:
            data["event_time"] = self.event_time
        if self.attendees:
            data["attendees"] = self.attendees
        if self.no_send:
            data["safe_smoke"] = True
        if self.warnings:
            data["intent_warnings"] = self.warnings
        return data


def parse_instruction(instruction: str, product_hint: str = "unknown") -> ParsedIntent:
    text = _normalize(instruction)
    product = _infer_product(text, product_hint)
    no_send = _has_no_send_guard(text)

    if product == "docs" and _is_doc_create_instruction(text):
        title, body = _extract_doc_content(text)
        warnings: list[str] = []
        if not title:
            warnings.append("Document title was not confidently parsed; guarded workflow will use a timestamped smoke title.")
        if not body:
            warnings.append("Document body was not confidently parsed; guarded workflow will use a harmless smoke body.")
        return ParsedIntent(
            intent="docs_create_doc",
            product="docs",
            plan_template="docs_create_doc_guarded",
            doc_title=title,
            doc_body=body,
            safety_guard_required=True,
            confidence=0.84 if title or body else 0.64,
            reason="Detected a Docs create-document instruction; routed to guarded document creation workflow.",
            warnings=warnings,
        )

    if product == "calendar" and _is_calendar_create_instruction(text):
        event_title, event_time, attendees = _extract_calendar_event(text)
        warnings = []
        if not event_title:
            warnings.append("Calendar event title was not confidently parsed; guarded workflow will use a smoke meeting title.")
        if not event_time:
            warnings.append("Calendar event time was not confidently parsed; guarded workflow will keep the time phrase empty.")
        return ParsedIntent(
            intent="calendar_create_event",
            product="calendar",
            plan_template="calendar_create_event_guarded",
            event_title=event_title,
            event_time=event_time,
            attendees=attendees,
            safety_guard_required=True,
            confidence=0.84 if event_title or event_time else 0.62,
            reason="Detected a Calendar create-event instruction; routed to guarded calendar creation workflow.",
            warnings=warnings,
        )

    if product == "docs":
        if _mentions_docs(text) and (_contains_any(text, ["打开", "进入", "切换", "查看", "open"]) or no_send):
            return ParsedIntent(
                intent="docs_open_smoke",
                product="docs",
                plan_template="docs_open_smoke",
                no_send=True,
                confidence=0.86,
                reason="Detected a non-mutating Docs open/observe instruction.",
            )

    if product == "im":
        if no_send or _contains_any(text, ["只搜索", "仅搜索", "不要发送", "不发送", "不发消息", "no send"]):
            target = _extract_search_target(text)
            return ParsedIntent(
                intent="im_search_only",
                product="im",
                plan_template="im_search_only",
                target=target,
                search_text=target or "harmless-smoke-test",
                no_send=True,
                confidence=0.84,
                reason="Detected an IM search-only instruction with no-send safety wording.",
            )

        if _contains_any(text, ["发送", "发一条", "发消息", "send"]):
            target = _extract_im_target(text)
            message = _extract_message(text)
            warnings: list[str] = []
            if not target:
                warnings.append("Target chat was not confidently parsed; guarded workflow will use configured/default target.")
            if not message:
                warnings.append("Message text was not confidently parsed; guarded workflow will use default smoke message.")
            return ParsedIntent(
                intent="im_send_message",
                product="im",
                plan_template="im_send_message_guarded",
                target=target,
                message=message,
                safety_guard_required=True,
                confidence=0.82 if target or message else 0.62,
                reason="Detected an IM send-message instruction; routed to guarded send workflow.",
                warnings=warnings,
            )

        if _contains_any(text, ["搜索", "查找", "find", "search"]):
            target = _extract_search_target(text)
            return ParsedIntent(
                intent="im_search_only",
                product="im",
                plan_template="im_search_only",
                target=target,
                search_text=target or "harmless-smoke-test",
                no_send=True,
                confidence=0.72,
                reason="Detected an IM search instruction; defaulting to safe search-only workflow.",
            )

    return ParsedIntent(
        intent="unknown",
        product=product,
        confidence=0.1,
        reason="No high-confidence local intent rule matched; fallback planner may handle it.",
    )


def enrich_case_with_intent(case: TestCase) -> TestCase:
    if case.metadata.get("plan_template"):
        return case
    parsed = parse_instruction(case.instruction, case.product)
    if parsed.intent == "unknown":
        metadata = {**case.metadata, "parsed_intent": "unknown", "intent_reason": parsed.reason}
        return case.model_copy(update={"metadata": metadata})

    metadata = {**case.metadata, **parsed.to_metadata()}
    product = parsed.product if case.product == "unknown" else case.product
    expected = case.expected_result or _expected_result(parsed)
    name = case.name
    if name in {"CLI natural-language run", "Manual natural-language run"}:
        name = _case_name(parsed)
    return case.model_copy(update={"product": product, "expected_result": expected, "metadata": metadata, "name": name})


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _infer_product(text: str, hint: str) -> Product:
    if hint in {"im", "docs", "calendar", "base", "vc", "mail"}:
        return hint  # type: ignore[return-value]
    if _mentions_docs(text):
        return "docs"
    if _contains_any(text, ["im", "消息", "聊天", "群", "联系人", "发送", "发消息", "send", "search"]):
        return "im"
    if _contains_any(text, ["日历", "会议", "calendar", "meeting"]):
        return "calendar"
    return "unknown"


def _mentions_docs(text: str) -> bool:
    return _contains_any(text, ["云文档", "文档", "docs", "doc", "知识库"])


def _has_no_send_guard(text: str) -> bool:
    return _contains_any(text, ["不发送", "不要发送", "不发消息", "不要发", "只观察", "只搜索", "no send", "do not send"])


def _contains_any(text: str, items: list[str]) -> bool:
    raw = text.lower()
    return any(item.lower() in raw for item in items)


def _infer_product(text: str, hint: str) -> Product:
    if hint in {"im", "docs", "calendar", "base", "vc", "mail"}:
        return hint  # type: ignore[return-value]
    if _mentions_docs(text):
        return "docs"
    if _contains_any(text, ["日历", "会议", "日程", "calendar", "meeting", "event"]):
        return "calendar"
    if _contains_any(text, ["im", "消息", "聊天", "群", "联系人", "发送", "发消息", "send", "search", "搜索"]):
        return "im"
    return "unknown"


def _mentions_docs(text: str) -> bool:
    return _contains_any(text, ["云文档", "文档", "docs", "doc", "知识库"])


def _has_no_send_guard(text: str) -> bool:
    return _contains_any(text, ["不发送", "不要发送", "不发消息", "不要发", "只观察", "只搜索", "no send", "do not send"])


def _extract_im_target(text: str) -> str | None:
    patterns = [
        r"(?:给|向|发给)\s*[\"'“”‘’「『]?(.+?)[\"'“”‘’」』]?\s*(?:发送|发一条|发消息|发|说)",
        r"在\s*[\"'“”‘’「『]?([^，,。；;：:\s\"'“”‘’」』]+(?:群|联系人|测试群)?)\s*(?:中|里)?\s*(?:发送|发)",
        r"(?:搜索|查找)\s*[\"'“”‘’「『]?([^，,。；;：:\s\"'“”‘’」』]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return _strip_punctuation(match.group(1))
    return None


def _extract_search_target(text: str) -> str | None:
    patterns = [
        r"(?:搜索|查找|找到|find|search)\s*[\"'“”‘’「『]?([^，,。；;：:\s\"'“”‘’」』]+)",
        r"(?:打开|进入)\s*[\"'“”‘’「『]?([^，,。；;：:\s\"'“”‘’」』]+)\s*(?:聊天|会话|群)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return _strip_punctuation(match.group(1))
    return None


def _extract_message(text: str) -> str | None:
    quoted = re.findall(r"[\"'“”‘’「『](.*?)[\"'“”‘’」』]", text)
    if quoted:
        return quoted[-1].strip()
    patterns = [
        r"(?:消息|内容|message)\s*[：:]\s*(.+)$",
        r"(?:发送|发一条|发消息|send)\s*(?:一条)?\s*(?:消息)?\s*[：:]?\s*(.+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        candidate = _strip_leading_target_phrase(match.group(1).strip())
        if candidate:
            return candidate
    return None


def _strip_leading_target_phrase(text: str) -> str:
    text = re.sub(r"^(?:给|向|发给)\s*[^，,。；;：:]+\s*[，,。；;：:]?\s*", "", text)
    text = re.sub(r"^到\s*[^，,。；;：:]+\s*[，,。；;：:]?\s*", "", text)
    return _strip_punctuation(text)


def _strip_punctuation(text: str) -> str:
    cleaned = (text or "").strip().strip(" ，,。；;：:\"'“”‘’「」『』")
    cleaned = re.sub(r"(?:一条)?消息$", "", cleaned).strip()
    return cleaned


def _strip_common(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = text.strip().strip(" \t\r\n：:，,。；;、\"'“”‘’「」《》")
    return cleaned or None


def _is_doc_create_instruction(text: str) -> bool:
    if not _mentions_docs(text):
        return False
    return _contains_any(text, ["创建", "新建", "写一篇", "写入", "输入", "生成", "create", "new"])


def _extract_doc_content(text: str) -> tuple[str | None, str | None]:
    title = None
    for pattern in [
        r"(?:标题(?:为|是|叫|：|:)|题目(?:为|是|叫|：|:)|名为|叫做)\s*[\"'“”‘’「」《》]?([^，。；;\n\"'“”‘’「」《》]+)",
        r"(?:创建|新建)(?:一个|一篇)?(?:测试)?(?:云文档|文档)?\s*[\"'“”‘’「」《》]?([^，。；;\n\"'“”‘’「」《》]+)",
    ]:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            title = _strip_common(match.group(1))
            break

    body = None
    for pattern in [
        r"(?:正文|内容|文档内容|body)\s*(?:为|是|写入|输入|：|:)?\s*(.+)$",
        r"(?:写入|输入)\s*(.+)$",
    ]:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            body = _strip_common(match.group(1))
            break

    quoted = re.findall(r"[\"“‘「《](.*?)[\"”’」》]", text)
    if quoted:
        if title is None:
            title = _strip_common(quoted[0])
        if len(quoted) > 1 and body is None:
            body = _strip_common(quoted[-1])
    return title, body


def _is_calendar_create_instruction(text: str) -> bool:
    if not _contains_any(text, ["日历", "会议", "日程", "calendar", "meeting", "event"]):
        return False
    return _contains_any(text, ["创建", "新建", "安排", "预约", "保存", "create", "new", "schedule"])


def _extract_calendar_event(text: str) -> tuple[str | None, str | None, list[str]]:
    title = None
    for pattern in [
        r"(?:会议|日程)(?:标题|名称)?(?:为|是|叫|：|:)?\s*[\"'“”‘’「」《》]?([^，。；;\n\"'“”‘’「」《》]+)",
        r"(?:标题|名称)(?:为|是|叫|：|:)\s*[\"'“”‘’「」《》]?([^，。；;\n\"'“”‘’「」《》]+)",
    ]:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            title = _strip_common(match.group(1))
            break

    time_phrase = None
    for pattern in [
        r"(?:时间|在|安排到|安排在)(?:为|是|：|:)?\s*([^，。；;\n]+)",
        r"((?:今天|明天|后天|下周|周[一二三四五六日天]|星期[一二三四五六日天]|\d{1,2}[月/-]\d{1,2}[日号]?).{0,18}(?:\d{1,2}[:：]\d{2}|\d{1,2}点|上午|下午|晚上|中午).{0,18})",
    ]:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            time_phrase = _strip_common(match.group(1))
            break

    attendees: list[str] = []
    attendee_match = re.search(r"(?:参会人|参与人|邀请|参会人列表)\s*(?:为|是|：|:)?\s*[\"'“”‘’「」《》]?(.+?)(?:[\"”’」》]?(?:参加|参会|开会)|$)", text)
    if attendee_match:
        attendees = [
            item
            for item in (_strip_common(part) for part in re.split(r"[、,，和\s]+", attendee_match.group(1)))
            if item
        ]
    return title, time_phrase, attendees


def _expected_result(intent: ParsedIntent) -> str:
    if intent.intent == "im_send_message":
        return "The guarded message is sent only to the explicitly allowed test chat."
    if intent.intent == "im_search_only":
        return "The IM search input is focused and no chat message is sent."
    if intent.intent == "docs_create_doc":
        return "A guarded test document is created only when CUA_LARK_ALLOW_DOC_CREATE=true, and its title/body are visible."
    if intent.intent == "docs_open_smoke":
        return "The Docs entry or workspace is visible and no document is created or modified."
    if intent.intent == "calendar_create_event":
        return "A guarded test calendar event is created only when CUA_LARK_ALLOW_CALENDAR_CREATE=true, and the event is visible."
    return ""


def _case_name(intent: ParsedIntent) -> str:
    if intent.intent == "im_send_message":
        return "Natural language IM guarded send"
    if intent.intent == "im_search_only":
        return "Natural language IM safe search"
    if intent.intent == "docs_create_doc":
        return "Natural language Docs guarded create"
    if intent.intent == "docs_open_smoke":
        return "Natural language Docs safe open"
    if intent.intent == "calendar_create_event":
        return "Natural language Calendar guarded create"
    return "CLI natural-language run"
