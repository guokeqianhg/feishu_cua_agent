from __future__ import annotations

from datetime import datetime, timedelta

from app.config import settings
from core.schemas import PlanStep, TestCase, TestPlan


def build_product_plan(case: TestCase) -> TestPlan | None:
    """Return deterministic plans for guarded demos and smoke checks.

    These templates keep the fast, safe demo path out of the VLM client while
    still allowing generic natural-language cases to fall back to the model.
    """

    template = str(case.metadata.get("plan_template") or "").strip()
    if case.metadata.get("safe_smoke") or template in {"safe_smoke", "im_search_only"}:
        return _im_search_only_plan(case)
    if template == "im_send_message_guarded":
        return _im_send_message_guarded_plan(case)
    if template in {"docs_open_smoke", "docs_smoke"}:
        return _docs_open_smoke_plan(case)
    if template == "docs_create_doc_guarded":
        return _docs_create_doc_guarded_plan(case)
    if template == "calendar_create_event_guarded":
        return _calendar_create_event_guarded_plan(case)
    return None


def _im_search_only_plan(case: TestCase) -> TestPlan:
    search_text = str(case.metadata.get("search_text") or "harmless-smoke-test")
    return TestPlan(
        goal=case.instruction,
        product="im",
        steps=[
            PlanStep(
                id="open_im",
                action="wait",
                target_description="Feishu/Lark desktop window",
                expected_state="Feishu IM is already open and visible.",
                retry_limit=2,
                metadata={"local_verifier": "im_open"},
            ),
            PlanStep(
                id="focus_search",
                action="hover",
                target_description="left sidebar search box",
                expected_state="Feishu sidebar or global search input is focused.",
                retry_limit=1,
                metadata={"local_verifier": "im_search_focused", "locator_strategy": "sidebar_search_box"},
            ),
            PlanStep(
                id="type_safe_query",
                action="type_text",
                target_description="search box",
                input_text=search_text,
                expected_state="Search text is entered into the search input.",
                retry_limit=1,
                metadata={
                    "local_verifier": "im_search_text_entered",
                    "locator_strategy": "search_dialog_input",
                    "safe_no_send": True,
                    "clear_before_type": True,
                },
            ),
            PlanStep(
                id="observe_results",
                action="wait",
                wait_seconds=1.0,
                expected_state="Search results or an empty-state panel is visible.",
                retry_limit=1,
                metadata={"local_verifier": "visible_screen"},
            ),
            PlanStep(
                id="verify_no_send",
                action="verify",
                target_description="current screen",
                expected_state="No chat message was sent.",
                retry_limit=1,
                metadata={"local_verifier": "no_send"},
            ),
        ],
        success_criteria=[
            "Feishu IM is visible.",
            f"Search input contains or visibly reflects {search_text!r}.",
            "No chat message is sent.",
        ],
        assumptions=["This is a safe no-send IM workflow template."],
        raw_model_output={"provider": "product_template", "template": "im_search_only"},
    )


def _im_send_message_guarded_plan(case: TestCase) -> TestPlan:
    target = str(case.metadata.get("target") or settings.allowed_im_target or "测试群")
    message = str(case.metadata.get("message") or "CUA-Lark guarded smoke message")
    return TestPlan(
        goal=case.instruction,
        product="im",
        steps=[
            PlanStep(
                id="open_im",
                action="focus_window",
                target_description="Feishu/Lark desktop window",
                expected_state="Feishu IM is open and visible.",
                retry_limit=1,
                metadata={"local_verifier": "im_open"},
            ),
            PlanStep(
                id="focus_search",
                action="click",
                target_description="left sidebar search box",
                expected_state="Search input is focused.",
                retry_limit=1,
                metadata={"local_verifier": "im_search_focused", "locator_strategy": "sidebar_search_box"},
            ),
            PlanStep(
                id="type_query",
                action="type_text",
                target_description="search box",
                input_text=target,
                expected_state="Target chat keyword is entered into search.",
                retry_limit=1,
                metadata={
                    "local_verifier": "im_search_text_entered",
                    "locator_strategy": "search_dialog_input",
                    "target": target,
                    "clear_before_type": True,
                },
            ),
            PlanStep(
                id="open_chat",
                action="click",
                target_description=f"first matching test chat result for {target}",
                expected_state=f"The chat conversation header is the target test chat {target!r}.",
                retry_limit=1,
                metadata={
                    "local_verifier": "im_chat_opened",
                    "requires_send_guard": True,
                    "locator_strategy": "search_first_result",
                    "guard_phase": "open_chat",
                    "target": target,
                },
            ),
            PlanStep(
                id="type_message",
                action="type_text",
                target_description="current chat message input focus",
                input_text=message,
                expected_state="Message text is drafted in the input box but not sent yet.",
                retry_limit=1,
                metadata={
                    "local_verifier": "im_message_drafted",
                    "requires_send_guard": True,
                    "guard_phase": "draft_message",
                    "target": target,
                    "clear_before_type": True,
                    "use_current_focus": True,
                },
            ),
            PlanStep(
                id="send_message",
                action="hotkey",
                hotkeys=["enter"],
                expected_state=f"Message is sent to the allowed test chat {target!r}, not to any other chat.",
                retry_limit=1,
                metadata={
                    "local_verifier": "im_message_sent",
                    "requires_send_guard": True,
                    "dangerous_send": True,
                    "target": target,
                    "message": message,
                },
            ),
            PlanStep(
                id="verify_message",
                action="verify",
                target_description="latest chat message",
                expected_state=f"Latest chat history in {target!r} contains the guarded smoke message from the current user: {message!r}.",
                retry_limit=1,
                metadata={"local_verifier": "im_message_visible"},
            ),
        ],
        success_criteria=[
            f"Target test chat {target!r} is opened.",
            f"Message {message!r} is sent only when CUA_LARK_ALLOW_SEND_MESSAGE=true.",
        ],
        assumptions=["Full send is guarded by explicit environment policy."],
        raw_model_output={"provider": "product_template", "template": "im_send_message_guarded"},
    )


