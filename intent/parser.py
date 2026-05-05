from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from core.schemas import Product, TestCase


IntentName = Literal[
    "im_search_only",
    "im_send_message",
    "im_send_image",
    "im_create_group",
    "im_mention_user",
    "im_search_messages",
    "im_emoji_reaction",
    "docs_create_doc",
    "docs_edit_text",
    "docs_rich_edit",
    "docs_share_doc",
    "docs_open_smoke",
    "calendar_create_event",
    "calendar_invite_attendee",
    "calendar_modify_event_time",
    "calendar_view_busy_free",
    "vc_start_meeting",
    "vc_join_meeting",
    "vc_toggle_devices",
    "unknown",
]


class ParsedIntent(BaseModel):
    intent: IntentName = "unknown"
    product: Product = "unknown"
    plan_template: str | None = None
    im_action: str | None = None
    target: str | None = None
    message: str | None = None
    search_text: str | None = None
    image_path: str | None = None
    mention_user: str | None = None
    group_name: str | None = None
    group_members: list[str] = Field(default_factory=list)
    emoji_name: str | None = None
    doc_title: str | None = None
    doc_body: str | None = None
    doc_heading: str | None = None
    doc_list_items: list[str] = Field(default_factory=list)
    share_recipient: str | None = None
    event_title: str | None = None
    event_time: str | None = None
    new_event_time: str | None = None
    calendar_action: str | None = None
    attendees: list[str] = Field(default_factory=list)
    vc_action: str | None = None
    meeting_id: str | None = None
    meeting_title: str | None = None
    desired_camera_on: bool | None = None
    desired_mic_on: bool | None = None
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
        for key in (
            "plan_template",
            "im_action",
            "target",
            "message",
            "search_text",
            "image_path",
            "mention_user",
            "group_name",
            "emoji_name",
            "doc_title",
            "doc_body",
            "doc_heading",
            "share_recipient",
            "event_title",
            "event_time",
            "new_event_time",
            "calendar_action",
            "vc_action",
            "meeting_id",
            "meeting_title",
        ):
            value = getattr(self, key)
            if value:
                data[key] = value
        if self.desired_camera_on is not None:
            data["desired_camera_on"] = self.desired_camera_on
        if self.desired_mic_on is not None:
            data["desired_mic_on"] = self.desired_mic_on
        if self.doc_list_items:
            data["doc_list_items"] = self.doc_list_items
        if self.group_members:
            data["group_members"] = self.group_members
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

    if product == "docs" and _is_doc_share_instruction(text):
        title, body = _extract_doc_content(text)
        recipient = _extract_share_recipient(text) or "李新元"
        return ParsedIntent(
            intent="docs_share_doc",
            product="docs",
            plan_template="docs_share_doc_guarded",
            doc_title=title,
            doc_body=body,
            share_recipient=recipient,
            safety_guard_required=True,
            confidence=0.84,
            reason="Detected a Docs share instruction; routed to guarded document sharing workflow.",
        )

    if product == "docs" and _is_doc_rich_edit_instruction(text):
        title, body, heading, list_items = _extract_doc_rich_content(text)
        return ParsedIntent(
            intent="docs_rich_edit",
            product="docs",
            plan_template="docs_rich_edit_guarded",
            doc_title=title,
            doc_body=body,
            doc_heading=heading,
            doc_list_items=list_items,
            safety_guard_required=True,
            confidence=0.84 if heading or list_items else 0.68,
            reason="Detected a Docs heading/list editing instruction; routed to guarded rich-edit workflow.",
        )

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

    if product == "calendar" and _is_calendar_busy_free_instruction(text):
        attendee = _extract_calendar_people(text) or ["李新元"]
        event_title, event_time, _attendees = _extract_calendar_event(text)
        event_time = _extract_calendar_busy_free_time(text) or event_time
        return ParsedIntent(
            intent="calendar_view_busy_free",
            product="calendar",
            plan_template="calendar_view_busy_free_guarded",
            calendar_action="view_busy_free",
            event_title=event_title,
            event_time=event_time,
            attendees=attendee,
            safety_guard_required=True,
            confidence=0.84,
            reason="Detected a Calendar busy/free lookup instruction.",
        )

    if product == "calendar" and _is_calendar_modify_time_instruction(text):
        event_title, event_time, attendees = _extract_calendar_event(text)
        new_event_time = _extract_new_event_time(text) or event_time
        return ParsedIntent(
            intent="calendar_modify_event_time",
            product="calendar",
            plan_template="calendar_modify_event_time_guarded",
            calendar_action="modify_time",
            event_title=event_title,
            event_time=event_time,
            new_event_time=new_event_time,
            attendees=attendees,
            safety_guard_required=True,
            confidence=0.8 if new_event_time else 0.62,
            reason="Detected a Calendar event-time modification instruction.",
        )

    if product == "calendar" and _is_calendar_invite_instruction(text):
        event_title, event_time, attendees = _extract_calendar_event(text)
        attendees = attendees or _extract_calendar_people(text) or ["李新元"]
        return ParsedIntent(
            intent="calendar_invite_attendee",
            product="calendar",
            plan_template="calendar_invite_attendee_guarded",
            calendar_action="invite_attendee",
            event_title=event_title,
            event_time=event_time,
            attendees=attendees,
            safety_guard_required=True,
            confidence=0.78,
            reason="Detected a Calendar invite-attendee instruction.",
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

    if product == "vc" and _is_vc_start_instruction(text):
        camera_on, mic_on = _extract_vc_device_intent(text)
        return ParsedIntent(
            intent="vc_start_meeting",
            product="vc",
            plan_template="vc_start_meeting_guarded",
            vc_action="start_meeting",
            meeting_title=_extract_vc_meeting_title(text),
            desired_camera_on=camera_on,
            desired_mic_on=mic_on,
            safety_guard_required=True,
            confidence=0.86,
            reason="Detected a VC start-meeting instruction.",
        )

    if product == "vc" and _is_vc_join_instruction(text):
        camera_on, mic_on = _extract_vc_device_intent(text)
        return ParsedIntent(
            intent="vc_join_meeting",
            product="vc",
            plan_template="vc_join_meeting_guarded",
            vc_action="join_meeting",
            meeting_id=_extract_vc_meeting_id(text) or "259427455",
            desired_camera_on=camera_on,
            desired_mic_on=mic_on,
            safety_guard_required=True,
            confidence=0.86,
            reason="Detected a VC join-meeting instruction.",
        )

    if product == "vc" and _is_vc_device_instruction(text):
        camera_on, mic_on = _extract_vc_device_intent(text)
        return ParsedIntent(
            intent="vc_toggle_devices",
            product="vc",
            plan_template="vc_toggle_devices_guarded",
            vc_action="toggle_devices",
            desired_camera_on=camera_on,
            desired_mic_on=mic_on,
            safety_guard_required=True,
            confidence=0.78,
            reason="Detected a VC camera/microphone device-control instruction.",
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
        return _parse_im_intent(text, no_send)

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


def _parse_im_intent(text: str, no_send: bool) -> ParsedIntent:
    if _contains_any(text, ["创建群", "新建群", "建群", "拉群", "创建群组", "create group"]) or re.search(r"创建.*群", text):
        members = _extract_people_list(text) or ["李新元"]
        group_name = _extract_title_value(text, entity_words=("群", "群组")) or _extract_named_value(text, ["群名", "群名称", "名称", "名字"])
        return ParsedIntent(
            intent="im_create_group",
            product="im",
            plan_template="im_create_group_guarded",
            im_action="create_group",
            group_name=group_name,
            group_members=members,
            safety_guard_required=True,
            confidence=0.86,
            reason="Detected an IM group creation instruction.",
        )

    if _contains_any(text, ["聊天记录", "消息记录", "历史消息", "搜索消息", "查找消息", "search history", "message history"]):
        search_text = _extract_search_text(text) or "hello from CUA"
        search_text = _strip_no_send_tail(search_text)
        target = _extract_im_target(text)
        return ParsedIntent(
            intent="im_search_messages",
            product="im",
            plan_template="im_search_messages_guarded",
            im_action="search_history",
            target=target,
            search_text=search_text,
            no_send=True,
            confidence=0.86,
            reason="Detected an IM message-history search instruction.",
        )

    if _contains_any(text, ["@", "艾特", "提及", "at ", "mention"]):
        mention_user = _extract_mention_user(text) or "李新元"
        target = _extract_im_target(text) or _extract_group_target(text) or "测试群"
        message = _extract_message(text) or f"@{mention_user} hello from CUA"
        return ParsedIntent(
            intent="im_mention_user",
            product="im",
            plan_template="im_mention_user_guarded",
            im_action="mention",
            target=target,
            mention_user=mention_user,
            message=message,
            safety_guard_required=True,
            confidence=0.84,
            reason="Detected an IM @ mention instruction.",
        )

    if _contains_any(text, ["图片", "照片", "截图", "image", "photo", "picture"]):
        target = _extract_im_target(text)
        message = _extract_message(text)
        if message and _normalize_text_for_route(message) in {"一张图片", "一张照片", "图片", "照片", "截图"}:
            message = None
        image_path = _extract_image_path(text)
        warnings: list[str] = []
        if not image_path:
            warnings.append("Image path was not parsed; workflow will use the configured/default test image fixture.")
        return ParsedIntent(
            intent="im_send_image",
            product="im",
            plan_template="im_send_image_guarded",
            im_action="send_image",
            target=target,
            message=message,
            image_path=image_path,
            safety_guard_required=True,
            confidence=0.84 if target else 0.68,
            reason="Detected an IM send-image instruction.",
            warnings=warnings,
        )

    if _contains_any(text, ["表情", "点赞", "reaction", "emoji", "回复表情", "表情回复"]):
        target = _extract_im_target(text) or _extract_group_target(text) or "测试群"
        search_text = _extract_search_text(text)
        emoji_name = _extract_emoji_name(text)
        return ParsedIntent(
            intent="im_emoji_reaction",
            product="im",
            plan_template="im_emoji_reaction_guarded",
            im_action="emoji_reaction",
            target=target,
            search_text=search_text,
            emoji_name=emoji_name or "点赞",
            safety_guard_required=True,
            confidence=0.8,
            reason="Detected an IM emoji reaction instruction.",
        )

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
            im_action="send_text",
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
        product="im",
        confidence=0.1,
        reason="No high-confidence IM intent rule matched.",
    )


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _infer_product(text: str, hint: str) -> Product:
    if hint in {"im", "docs", "calendar", "base", "vc", "mail"}:
        return hint  # type: ignore[return-value]
    if _contains_any(text, ["视频会议", "发起会议", "加入会议", "会议id", "会议ID", "会议号", "摄像头", "麦克风", "vc", "video meeting"]):
        return "vc"
    if "发起" in text and "会议" in text:
        return "vc"
    if _mentions_docs(text):
        return "docs"
    if _contains_any(text, ["日历", "会议", "日程", "calendar", "meeting", "event"]):
        return "calendar"
    if _contains_any(
        text,
        [
            "im",
            "消息",
            "聊天",
            "群",
            "联系人",
            "发送",
            "发消息",
            "搜索",
            "查找",
            "艾特",
            "提及",
            "图片",
            "表情",
            "send",
            "search",
        ],
    ):
        return "im"
    return "unknown"


def _mentions_docs(text: str) -> bool:
    return _contains_any(text, ["云文档", "文档", "docs", "doc", "知识库"])


def _has_no_send_guard(text: str) -> bool:
    return _contains_any(text, ["不发送", "不要发送", "不发消息", "不要发", "只观察", "只搜索", "no send", "do not send"])


def _contains_any(text: str, items: list[str]) -> bool:
    raw = text.lower()
    return any(item.lower() in raw for item in items)


def _extract_im_target(text: str) -> str | None:
    patterns = [
        r"(?:给|向|发给)\s*[\"'“”‘’「」『』]?(.+?)[\"'“”‘’「」『』]?\s*(?:发送|发一条|发消息|发图片|发照片|发截图|@|艾特|提及)",
        r"(?:在|到)\s*[\"'“”‘’「」『』]?([^，。；;、\s\"'“”‘’「」『』]+(?:群|联系人|测试群)?)[\"'“”‘’「」『』]?\s*(?:里|中)?\s*(?:发送|发|@|艾特|提及|搜索|查找)",
        r"(?:搜索|查找|打开|进入)\s*[\"'“”‘’「」『』]?([^，。；;、\s\"'“”‘’「」『』]+)[\"'“”‘’「」『』]?\s*(?:聊天|会话|群|联系人)?",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            candidate = _strip_punctuation(match.group(1))
            candidate = re.sub(r"(?:里|中)$", "", candidate).strip()
            if candidate and candidate not in {"消息记录", "聊天记录", "图片", "照片", "截图"}:
                return candidate
    return None


def _extract_group_target(text: str) -> str | None:
    match = re.search(r"[\"'“”‘’「」『』]?([^，。；;、\s\"'“”‘’「」『』]+群)[\"'“”‘’「」『』]?", text)
    if not match:
        return None
    candidate = _strip_punctuation(match.group(1))
    candidate = re.sub(r"^(?:在|到|给|向)", "", candidate).strip()
    return candidate or None


def _extract_search_target(text: str) -> str | None:
    typed_query = _extract_typed_search_query(text)
    if typed_query:
        return typed_query
    patterns = [
        r"(?:搜索|查找|找到|find|search)\s*[\"'“”‘’「」『』]?([^，。；;、\s\"'“”‘’「」『』]+)",
        r"(?:打开|进入)\s*[\"'“”‘’「」『』]?([^，。；;、\s\"'“”‘’「」『』]+)\s*(?:聊天|会话|群)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            candidate = _strip_punctuation(match.group(1))
            candidate = re.sub(r"^(?:艾特|提及|mention)", "", candidate, flags=re.IGNORECASE).strip()
            if _is_search_ui_label(candidate):
                continue
            return candidate or None
    return None


def _extract_typed_search_query(text: str) -> str | None:
    if not _contains_any(text, ["搜索框", "搜索栏", "搜索输入框", "search box", "search input"]):
        return None
    patterns = [
        r"(?:输入|键入|填入|录入|type|enter)\s*([\"'“”‘’「」『』])(.+?)([\"'“”‘’「」『』])",
        r"(?:输入|键入|填入|录入|type|enter)\s*[:：]?\s*([^，。；;、\s\"'“”‘’「」『』]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        if len(match.groups()) >= 3:
            if not _is_matching_quote(match.group(1), match.group(3)):
                continue
            candidate = match.group(2)
        else:
            candidate = match.group(1)
        candidate = _strip_punctuation(candidate)
        if candidate and not _is_search_ui_label(candidate):
            return candidate
    return None


def _is_search_ui_label(candidate: str | None) -> bool:
    normalized = re.sub(r"\s+", "", candidate or "").lower()
    return normalized in {"框", "搜索框", "搜索栏", "搜索输入框", "searchbox", "searchinput"}


def _extract_search_text(text: str) -> str | None:
    named = _extract_named_value(text, ["关键词", "关键字", "搜索内容", "搜索", "查找"])
    if named:
        return named
    quoted = _quoted_items(text)
    if quoted:
        return quoted[-1]
    match = re.search(r"(?:搜索|查找)(?:聊天记录|消息记录|消息|历史消息)?\s*[:：]?\s*(.+)$", text, re.IGNORECASE)
    if match:
        return _strip_punctuation(match.group(1))
    return None


def _strip_no_send_tail(text: str) -> str:
    return re.split(r"(?:，|,|。|；|;)?\s*(?:不发送|不要发送|不发消息|no send|do not send)", text, maxsplit=1, flags=re.IGNORECASE)[0].strip()


def _normalize_text_for_route(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").lower())


def _extract_message(text: str) -> str | None:
    quoted = _quoted_items(text)
    if quoted:
        return quoted[-1]
    named = _extract_named_value(text, ["消息", "内容", "正文", "message"])
    if named:
        return named
    patterns = [
        r"(?:发送|发一条|发消息|send)\s*(?:一条)?\s*(?:消息)?\s*[:：]?\s*(.+)$",
        r"(?:说|写)\s*[:：]?\s*(.+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        candidate = _strip_leading_target_phrase(match.group(1).strip())
        if candidate:
            return candidate
    return None


def _extract_mention_user(text: str) -> str | None:
    patterns = [
        r"@[\s]*([^\s，。；;、\"'“”‘’「」『』]+)",
        r"(?:艾特|提及|mention)\s*[\"'“”‘’「」『』]?([^\s，。；;、\"'“”‘’「」『』]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            candidate = _strip_punctuation(match.group(1))
            candidate = re.sub(r"^(?:艾特|提及|mention)", "", candidate, flags=re.IGNORECASE).strip()
            return candidate or None
    return None


def _extract_people_list(text: str) -> list[str]:
    for key in ("成员", "群成员", "邀请", "拉", "加入"):
        value = _extract_named_value(text, [key])
        if value:
            return [item for item in (_strip_punctuation(part) for part in re.split(r"[、,，和\s]+", value)) if item]
    people = re.findall(r"(李新元|吴佳园|张三|李四)", text)
    return list(dict.fromkeys(people))


def _extract_image_path(text: str) -> str | None:
    match = re.search(r"([A-Za-z]:\\[^，。；;\"'“”‘’「」『』]+?\.(?:png|jpg|jpeg|bmp|gif))", text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    match = re.search(r"([^\s，。；;\"'“”‘’「」『』]+?\.(?:png|jpg|jpeg|bmp|gif))", text, re.IGNORECASE)
    return match.group(1).strip() if match else None


def _extract_emoji_name(text: str) -> str | None:
    for item in ("点赞", "爱心", "笑脸", "鼓掌", "OK", "ok"):
        if item in text:
            return item
    named = _extract_named_value(text, ["表情", "emoji", "reaction"])
    return named


def _extract_named_value(text: str, names: list[str]) -> str | None:
    name_pattern = "|".join(re.escape(name) for name in names)
    quoted_match = re.search(
        rf"(?:{name_pattern})\s*(?:为|是|叫|:|：)\s*([\"'“”‘’「」『』])(.+?)([\"'“”‘’「」『』])",
        text,
        re.IGNORECASE,
    )
    if quoted_match and _is_matching_quote(quoted_match.group(1), quoted_match.group(3)):
        return _strip_punctuation(quoted_match.group(2))
    match = re.search(rf"(?:{name_pattern})\s*(?:为|是|叫|:|：)\s*[\"'“”‘’「」『』]?(.+?)[\"'“”‘’「」『』]?(?:[，。；;]|$)", text, re.IGNORECASE)
    if match:
        return _strip_punctuation(match.group(1))
    return None


def _extract_title_value(text: str, *, entity_words: tuple[str, ...] = ()) -> str | None:
    label_words = (
        "标题",
        "名称",
        "名字",
        "题目",
        "会议标题",
        "会议名称",
        "日程标题",
        "日程名称",
        "文档标题",
        "文档名称",
        "群名",
        "群名称",
    )
    label_pattern = "|".join(re.escape(item) for item in label_words)
    quoted_match = re.search(
        rf"(?:{label_pattern})\s*(?:为|是|叫|:|：)\s*([\"'“”‘’「」『』])(.+?)([\"'“”‘’「」『』])",
        text,
        re.IGNORECASE,
    )
    if quoted_match and _is_matching_quote(quoted_match.group(1), quoted_match.group(3)):
        return _strip_common(quoted_match.group(2))

    quoted_name_match = re.search(
        r"(?:名为|叫做|命名为|取名为|叫)\s*([\"'“”‘’「」『』])(.+?)([\"'“”‘’「」『』])",
        text,
        re.IGNORECASE,
    )
    if quoted_name_match and _is_matching_quote(quoted_name_match.group(1), quoted_name_match.group(3)):
        return _strip_common(quoted_name_match.group(2))

    stop_words = ("，", "。", "；", ";", "\n")
    unquoted_match = re.search(
        rf"(?:{label_pattern})\s*(?:为|是|叫|:|：)\s*([^，。；;\n\"'“”‘’「」『』]+)",
        text,
        re.IGNORECASE,
    )
    if unquoted_match:
        return _clean_extracted_title(unquoted_match.group(1), entity_words)

    unquoted_name_match = re.search(
        r"(?:名为|叫做|命名为|取名为|叫)\s*([^，。；;\n\"'“”‘’「」『』]+)",
        text,
        re.IGNORECASE,
    )
    if unquoted_name_match:
        return _clean_extracted_title(unquoted_name_match.group(1), entity_words)

    return None


def _clean_extracted_title(raw: str, entity_words: tuple[str, ...] = ()) -> str | None:
    cleaned = _strip_common(raw)
    if not cleaned:
        return None
    for word in entity_words:
        if not word:
            continue
        cleaned = re.sub(rf"(?:的)?{re.escape(word)}$", "", cleaned).strip()
    cleaned = re.sub(r"(?:的)?(?:日程|会议|文档|云文档|群|群组)$", "", cleaned).strip()
    return _strip_common(cleaned)


def _is_matching_quote(left: str, right: str) -> bool:
    return {
        '"': '"',
        "'": "'",
        "“": "”",
        "‘": "’",
        "「": "」",
        "『": "』",
    }.get(left) == right


def _quoted_items(text: str) -> list[str]:
    return [item.strip() for item in re.findall(r"[\"'“”‘’「」『』](.*?)[\"'“”‘’「」『』]", text) if item.strip()]


def _strip_leading_target_phrase(text: str) -> str:
    text = re.sub(r"^(?:给|向|发给)\s*[^，。；;、]+\s*[，。；;、]?\s*", "", text)
    text = re.sub(r"^到\s*[^，。；;、]+\s*[，。；;、]?\s*", "", text)
    return _strip_punctuation(text)


def _strip_punctuation(text: str) -> str:
    cleaned = (text or "").strip().strip(" ，。；;、\"'“”‘’「」『』")
    cleaned = re.sub(r"(?:一条)?消息$", "", cleaned).strip()
    return cleaned


def _strip_common(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = text.strip().strip(" \t\r\n，。；;、\"'“”‘’「」『』")
    return cleaned or None


def _is_doc_create_instruction(text: str) -> bool:
    if not _mentions_docs(text):
        return False
    return _contains_any(text, ["创建", "新建", "写一篇", "写入", "输入", "生成", "create", "new"])


def _is_doc_rich_edit_instruction(text: str) -> bool:
    if not _mentions_docs(text):
        return False
    rich_markers = [
        "一级标题",
        "二级标题",
        "三级标题",
        "插入标题",
        "添加标题",
        "正文标题",
        "小标题",
        "列表",
        "清单",
        "项目符号",
        "编号",
        "有序列表",
        "无序列表",
        "heading",
        "list",
        "bullet",
    ]
    return _contains_any(text, rich_markers)


def _is_doc_share_instruction(text: str) -> bool:
    if not _mentions_docs(text):
        return False
    return _contains_any(text, ["分享", "共享", "发送链接", "share", "permission"])


def _extract_doc_rich_content(text: str) -> tuple[str | None, str | None, str | None, list[str]]:
    title, body = _extract_doc_content(text)
    heading = _extract_named_value(text, ["标题", "一级标题", "二级标题", "heading"]) or title
    list_items: list[str] = []
    list_match = re.search(r"(?:列表|清单|项目符号|list)\s*(?:为|是|：|:)?\s*(.+)$", text, re.IGNORECASE)
    if list_match:
        list_items = [
            item
            for item in (_strip_common(part) for part in re.split(r"[、,，;\n]+", list_match.group(1)))
            if item
        ]
    quoted = _quoted_items(text)
    if not list_items and len(quoted) >= 2 and _contains_any(text, ["列表", "清单", "list"]):
        list_items = [item for item in (_strip_common(raw) for raw in quoted[1:]) if item]
    return title, body, heading, list_items[:6]


def _extract_share_recipient(text: str) -> str | None:
    for pattern in [
        r"(?:分享给|共享给|发送给|授权给)\s*[\"'“”‘’「」『』]?([^，。；;\s\"'“”‘’「」『』]+)",
        r"(?:邀请|协作者|成员)\s*(?:为|是|：|:)?\s*[\"'“”‘’「」『』]?([^，。；;\s\"'“”‘’「」『』]+)",
    ]:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return _strip_common(match.group(1))
    return None


def _extract_doc_content(text: str) -> tuple[str | None, str | None]:
    title = _extract_title_value(text, entity_words=("云文档", "文档"))
    for pattern in [
        r"(?:标题(?:为|是|叫|：|:)|题目(?:为|是|叫|：|:)|名为|叫做)\s*[\"'“”‘’「」『』]?([^，。；;\n\"'“”‘’「」『』]+)",
        r"(?:创建|新建)(?:一个|一篇)?(?:测试)?(?:云文档|文档)?\s*[\"'“”‘’「」『』]?([^，。；;\n\"'“”‘’「」『』]+)",
    ]:
        if title is not None:
            break
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            title = _strip_common(match.group(1))
            break

    body = None
    quoted_body = re.search(
        r"(?:正文|内容|文档内容|body)\s*(?:为|是|写入|输入|：|:)?\s*([\"'“”‘’「」『』])(.+?)([\"'“”‘’「」『』])",
        text,
        re.IGNORECASE,
    )
    if quoted_body and _is_matching_quote(quoted_body.group(1), quoted_body.group(3)):
        body = _strip_common(quoted_body.group(2))
    for pattern in [
        r"(?:正文|内容|文档内容|body)\s*(?:为|是|写入|输入|：|:)?\s*(.+)$",
        r"(?:写入|输入)\s*(.+)$",
    ]:
        if body is not None:
            break
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            body = _strip_common(match.group(1))
            break

    quoted = _quoted_items(text)
    if quoted:
        if title is None:
            title = _strip_common(quoted[0])
        if len(quoted) > 1 and body is None:
            body = _strip_common(quoted[-1])
    if body:
        body = re.split(r"(?:分享给|共享给|发送给|授权给|share with)", body, maxsplit=1, flags=re.IGNORECASE)[0]
        body = re.split(
            r"(?:插入标题|添加标题|正文标题|小标题|一级标题|二级标题|三级标题|和列表|并列表|列表|清单|项目符号|编号)",
            body,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]
        body = _strip_common(body)
    return title, body


def _is_calendar_create_instruction(text: str) -> bool:
    if not _contains_any(text, ["日历", "会议", "日程", "calendar", "meeting", "event"]):
        return False
    return _contains_any(text, ["创建", "新建", "安排", "预约", "保存", "create", "new", "schedule"])


def _is_calendar_invite_instruction(text: str) -> bool:
    if not _contains_any(text, ["日历", "会议", "日程", "calendar", "meeting", "event"]):
        return False
    return _contains_any(text, ["邀请", "参会人", "参与人", "添加成员", "attendee", "invite"])


def _is_calendar_modify_time_instruction(text: str) -> bool:
    if not _contains_any(text, ["日历", "会议", "日程", "calendar", "meeting", "event"]):
        return False
    return _contains_any(text, ["修改", "改到", "调整", "移动", "变更", "reschedule", "change time"])


def _is_calendar_busy_free_instruction(text: str) -> bool:
    if not _contains_any(text, ["日历", "会议", "日程", "calendar", "meeting", "event"]):
        return False
    return _contains_any(text, ["忙闲", "空闲", "有空", "busy", "free", "availability"])


def _extract_calendar_people(text: str) -> list[str]:
    match = re.search(r"(?:参会人|参与人|邀请|查看|成员|人员)\s*(?:为|是|：|:)?\s*[\"'“”‘’「」『』]?(.+?)(?:[\"'“”‘’「」『』]?(?:的忙闲|忙闲|是否有空|有空|参加|参会|$))", text)
    if not match:
        return []
    raw = re.split(r"(?:今天|明天|后天|下周|周[一二三四五六日天]|星期[一二三四五六日天]|\d{1,2}[:：]\d{2}|\d{1,2}点)", match.group(1), maxsplit=1)[0]
    return [
        item
        for item in (_strip_common(part) for part in re.split(r"[、,，和\s]+", raw))
        if item and item not in {"查看", "邀请", "参会人"}
    ]


def _extract_calendar_busy_free_time(text: str) -> str | None:
    match = re.search(
        r"((?:今天|明天|后天|下周|周[一二三四五六日天]|星期[一二三四五六日天])\s*(?:上午|下午|晚上|中午)?\s*\d{1,2}[:：]\d{2})",
        text,
    )
    if match:
        return _strip_common(match.group(1).replace("：", ":"))
    match = re.search(
        r"((?:今天|明天|后天|下周|周[一二三四五六日天]|星期[一二三四五六日天])\s*(?:上午|下午|晚上|中午)?\s*\d{1,2}点(?:\d{1,2}分)?)",
        text,
    )
    if match:
        return _strip_common(match.group(1))
    return None


def _extract_new_event_time(text: str) -> str | None:
    for pattern in [
        r"(?:改到|调整到|修改为|变更为|移动到)\s*([^，。；;\n]+?)(?:并保存|保存|$)",
        r"(?:新时间|新的时间)\s*(?:为|是|：|:)?\s*([^，。；;\n]+)",
    ]:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return _strip_common(match.group(1))
    return None


def _extract_calendar_event(text: str) -> tuple[str | None, str | None, list[str]]:
    title = _extract_title_value(text, entity_words=("日程", "会议"))
    for pattern in [
        r"(?:创建|新建|安排|预约)(?:一个|一场)?(?:测试)?(?:会议|日程)\s*[\"'“”‘’「」『』]([^，。；;\n\"'“”‘’「」『』]+)[\"'“”‘’「」『』]?",
        r"(?:标题|名称)(?:为|是|叫|：|:)\s*[\"'“”‘’「」『』]?([^，。；;\n\"'“”‘’「」『』]+)",
    ]:
        if title is not None:
            break
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            title = _clean_extracted_title(match.group(1), ("日程", "会议"))
            break

    time_phrase = None
    for pattern in [
        r"(?:时间)(?:为|是|：|:)\s*([^，。；;\n]+)",
        r"(?:先设为|先设置为|原时间(?:为|是|：|:)|从)\s*([^，。；;\n]+?)(?:，|,|然后|再|并|修改|改到|调整|$)",
        r"(?:安排到|安排在)\s*([^，。；;\n]+)",
        r"((?:今天|明天|后天|下周|周[一二三四五六日天]|星期[一二三四五六日天]|\d{1,2}[月/-]\d{1,2}[日号]?).{0,18}(?:\d{1,2}[:：]\d{2}|\d{1,2}点|上午|下午|晚上|中午).{0,18})",
    ]:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            time_phrase = _strip_common(match.group(1))
            break

    attendees: list[str] = []
    attendee_match = re.search(
        r"(?:参会人|参与人|参会人列表)\s*(?:为|是|：|:)?\s*[\"'“”‘’「」『』]?(.+?)(?:[\"'“”‘’「」『』]?(?:参加|参会|开会)|[，。；;\n]|$)",
        text,
    )
    if attendee_match is None:
        attendee_match = re.search(
            r"(?:并|，|,|。|；|;)\s*邀请\s*[\"'“”‘’「」『』]?(.+?)(?:[\"'“”‘’「」『』]?(?:参加|参会|开会)|[，。；;\n]|$)",
            text,
        )
    if attendee_match:
        attendees = [
            item
            for item in (_strip_common(part) for part in re.split(r"[、,，和\s]+", attendee_match.group(1)))
            if item
        ]
    return title, time_phrase, attendees


def _is_vc_start_instruction(text: str) -> bool:
    direct_start = _contains_any(
        text,
        [
            "发起会议",
            "开始会议",
            "新会议",
            "start meeting",
            "start a meeting",
            "new meeting",
        ],
    )
    natural_start = _contains_any(text, ["发起", "开始", "新建", "创建"]) and "会议" in text
    return (direct_start or natural_start) and not _is_vc_join_instruction(text)


def _is_vc_join_instruction(text: str) -> bool:
    direct_join = _contains_any(
        text,
        [
            "加入会议",
            "入会",
            "会议id",
            "会议ID",
            "会议号",
            "join meeting",
            "meeting id",
        ],
    )
    natural_join_with_id = _contains_any(text, ["加入", "join"]) and bool(_extract_vc_meeting_id(text))
    return direct_join or natural_join_with_id


def _is_vc_device_instruction(text: str) -> bool:
    return _contains_any(
        text,
        [
            "摄像头",
            "麦克风",
            "麦克",
            "静音",
            "camera",
            "microphone",
            "mic",
            "mute",
            "unmute",
        ],
    )


def _extract_vc_meeting_id(text: str) -> str | None:
    for pattern in (
        r"(?:会议\s*id|会议\s*ID|会议号|id|ID|meeting\s*id)\s*(?:为|是|:|：)?\s*([0-9\s-]{6,})",
        r"(?:会议\s*id|会议\s*ID|会议号|meeting\s*id)\s*[:：]?\s*([0-9\s-]{6,})",
        r"\b(\d[\d\s-]{5,}\d)\b",
    ):
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        meeting_id = re.sub(r"\D", "", match.group(1))
        if len(meeting_id) >= 6:
            return meeting_id
    return None


def _extract_vc_meeting_title(text: str) -> str | None:
    title = _extract_title_value(text, entity_words=("视频会议", "会议"))
    if title:
        return title
    for pattern in (
        r"(?:名为|叫做|叫)\s*[\"'“”‘’「」『』]?([^，。；;\n\"'“”‘’「」『』]+)",
        r"(?:会议名称|会议名|会议标题|名称|名字|标题)\s*(?:为|是|叫|:|：)\s*[\"'“”‘’「」『』]?([^，。；;\n\"'“”‘’「」『』]+)",
    ):
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return _strip_common(match.group(1))
    return None


def _extract_vc_device_intent(text: str) -> tuple[bool | None, bool | None]:
    camera_on = _extract_single_device_intent(
        text,
        device_markers=("摄像头", "摄像", "camera", "video"),
        on_markers=("打开", "开启", "开", "on", "enable", "start"),
        off_markers=("关闭", "关掉", "关", "off", "disable", "stop"),
    )
    mic_on = _extract_single_device_intent(
        text,
        device_markers=("麦克风", "麦克", "话筒", "mic", "microphone", "audio"),
        on_markers=("打开", "开启", "解除静音", "开", "on", "enable", "unmute"),
        off_markers=("关闭", "关掉", "静音", "关", "off", "disable", "mute"),
    )
    if _contains_any(text, ["摄像头和麦克风", "摄像头/麦克风", "摄像头麦克风", "camera and microphone"]):
        both_on = _contains_any(text, ["打开", "开启", "on", "enable"])
        both_off = _contains_any(text, ["关闭", "关掉", "off", "disable"])
        if both_on:
            camera_on = True if camera_on is None else camera_on
            mic_on = True if mic_on is None else mic_on
        elif both_off:
            camera_on = False if camera_on is None else camera_on
            mic_on = False if mic_on is None else mic_on
    return camera_on, mic_on


def _extract_single_device_intent(
    text: str,
    *,
    device_markers: tuple[str, ...],
    on_markers: tuple[str, ...],
    off_markers: tuple[str, ...],
) -> bool | None:
    lowered = text.lower()
    for device in device_markers:
        index = lowered.find(device.lower())
        if index < 0:
            continue
        before = lowered[max(0, index - 10) : index]
        after = lowered[index : index + 16]
        scope = before + after
        if any(marker.lower() in scope for marker in off_markers):
            return False
        if any(marker.lower() in scope for marker in on_markers):
            return True
    return None


def _expected_result(intent: ParsedIntent) -> str:
    if intent.intent == "im_send_message":
        return "The guarded text message is sent only to the explicitly allowed test chat."
    if intent.intent == "im_send_image":
        return "The guarded image message is sent only to the explicitly allowed test chat."
    if intent.intent == "im_create_group":
        return "A guarded test group is created only when group creation is explicitly enabled."
    if intent.intent == "im_mention_user":
        return "The guarded @ mention is sent only to the explicitly allowed test chat."
    if intent.intent == "im_search_messages":
        return "The IM message-history search results are visible and no message is sent."
    if intent.intent == "im_emoji_reaction":
        return "A guarded emoji reaction is applied to a visible test message only when explicitly enabled."
    if intent.intent == "im_search_only":
        return "The IM search input is focused and no chat message is sent."
    if intent.intent == "docs_create_doc":
        return "A guarded test document is created only when CUA_LARK_ALLOW_DOC_CREATE=true, and its title/body are visible."
    if intent.intent == "docs_edit_text":
        return "A guarded test document is edited only when CUA_LARK_ALLOW_DOC_CREATE=true, and the edited text is visible."
    if intent.intent == "docs_rich_edit":
        return "A guarded test document is created and formatted with heading/list content."
    if intent.intent == "docs_share_doc":
        return "A guarded test document is shared only when document creation/share guards are explicitly enabled."
    if intent.intent == "docs_open_smoke":
        return "The Docs entry or workspace is visible and no document is created or modified."
    if intent.intent == "calendar_create_event":
        return "A guarded test calendar event is created only when CUA_LARK_ALLOW_CALENDAR_CREATE=true, and the event is visible."
    if intent.intent == "calendar_invite_attendee":
        return "A guarded calendar event includes the requested attendee only when calendar invite is explicitly enabled."
    if intent.intent == "calendar_modify_event_time":
        return "A guarded calendar event time is modified only when calendar mutation is explicitly enabled."
    if intent.intent == "calendar_view_busy_free":
        return "The Calendar busy/free state for the requested attendee is visible."
    if intent.intent == "vc_start_meeting":
        return "A guarded video meeting is started only when VC start is explicitly enabled; requested device states are verified when provided."
    if intent.intent == "vc_join_meeting":
        return "A guarded video meeting is joined by meeting ID only when VC join is explicitly enabled; requested device states are verified when provided."
    if intent.intent == "vc_toggle_devices":
        return "Camera and microphone state is changed only when VC device toggle is explicitly enabled."
    return ""


def _case_name(intent: ParsedIntent) -> str:
    names = {
        "im_send_message": "Natural language IM guarded text send",
        "im_send_image": "Natural language IM guarded image send",
        "im_create_group": "Natural language IM guarded group create",
        "im_mention_user": "Natural language IM guarded mention",
        "im_search_messages": "Natural language IM message-history search",
        "im_emoji_reaction": "Natural language IM guarded emoji reaction",
        "im_search_only": "Natural language IM safe search",
        "docs_create_doc": "Natural language Docs guarded create",
        "docs_edit_text": "Natural language Docs guarded text edit",
        "docs_rich_edit": "Natural language Docs guarded heading/list edit",
        "docs_share_doc": "Natural language Docs guarded share",
        "docs_open_smoke": "Natural language Docs safe open",
        "calendar_create_event": "Natural language Calendar guarded create",
        "calendar_invite_attendee": "Natural language Calendar guarded attendee invite",
        "calendar_modify_event_time": "Natural language Calendar guarded time modification",
        "calendar_view_busy_free": "Natural language Calendar busy-free lookup",
        "vc_start_meeting": "Natural language VC guarded start meeting",
        "vc_join_meeting": "Natural language VC guarded join meeting",
        "vc_toggle_devices": "Natural language VC guarded device toggle",
    }
    return names.get(intent.intent, "CLI natural-language run")