def _docs_open_smoke_plan(case: TestCase) -> TestPlan:
    return TestPlan(
        goal=case.instruction,
        product="docs",
        steps=[
            PlanStep(
                id="open_docs",
                action="click",
                target_description="Feishu Docs sidebar entry",
                expected_state="Docs entry is clicked or Docs workspace becomes visible.",
                retry_limit=1,
                metadata={"local_verifier": "docs_entry_clicked", "locator_strategy": "docs_sidebar_entry"},
            ),
            PlanStep(
                id="observe_docs",
                action="wait",
                wait_seconds=1.0,
                expected_state="Docs workspace or Docs-related screen remains visible.",
                retry_limit=1,
                metadata={"local_verifier": "docs_visible"},
            ),
            PlanStep(
                id="verify_docs_no_create",
                action="verify",
                target_description="current Docs screen",
                expected_state="Docs smoke did not create or modify any document.",
                retry_limit=1,
                metadata={"local_verifier": "docs_no_create"},
            ),
        ],
        success_criteria=[
            "A visible Feishu screen is captured after attempting to open Docs.",
            "No document creation or content mutation action is executed.",
        ],
        assumptions=["This is a non-destructive Docs smoke workflow."],
        raw_model_output={"provider": "product_template", "template": "docs_open_smoke"},
    )


def _docs_create_doc_guarded_plan(case: TestCase) -> TestPlan:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    title = str(case.metadata.get("doc_title") or f"CUA-Lark 测试文档 {stamp}")
    body = str(case.metadata.get("doc_body") or "这是一段由 CUA-Lark 自动写入的安全测试正文。")
    return TestPlan(
        goal=case.instruction,
        product="docs",
        steps=[
            PlanStep(
                id="focus_lark",
                action="focus_window",
                target_description="Feishu/Lark desktop window",
                expected_state="Feishu/Lark is foreground and ready for product navigation.",
                retry_limit=1,
                metadata={"local_verifier": "lark_focused"},
            ),
            PlanStep(
                id="dismiss_overlays",
                action="conditional_hotkey",
                hotkeys=["esc"],
                expected_state="A stale overlay is dismissed only if the screen indicates one is present.",
                retry_limit=1,
                metadata={"local_verifier": "visible_screen", "locator_strategy": "docs_transient_overlay"},
            ),
            PlanStep(
                id="close_docs_template_preview",
                action="conditional_click",
                target_description="Docs template preview back button if a stale preview modal is open",
                expected_state="Any stale Docs template preview is closed before creating a new blank document.",
                retry_limit=1,
                metadata={
                    "local_verifier": "visible_screen",
                    "locator_strategy": "docs_template_preview_back",
                    "locator_kind": "button",
                },
            ),
            PlanStep(
                id="open_docs",
                action="click",
                target_description="Feishu Docs sidebar entry",
                expected_state="Docs workspace is visible.",
                retry_limit=1,
                metadata={"local_verifier": "docs_visible", "locator_strategy": "docs_sidebar_entry"},
            ),
            PlanStep(
                id="dismiss_docs_popups",
                action="conditional_hotkey",
                hotkeys=["esc"],
                expected_state="Any visible Docs search popup or transient overlay is dismissed before clicking create.",
                retry_limit=1,
                metadata={"local_verifier": "visible_screen", "locator_strategy": "docs_transient_overlay"},
            ),
            PlanStep(
                id="click_create_doc",
                action="hover",
                target_description="Docs create menu button",
                expected_state="Docs creation menu is opened.",
                retry_limit=1,
                metadata={
                    "local_verifier": "visible_screen",
                    "requires_doc_create_guard": True,
                    "locator_strategy": "docs_create_button",
                    "locator_kind": "button",
                },
            ),
            PlanStep(
                id="click_blank_doc",
                action="click",
                target_description="Docs blank document menu item",
                expected_state="The blank document template picker is opened.",
                retry_limit=1,
                metadata={
                    "local_verifier": "visible_screen",
                    "requires_doc_create_guard": True,
                    "locator_strategy": "docs_blank_doc_option",
                    "locator_kind": "button",
                },
            ),
            PlanStep(
                id="wait_blank_doc_picker",
                action="wait",
                wait_seconds=1.5,
                expected_state="The blank document picker has finished loading.",
                retry_limit=1,
                metadata={"local_verifier": "visible_screen"},
            ),
            PlanStep(
                id="click_blank_doc_card",
                action="click",
                target_description="Docs new blank document card",
                expected_state="A new blank document editor is opened.",
                retry_limit=1,
                metadata={
                    "local_verifier": "docs_editor_opened",
                    "requires_doc_create_guard": True,
                    "locator_strategy": "docs_blank_doc_card",
                    "locator_kind": "button",
                    "preserve_after_foreground": True,
                },
            ),
            PlanStep(
                id="focus_docs_editor_window",
                action="focus_window",
                target_description="browser window containing the new Feishu Docs editor",
                expected_state="The Feishu Docs browser editor window is foreground.",
                retry_limit=3,
                metadata={
                    "local_verifier": "visible_screen",
                    "foreground_window_keywords": ["飞书云文档", "未命名文档", "Docs"],
                    "focus_docs_editor": True,
                    "preserve_foreground": True,
                },
            ),
            PlanStep(
                id="wait_doc_editor",
                action="wait",
                wait_seconds=7.0,
                expected_state="Docs editor has finished loading and the title field is focused.",
                retry_limit=1,
                metadata={"local_verifier": "visible_screen", "preserve_foreground": True},
            ),
            PlanStep(
                id="type_doc_title",
                action="type_text",
                target_description="document title field",
                input_text=title,
                expected_state=f"Document title field contains {title!r}.",
                retry_limit=1,
                metadata={
                    "local_verifier": "docs_title_entered",
                    "requires_doc_create_guard": True,
                    "foreground_window_keywords": ["飞书云文档", "未命名文档", "Docs", "wiki", "feishu"],
                    "doc_title": title,
                    "clear_before_type": True,
                    "use_current_focus": True,
                    "preserve_foreground": True,
                },
            ),
            PlanStep(
                id="move_to_doc_body",
                action="hotkey",
                hotkeys=["enter"],
                expected_state="Cursor moves from the title field into the body editor.",
                retry_limit=1,
                metadata={
                    "local_verifier": "visible_screen",
                    "requires_doc_create_guard": True,
                    "foreground_window_keywords": ["飞书云文档", "未命名文档", "Docs", "wiki", "feishu"],
                    "preserve_foreground": True,
                },
            ),
            PlanStep(
                id="type_doc_body",
                action="type_text",
                target_description="document body editor area",
                input_text=body,
                expected_state=f"Document body contains {body!r}.",
                retry_limit=1,
                metadata={
                    "local_verifier": "docs_body_entered",
                    "requires_doc_create_guard": True,
                    "foreground_window_keywords": ["飞书云文档", "未命名文档", "Docs", "wiki", "feishu"],
                    "doc_title": title,
                    "doc_body": body,
                    "clear_before_type": True,
                    "use_current_focus": True,
                    "preserve_foreground": True,
                },
            ),
            PlanStep(
                id="verify_doc_content",
                action="verify",
                target_description="current document",
                expected_state=f"The current document visibly contains title {title!r} and body {body!r}.",
                retry_limit=1,
                metadata={
                    "local_verifier": "docs_content_visible",
                    "doc_title": title,
                    "doc_body": body,
                    "preserve_foreground": True,
                },
            ),
        ],
        success_criteria=[
            f"Docs editor is opened only when CUA_LARK_ALLOW_DOC_CREATE=true.",
            f"Title {title!r} and body {body!r} are visible in the final screenshot.",
        ],
        assumptions=[
            "Feishu/Lark is already installed and logged in.",
            "Docs normally auto-saves; this workflow does not share, publish, or send the document.",
        ],
        raw_model_output={"provider": "product_template", "template": "docs_create_doc_guarded"},
    )


def _calendar_create_event_guarded_plan(case: TestCase) -> TestPlan:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    title = str(case.metadata.get("event_title") or f"CUA-Lark 测试日程 {stamp}")
    event_time = str(case.metadata.get("event_time") or "明天 10:00")
    event_date, start_time, end_time = _calendar_time_parts(event_time)
    attendees = [str(item) for item in case.metadata.get("attendees", []) if str(item).strip()]
    attendees_text = "、".join(attendees)
    steps = [
        PlanStep(
            id="focus_lark",
            action="focus_window",
            target_description="Feishu/Lark desktop window",
            expected_state="Feishu/Lark is foreground and ready for product navigation.",
            retry_limit=1,
            metadata={"local_verifier": "lark_focused"},
        ),
        PlanStep(
            id="dismiss_overlays",
            action="conditional_hotkey",
            hotkeys=["esc"],
            expected_state="A stale overlay is dismissed only if the screen indicates one is present.",
            retry_limit=1,
            metadata={"local_verifier": "visible_screen", "locator_strategy": "docs_transient_overlay"},
        ),
        PlanStep(
            id="close_calendar_editor",
            action="conditional_click",
            target_description="Calendar editor cancel button if a stale unsaved editor is open",
            expected_state="A stale Calendar editor is closed only when its cancel button is visible.",
            retry_limit=1,
            metadata={
                "local_verifier": "visible_screen",
                "locator_strategy": "calendar_cancel_button",
                "locator_kind": "button",
            },
        ),
        PlanStep(
            id="confirm_calendar_editor_exit",
            action="conditional_click",
            target_description="Calendar discard confirmation exit button if shown",
            expected_state="A stale unsaved Calendar editor is discarded only when the confirmation dialog is visible.",
            retry_limit=1,
            metadata={
                "local_verifier": "visible_screen",
                "locator_strategy": "calendar_discard_exit_button",
                "locator_kind": "button",
            },
        ),
        PlanStep(
            id="open_calendar",
            action="click",
            target_description="Feishu Calendar sidebar entry",
            expected_state="Calendar workspace is visible.",
            retry_limit=1,
            metadata={"local_verifier": "calendar_visible", "locator_strategy": "calendar_sidebar_entry"},
        ),
        PlanStep(
            id="click_calendar_main_tab",
            action="click",
            target_description="Calendar main calendar tab",
            expected_state="The main Calendar tab is selected rather than Meeting Rooms.",
            retry_limit=1,
            metadata={
                "local_verifier": "calendar_visible",
                "locator_strategy": "calendar_main_tab",
                "locator_kind": "button",
            },
        ),
        PlanStep(
            id="click_create_event",
            action="click",
            target_description="Calendar create event button",
            expected_state="Event creation dialog or editor is open.",
                retry_limit=1,
                metadata={
                    "local_verifier": "calendar_editor_opened",
                    "requires_calendar_create_guard": True,
                    "locator_strategy": "calendar_create_button",
                "locator_kind": "button",
            },
        ),
        PlanStep(
            id="wait_event_editor",
            action="wait",
            wait_seconds=2.0,
            expected_state="Calendar event editor has finished loading.",
            retry_limit=1,
            metadata={"local_verifier": "visible_screen"},
        ),
        PlanStep(
            id="type_event_title",
            action="type_text",
            target_description="calendar event title field",
            input_text=title,
            expected_state=f"Calendar event title contains {title!r}.",
            retry_limit=1,
            metadata={
                "local_verifier": "calendar_title_entered",
                "requires_calendar_create_guard": True,
                "locator_strategy": "calendar_event_title_input",
                "locator_kind": "text_input",
                "event_title": title,
                "clear_before_type": True,
            },
        ),
        PlanStep(
            id="click_event_start_date",
            action="click",
            target_description="calendar event start date field",
            expected_state="Calendar event date picker is opened.",
            retry_limit=1,
            metadata={
                "local_verifier": "visible_screen",
                "requires_calendar_create_guard": True,
                "locator_strategy": "calendar_event_start_date",
                "locator_kind": "text_input",
                "event_time": event_time,
            },
        ),
        PlanStep(
            id="click_event_start_day",
            action="click",
            target_description=f"calendar date picker day {event_date}",
            expected_state=f"Calendar event start date reflects {event_date!r}.",
            retry_limit=1,
            metadata={
                "local_verifier": "visible_screen",
                "requires_calendar_create_guard": True,
                "locator_strategy": "calendar_date_picker_day",
                "locator_kind": "button",
                "event_date": event_date,
                "require_lark_locator": True,
            },
        ),
        PlanStep(
            id="type_event_start_time",
            action="type_text",
            target_description="calendar event start time field",
            input_text=start_time,
            expected_state=f"Calendar event start time reflects {start_time!r}.",
            retry_limit=1,
            metadata={
                "local_verifier": "visible_screen",
                "requires_calendar_create_guard": True,
                "locator_strategy": "calendar_event_start_time",
                "locator_kind": "text_input",
                "event_time": event_time,
                "calendar_time_from_text": True,
                "clear_before_type": True,
                "double_click_before_type": True,
                "press_enter_after_type": True,
            },
        ),
        PlanStep(
            id="type_event_end_time",
            action="type_text",
            target_description="calendar event end time field",
            input_text=end_time,
            expected_state=f"Calendar event time reflects {event_time!r}.",
            retry_limit=1,
            metadata={
                "local_verifier": "visible_screen",
                "requires_calendar_create_guard": True,
                "locator_strategy": "calendar_event_end_time",
                "locator_kind": "text_input",
                "event_time": event_time,
                "event_date": event_date,
                "start_time": start_time,
                "end_time": end_time,
                "calendar_time_from_text": True,
                "clear_before_type": True,
                "double_click_before_type": True,
                "press_enter_after_type": True,
            },
        ),
    ]
    if attendees_text and settings.allow_calendar_invite:
        steps.append(
            PlanStep(
                id="type_event_attendees",
                action="type_text",
                target_description="calendar attendee or participant field",
                input_text=attendees_text,
                expected_state=f"Calendar attendee field contains {attendees_text!r}.",
                retry_limit=1,
                metadata={
                    "local_verifier": "calendar_attendees_entered",
                    "requires_calendar_create_guard": True,
                    "locator_strategy": "calendar_event_attendee_input",
                    "locator_kind": "text_input",
                    "attendees": attendees,
                    "clear_before_type": True,
                },
            )
        )
    steps.extend(
        [
            PlanStep(
                id="save_event",
                action="click",
                target_description="Calendar save or confirm event button",
                expected_state=f"Calendar event {title!r} is saved.",
                retry_limit=1,
                metadata={
                    "local_verifier": "calendar_event_saved",
                    "requires_calendar_create_guard": True,
                    "dangerous_calendar_create": True,
                    "locator_strategy": "calendar_save_button",
                    "locator_kind": "button",
                    "event_title": title,
                    "event_time": event_time,
                    "attendees": attendees,
                },
            ),
            PlanStep(
                id="wait_saved_event_visible",
                action="wait",
                wait_seconds=1.2,
                expected_state="Calendar returns to the event view after save and transient success toast settles.",
                retry_limit=1,
                metadata={"local_verifier": "visible_screen"},
            ),
            PlanStep(
                id="verify_event",
                action="verify",
                target_description="current calendar",
                expected_state=f"The calendar visibly contains event title {title!r} around {event_time!r}.",
                retry_limit=1,
                metadata={
                    "local_verifier": "calendar_event_visible",
                    "event_title": title,
                    "event_time": event_time,
                    "event_date": event_date,
                    "start_time": start_time,
                    "end_time": end_time,
                    "attendees": attendees,
                },
            ),
        ]
    )
    return TestPlan(
        goal=case.instruction,
        product="calendar",
        steps=steps,
        success_criteria=[
            f"Calendar event editor is used only when CUA_LARK_ALLOW_CALENDAR_CREATE=true.",
            f"Event title {title!r} and time {event_time!r} are visible after saving.",
        ],
        assumptions=[
            "Feishu/Lark is already installed and logged in.",
            "Use a harmless test event before trying real work calendars.",
            "Attendees are parsed but not filled unless CUA_LARK_ALLOW_CALENDAR_INVITE=true.",
        ],
        raw_model_output={"provider": "product_template", "template": "calendar_create_event_guarded"},
    )


def _calendar_time_parts(raw_time: str) -> tuple[str, str, str]:
    now = datetime.now()
    event_date = now + timedelta(days=1 if "明天" in raw_time else 0)
    start_hour = 10
    start_minute = 0
    import re

    match = re.search(r"(\d{1,2}):(\d{2})", raw_time)
    if match:
        start_hour = int(match.group(1))
        start_minute = int(match.group(2))
    start_dt = event_date.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
    end_dt = start_dt + timedelta(minutes=30)
    return start_dt.strftime("%Y-%m-%d"), start_dt.strftime("%H:%M"), end_dt.strftime("%H:%M")
