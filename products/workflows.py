from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from app.config import settings
from core.schemas import PlanStep, TestCase, TestPlan


def build_product_plan(case: TestCase) -> TestPlan | None:
    """Return deterministic plans for guarded demos and smoke checks.

    These templates keep the fast, safe demo path out of the VLM client while
    still allowing generic natural-language cases to fall back to the model.
    """

    template = str(case.metadata.get("plan_template") or "").strip()
    if template == "im_send_message_guarded":
        return _im_send_message_guarded_plan(case)
    if template == "im_send_image_guarded":
        return _im_send_image_guarded_plan(case)
    if template == "im_mention_user_guarded":
        return _im_mention_user_guarded_plan(case)
    if template == "im_search_messages_guarded":
        return _im_search_messages_guarded_plan(case)
    if template == "im_create_group_guarded":
        return _im_create_group_guarded_plan(case)
    if template == "im_emoji_reaction_guarded":
        return _im_emoji_reaction_guarded_plan(case)
    if template in {"safe_smoke", "im_search_only"} or (case.metadata.get("safe_smoke") and not template):
        return _im_search_only_plan(case)
    if template in {"docs_open_smoke", "docs_smoke"}:
        return _docs_open_smoke_plan(case)
    if template == "docs_create_doc_guarded":
        return _docs_create_doc_guarded_plan(case)
    if template == "docs_rich_edit_guarded":
        return _docs_rich_edit_guarded_plan(case)
    if template == "docs_share_doc_guarded":
        return _docs_share_doc_guarded_plan(case)
    if template == "calendar_create_event_guarded":
        return _calendar_create_event_guarded_plan(case)
    if template == "calendar_invite_attendee_guarded":
        return _calendar_invite_attendee_guarded_plan(case)
    if template == "calendar_modify_event_time_guarded":
        return _calendar_modify_event_time_guarded_plan(case)
    if template == "calendar_view_busy_free_guarded":
        return _calendar_view_busy_free_guarded_plan(case)
    if template == "vc_start_meeting_guarded":
        return _vc_start_meeting_guarded_plan(case)
    if template == "vc_join_meeting_guarded":
        return _vc_join_meeting_guarded_plan(case)
    if template == "vc_toggle_devices_guarded":
        return _vc_toggle_devices_guarded_plan(case)
    return None


def _im_search_only_plan(case: TestCase) -> TestPlan:
    search_text = str(case.metadata.get("search_text") or "harmless-smoke-test")
    return TestPlan(
        goal=case.instruction,
        product="im",
        steps=[
            PlanStep(
                id="dismiss_stale_im_search_overlay",
                action="conditional_hotkey",
                hotkeys=["esc"],
                expected_state="Any stale Feishu global search overlay is dismissed before opening IM.",
                retry_limit=1,
                metadata={"local_verifier": "visible_screen", "locator_strategy": "search_dialog_input"},
            ),
            PlanStep(
                id="open_im",
                action="click",
                target_description="Feishu/Lark desktop window",
                expected_state="Feishu IM is visible.",
                retry_limit=2,
                metadata={"local_verifier": "im_open", "locator_strategy": "im_sidebar_entry", "locator_kind": "button"},
            ),
            PlanStep(
                id="focus_search",
                action="click",
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
    target = _im_target(case)
    message = str(case.metadata.get("message") or "CUA-Lark guarded smoke message")
    return TestPlan(
        goal=case.instruction,
        product="im",
        steps=[
            PlanStep(
                id="dismiss_stale_im_search_overlay",
                action="conditional_hotkey",
                hotkeys=["esc"],
                expected_state="Any stale Feishu global search overlay is dismissed before opening IM.",
                retry_limit=1,
                metadata={"local_verifier": "visible_screen", "locator_strategy": "search_dialog_input"},
            ),
            PlanStep(
                id="open_im",
                action="click",
                target_description="Feishu IM sidebar entry",
                expected_state="Feishu IM is open and visible.",
                retry_limit=1,
                metadata={"local_verifier": "im_open", "locator_strategy": "im_sidebar_entry", "locator_kind": "button"},
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
                id="wait_search_results",
                action="wait",
                wait_seconds=1.0,
                expected_state="IM search results have had time to populate.",
                retry_limit=1,
                metadata={"local_verifier": "visible_screen"},
            ),
            PlanStep(
                id="select_group_results",
                action="conditional_click",
                target_description="group or conversation results tab",
                expected_state="Group/conversation search results are selected when the tab is visible.",
                retry_limit=1,
                metadata={
                    "local_verifier": "visible_screen",
                    "locator_strategy": "im_search_group_tab",
                    "locator_kind": "button",
                },
            ),
            PlanStep(
                id="open_chat",
                action="click",
                target_description=f"first matching test chat result for {target}",
                expected_state=f"The chat conversation header is the target test chat {target!r}.",
                retry_limit=2,
                metadata={
                    "local_verifier": "im_chat_opened",
                    "requires_send_guard": True,
                    "locator_strategy": "search_first_result",
                    "guard_phase": "open_chat",
                    "recover_to_step_id": "focus_search",
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


def _im_send_image_guarded_plan(case: TestCase) -> TestPlan:
    target = _im_target(case)
    message = str(case.metadata.get("message") or "").strip()
    image_path = _im_image_path(case)
    steps = _im_open_chat_steps(target, guard_key="requires_image_send_guard")
    if message:
        steps.append(
            PlanStep(
                id="type_image_caption",
                action="type_text",
                target_description="current chat message input focus",
                input_text=message,
                expected_state="Optional image caption is drafted in the input box.",
                retry_limit=1,
                metadata={
                    "local_verifier": "im_message_drafted",
                    "requires_image_send_guard": True,
                    "target": target,
                    "clear_before_type": True,
                    "use_current_focus": True,
                },
            )
        )
    steps.extend(
        [
            PlanStep(
                id="paste_image",
                action="paste_image",
                target_description="current chat message input focus",
                input_text=image_path,
                expected_state="Image is pasted into the current chat input as a pending attachment.",
                retry_limit=1,
                metadata={
                    "local_verifier": "im_image_drafted",
                    "requires_image_send_guard": True,
                    "target": target,
                    "image_path": image_path,
                    "use_current_focus": True,
                },
            ),
            PlanStep(
                id="send_image",
                action="hotkey",
                hotkeys=["enter"],
                expected_state=f"Image is sent to the allowed test chat {target!r}.",
                retry_limit=1,
                metadata={
                    "local_verifier": "im_image_sent",
                    "requires_image_send_guard": True,
                    "dangerous_image_send": True,
                    "target": target,
                    "image_path": image_path,
                },
            ),
            PlanStep(
                id="verify_image",
                action="verify",
                target_description="latest chat image message",
                expected_state=f"Latest chat history in {target!r} contains the sent test image.",
                retry_limit=1,
                metadata={"local_verifier": "im_image_visible", "target": target},
            ),
        ]
    )
    return TestPlan(
        goal=case.instruction,
        product="im",
        steps=steps,
        success_criteria=[
            f"Target test chat {target!r} is opened.",
            f"Image {image_path!r} is sent only when CUA_LARK_ALLOW_SEND_IMAGE=true.",
        ],
        assumptions=["Image send uses the Windows clipboard and is guarded by explicit environment policy."],
        raw_model_output={"provider": "product_template", "template": "im_send_image_guarded"},
    )


def _im_mention_user_guarded_plan(case: TestCase) -> TestPlan:
    target = _im_target(case)
    mention_user = str(case.metadata.get("mention_user") or "李新元")
    message = str(case.metadata.get("message") or f"@{mention_user} hello from CUA")
    steps = _im_open_chat_steps(target, guard_key="requires_send_guard")
    steps.extend(
        [
            PlanStep(
                id="type_mention_trigger",
                action="type_text",
                target_description="current chat message input focus",
                input_text=f"@{mention_user}",
                expected_state=f"Mention suggestion list for {mention_user!r} is visible.",
                retry_limit=1,
                metadata={
                    "local_verifier": "im_mention_suggestions_visible",
                    "requires_send_guard": True,
                    "target": target,
                    "mention_user": mention_user,
                    "clear_before_type": True,
                    "use_current_focus": True,
                },
            ),
            PlanStep(
                id="select_mention_candidate",
                action="click",
                target_description=f"mention suggestion row for {mention_user}",
                expected_state=f"Mention candidate {mention_user!r} is selected into the draft.",
                retry_limit=1,
                metadata={
                    "local_verifier": "im_mention_selected",
                    "requires_send_guard": True,
                    "locator_strategy": "im_mention_suggestion_row",
                    "target": target,
                    "mention_user": mention_user,
                },
            ),
            PlanStep(
                id="type_mention_message",
                action="type_text",
                target_description="current chat message input focus after mention selection",
                input_text=_strip_mention_prefix(message, mention_user),
                expected_state="Mention message body is drafted.",
                retry_limit=1,
                metadata={
                    "local_verifier": "im_message_drafted",
                    "requires_send_guard": True,
                    "target": target,
                    "mention_user": mention_user,
                    "use_current_focus": True,
                },
            ),
            PlanStep(
                id="send_mention_message",
                action="hotkey",
                hotkeys=["enter"],
                expected_state=f"@ mention message is sent to {target!r}.",
                retry_limit=1,
                metadata={
                    "local_verifier": "im_mention_sent",
                    "requires_send_guard": True,
                    "dangerous_send": True,
                    "target": target,
                    "mention_user": mention_user,
                    "message": message,
                },
            ),
            PlanStep(
                id="verify_mention_message",
                action="verify",
                target_description="latest @ mention message",
                expected_state=f"Latest chat history contains an @ mention for {mention_user!r}.",
                retry_limit=1,
                metadata={"local_verifier": "im_mention_visible", "target": target, "mention_user": mention_user},
            ),
        ]
    )
    return TestPlan(
        goal=case.instruction,
        product="im",
        steps=steps,
        success_criteria=[
            f"Target test chat {target!r} is opened.",
            f"Mention user {mention_user!r} is OCR-confirmed before click.",
        ],
        assumptions=["Mention send is guarded by CUA_LARK_ALLOW_SEND_MESSAGE and optional target allow-list."],
        raw_model_output={"provider": "product_template", "template": "im_mention_user_guarded"},
    )


def _im_search_messages_guarded_plan(case: TestCase) -> TestPlan:
    search_text = str(case.metadata.get("search_text") or "hello from CUA")
    return TestPlan(
        goal=case.instruction,
        product="im",
        steps=[
            PlanStep(
                id="dismiss_stale_im_search_overlay",
                action="conditional_hotkey",
                hotkeys=["esc"],
                expected_state="Any stale Feishu global search overlay is dismissed before opening IM.",
                retry_limit=1,
                metadata={"local_verifier": "visible_screen", "locator_strategy": "search_dialog_input"},
            ),
            PlanStep(
                id="open_im",
                action="click",
                target_description="Feishu IM sidebar entry",
                expected_state="Feishu IM is open and visible.",
                retry_limit=1,
                metadata={"local_verifier": "im_open", "locator_strategy": "im_sidebar_entry", "locator_kind": "button"},
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
                id="type_history_query",
                action="type_text",
                target_description="search box",
                input_text=search_text,
                expected_state="Message-history query is entered into search.",
                retry_limit=1,
                metadata={
                    "local_verifier": "im_search_text_entered",
                    "locator_strategy": "search_dialog_input",
                    "search_text": search_text,
                    "clear_before_type": True,
                    "safe_no_send": True,
                },
            ),
            PlanStep(
                id="open_message_results",
                action="conditional_click",
                target_description="message or chat-history result tab",
                expected_state="Message-history results are selected if a results tab is visible.",
                retry_limit=1,
                metadata={
                    "local_verifier": "visible_screen",
                    "locator_strategy": "im_search_history_tab",
                    "locator_kind": "button",
                },
            ),
            PlanStep(
                id="observe_history_results",
                action="wait",
                wait_seconds=1.0,
                expected_state="Search results for message history are visible.",
                retry_limit=1,
                metadata={"local_verifier": "im_search_history_visible", "search_text": search_text},
            ),
            PlanStep(
                id="verify_no_send",
                action="verify",
                target_description="current screen",
                expected_state="No chat message was sent while searching message history.",
                retry_limit=1,
                metadata={"local_verifier": "no_send"},
            ),
        ],
        success_criteria=[
            f"Message-history search results for {search_text!r} are visible.",
            "No chat message is sent.",
        ],
        assumptions=["This is a non-mutating IM search-history workflow."],
        raw_model_output={"provider": "product_template", "template": "im_search_messages_guarded"},
    )


def _im_create_group_guarded_plan(case: TestCase) -> TestPlan:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    group_name = str(case.metadata.get("group_name") or f"CUA-Lark test group {stamp}")
    members = [str(item) for item in case.metadata.get("group_members", []) if str(item).strip()] or ["李新元"]
    first_member = members[0]
    return TestPlan(
        goal=case.instruction,
        product="im",
        steps=[
            PlanStep(
                id="open_im",
                action="click",
                target_description="Feishu IM sidebar entry",
                expected_state="Feishu IM is open and visible.",
                retry_limit=1,
                metadata={"local_verifier": "im_open", "locator_strategy": "im_sidebar_entry", "locator_kind": "button"},
            ),
            PlanStep(
                id="dismiss_search_overlay_for_group_create",
                action="conditional_hotkey",
                hotkeys=["esc"],
                expected_state="Any stale IM search overlay is dismissed before opening the new-chat menu.",
                retry_limit=1,
                metadata={"local_verifier": "visible_screen", "locator_strategy": "search_dialog_input"},
            ),
            PlanStep(
                id="click_new_chat",
                action="click",
                target_description="IM new chat or plus button",
                expected_state="New chat menu is visible.",
                retry_limit=1,
                metadata={
                    "local_verifier": "visible_screen",
                    "requires_group_create_guard": True,
                    "locator_strategy": "im_new_chat_button",
                    "locator_kind": "button",
                    "group_members": members,
                },
            ),
            PlanStep(
                id="click_create_group",
                action="click",
                target_description="create group menu item",
                expected_state="Group creation dialog starts opening.",
                retry_limit=1,
                metadata={
                    "local_verifier": "visible_screen",
                    "requires_group_create_guard": True,
                    "locator_strategy": "im_create_group_option",
                    "locator_kind": "button",
                    "group_members": members,
                },
            ),
            PlanStep(
                id="wait_group_create_dialog",
                action="wait",
                wait_seconds=4.0,
                expected_state="Group creation dialog has finished loading.",
                retry_limit=1,
                metadata={
                    "local_verifier": "im_group_create_dialog_opened",
                    "requires_group_create_guard": True,
                    "group_members": members,
                },
            ),
            PlanStep(
                id="type_group_member",
                action="type_text",
                target_description="group member search input",
                input_text=first_member,
                expected_state=f"Member search results contain {first_member!r}.",
                retry_limit=1,
                metadata={
                    "local_verifier": "im_group_member_search_entered",
                    "requires_group_create_guard": True,
                    "locator_strategy": "im_group_member_input",
                    "locator_kind": "text_input",
                    "member": first_member,
                    "group_members": members,
                    "clear_before_type": True,
                },
            ),
            PlanStep(
                id="select_group_member",
                action="click",
                target_description=f"group member search result for {first_member}",
                expected_state=f"Member {first_member!r} is selected.",
                retry_limit=1,
                metadata={
                    "local_verifier": "im_group_member_selected",
                    "requires_group_create_guard": True,
                    "locator_strategy": "im_group_member_result",
                    "locator_kind": "button",
                    "member": first_member,
                    "group_members": members,
                },
            ),
            PlanStep(
                id="type_group_name",
                action="type_text",
                target_description="group name input",
                input_text=group_name,
                expected_state=f"Group name field contains {group_name!r}.",
                retry_limit=1,
                metadata={
                    "local_verifier": "im_group_name_entered",
                    "requires_group_create_guard": True,
                    "locator_strategy": "im_group_name_input",
                    "locator_kind": "text_input",
                    "group_name": group_name,
                    "group_members": members,
                    "clear_before_type": True,
                },
            ),
            PlanStep(
                id="confirm_create_group",
                action="click",
                target_description="confirm create group button",
                expected_state=f"Test group {group_name!r} is created.",
                retry_limit=1,
                metadata={
                    "local_verifier": "im_group_created",
                    "requires_group_create_guard": True,
                    "dangerous_group_create": True,
                    "locator_strategy": "im_group_create_confirm_button",
                    "locator_kind": "button",
                    "group_name": group_name,
                    "group_members": members,
                },
            ),
            PlanStep(
                id="verify_group_created",
                action="verify",
                target_description="new group chat header",
                expected_state=f"New test group header contains {group_name!r}.",
                retry_limit=1,
                metadata={"local_verifier": "im_group_visible", "group_name": group_name, "group_members": members},
            ),
        ],
        success_criteria=[
            f"Group {group_name!r} is created only when CUA_LARK_ALLOW_CREATE_GROUP=true.",
            f"Configured member allow-list permits members: {members!r}.",
        ],
        assumptions=["Group creation is a real side effect; use only harmless test members and cleanup manually if needed."],
        raw_model_output={"provider": "product_template", "template": "im_create_group_guarded"},
    )


def _im_emoji_reaction_guarded_plan(case: TestCase) -> TestPlan:
    target = _im_target(case)
    search_text = str(case.metadata.get("search_text") or "hello from CUA")
    emoji_name = str(case.metadata.get("emoji_name") or "鐐硅禐")
    steps = _im_open_chat_steps(target, guard_key="requires_emoji_reaction_guard")
    steps.extend(
        [
            PlanStep(
                id="find_reaction_message",
                action="hover",
                target_description=f"visible message row containing {search_text}",
                expected_state="Target message row is focused or hovered for reaction controls.",
                wait_seconds=0.5,
                retry_limit=1,
                metadata={
                    "local_verifier": "visible_screen",
                    "requires_emoji_reaction_guard": True,
                    "locator_strategy": "im_message_row_by_text",
                    "locator_kind": "message_entry",
                    "target": target,
                    "search_text": search_text,
                },
            ),
            PlanStep(
                id="cancel_reply_context_if_visible",
                action="conditional_hotkey",
                target_description="visible IM reply context bar",
                hotkeys=["esc"],
                expected_state="Stale reply context is dismissed if it is visible.",
                retry_limit=1,
                metadata={
                    "local_verifier": "visible_screen",
                    "requires_emoji_reaction_guard": True,
                    "locator_strategy": "im_reply_context_bar",
                    "locator_kind": "panel",
                    "target": target,
                },
            ),
            PlanStep(
                id="hover_reaction_message",
                action="hover",
                target_description=f"visible message row containing {search_text}",
                expected_state="Reaction quick-action toolbar is visible near the target message.",
                wait_seconds=0.5,
                retry_limit=1,
                metadata={
                    "local_verifier": "visible_screen",
                    "requires_emoji_reaction_guard": True,
                    "locator_strategy": "im_message_row_by_text",
                    "locator_kind": "message_entry",
                    "target": target,
                    "search_text": search_text,
                },
            ),
            PlanStep(
                id="apply_quick_reaction",
                action="click",
                target_description=f"quick emoji reaction button {emoji_name}",
                expected_state=f"Emoji reaction {emoji_name!r} is applied.",
                retry_limit=1,
                metadata={
                    "local_verifier": "im_emoji_reaction_applied",
                    "requires_emoji_reaction_guard": True,
                    "dangerous_emoji_reaction": True,
                    "locator_strategy": "im_quick_reaction_button",
                    "locator_kind": "button",
                    "require_lark_locator": True,
                    "target": target,
                    "search_text": search_text,
                    "emoji_name": emoji_name,
                },
            ),
            PlanStep(
                id="verify_reaction",
                action="verify",
                target_description="emoji reaction marker on message",
                expected_state=f"Message row visibly contains reaction {emoji_name!r}.",
                retry_limit=1,
                metadata={"local_verifier": "im_emoji_reaction_visible", "target": target, "emoji_name": emoji_name},
            ),
        ]
    )
    return TestPlan(
        goal=case.instruction,
        product="im",
        steps=steps,
        success_criteria=[
            f"Target chat {target!r} is opened.",
            f"Emoji reaction {emoji_name!r} is applied only when CUA_LARK_ALLOW_EMOJI_REACTION=true.",
        ],
        assumptions=["Reaction controls are visually located because their positions vary by message row."],
        raw_model_output={"provider": "product_template", "template": "im_emoji_reaction_guarded"},
    )


def _im_open_chat_steps(target: str, guard_key: str) -> list[PlanStep]:
    return [
        PlanStep(
            id="dismiss_stale_im_search_overlay",
            action="conditional_hotkey",
            hotkeys=["esc"],
            expected_state="Any stale Feishu global search overlay is dismissed before opening IM.",
            retry_limit=1,
            metadata={"local_verifier": "visible_screen", "locator_strategy": "search_dialog_input"},
        ),
        PlanStep(
            id="open_im",
            action="click",
            target_description="Feishu IM sidebar entry",
            expected_state="Feishu IM is open and visible.",
            retry_limit=1,
            metadata={"local_verifier": "im_open", "locator_strategy": "im_sidebar_entry", "locator_kind": "button"},
        ),
        PlanStep(
            id="dismiss_stale_im_overlay",
            action="conditional_hotkey",
            hotkeys=["esc"],
            expected_state="Any stale IM menu, search overlay, or popup from a previous run is dismissed.",
            retry_limit=1,
            metadata={"local_verifier": "visible_screen", "locator_strategy": "search_dialog_input"},
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
            id="wait_search_results",
            action="wait",
            wait_seconds=1.0,
            expected_state="IM search results have had time to populate.",
            retry_limit=1,
            metadata={"local_verifier": "visible_screen"},
        ),
        PlanStep(
            id="select_group_results",
            action="conditional_click",
            target_description="group or conversation results tab",
            expected_state="Group/conversation search results are selected when the tab is visible.",
            retry_limit=1,
            metadata={
                "local_verifier": "visible_screen",
                "locator_strategy": "im_search_group_tab",
                "locator_kind": "button",
            },
        ),
        PlanStep(
            id="open_chat",
            action="click",
            target_description=f"first matching test chat result for {target}",
            expected_state=f"The chat conversation header is the target test chat {target!r}.",
            retry_limit=2,
            metadata={
                "local_verifier": "im_chat_opened",
                guard_key: True,
                "locator_strategy": "search_first_result",
                "guard_phase": "open_chat",
                "recover_to_step_id": "focus_search",
                "target": target,
            },
        ),
    ]


def _im_target(case: TestCase) -> str:
    return str(case.metadata.get("target") or settings.allowed_im_target or "测试群")


def _im_image_path(case: TestCase) -> str:
    configured = str(case.metadata.get("image_path") or settings.im_test_image_path or "").strip()
    if configured:
        return configured
    return str(Path(__file__).resolve().parents[1] / "assets" / "im_test_image.png")


def _strip_mention_prefix(message: str, mention_user: str) -> str:
    cleaned = message.replace(f"@{mention_user}", "", 1).strip()
    return f" {cleaned}" if cleaned else " hello from CUA"


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
    body = str(case.metadata.get("doc_body") or "This is a safe CUA-Lark test body.")
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
                    "dry_run_simulated_target": True,
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
                    "foreground_window_keywords": ["飞书云文档", "未命名文档", "Docs", "wiki", "feishu"],
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
                metadata={"local_verifier": "docs_editor_ready", "preserve_foreground": True},
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
                    "locator_strategy": "docs_title_input",
                    "locator_kind": "text_input",
                    "foreground_window_keywords": ["飞书云文档", "未命名文档", "Docs", "wiki", "feishu"],
                    "doc_title": title,
                    "clear_before_type": True,
                    "preserve_foreground": True,
                    "recover_to_step_id": "type_doc_title",
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
                    "locator_strategy": "docs_body_input",
                    "locator_kind": "text_input",
                    "preserve_foreground": True,
                    "recover_to_step_id": "move_to_doc_body",
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


def _docs_rich_edit_guarded_plan(case: TestCase) -> TestPlan:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    title = str(case.metadata.get("doc_title") or f"CUA-Lark rich edit test {stamp}")
    body = str(case.metadata.get("doc_body") or "Docs rich-edit smoke body.")
    heading = str(case.metadata.get("doc_heading") or "CUA Docs Heading")
    raw_items = case.metadata.get("doc_list_items") or ["first list item", "second list item"]
    list_items = [str(item) for item in raw_items if str(item).strip()]
    rich_text = "\n".join(["", f"# {heading}", *(f"- {item}" for item in list_items)])

    base_case = case.model_copy(update={"metadata": {**case.metadata, "doc_title": title, "doc_body": body}})
    plan = _docs_create_doc_guarded_plan(base_case)
    insert_at = max(0, len(plan.steps) - 1)
    plan.steps[insert_at:insert_at] = [
        PlanStep(
            id="insert_doc_heading_and_list",
            action="type_text",
            target_description="current Docs body editor",
            input_text=rich_text,
            expected_state=f"Docs body contains heading {heading!r} and list items.",
            retry_limit=1,
            metadata={
                "local_verifier": "docs_rich_content_entered",
                "requires_doc_create_guard": True,
                "doc_title": title,
                "doc_body": body,
                "doc_heading": heading,
                "doc_list_items": list_items,
                "locator_strategy": "docs_body_input",
                "locator_kind": "text_input",
                "preserve_foreground": True,
            },
        ),
        PlanStep(
            id="verify_doc_rich_content",
            action="verify",
            target_description="current rich Docs document",
            expected_state=f"The current document visibly contains heading {heading!r} and list items.",
            retry_limit=1,
            metadata={
                "local_verifier": "docs_rich_content_visible",
                "doc_title": title,
                "doc_body": body,
                "doc_heading": heading,
                "doc_list_items": list_items,
                "preserve_foreground": True,
            },
        ),
    ]
    plan.goal = case.instruction
    plan.raw_model_output = {"provider": "product_template", "template": "docs_rich_edit_guarded"}
    plan.success_criteria.append(f"Heading {heading!r} and list items {list_items!r} are visible.")
    return plan


def _docs_share_doc_guarded_plan(case: TestCase) -> TestPlan:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    title = str(case.metadata.get("doc_title") or f"CUA-Lark share test {stamp}")
    body = str(case.metadata.get("doc_body") or "Docs sharing smoke body.")
    recipient = str(case.metadata.get("share_recipient") or "李新元")
    base_case = case.model_copy(update={"metadata": {**case.metadata, "doc_title": title, "doc_body": body}})
    plan = _docs_create_doc_guarded_plan(base_case)
    plan.steps.extend(
        [
            PlanStep(
                id="open_doc_share",
                action="click",
                target_description="Docs share button",
                expected_state="Docs share dialog is opened.",
                retry_limit=1,
                metadata={
                    "local_verifier": "docs_share_dialog_opened",
                    "requires_doc_share_guard": True,
                    "locator_strategy": "docs_share_button",
                    "locator_kind": "button",
                    "share_recipient": recipient,
                    "preserve_foreground": True,
                },
            ),
            PlanStep(
                id="wait_doc_share_dialog",
                action="wait",
                wait_seconds=2.5,
                expected_state="Docs share dialog content has loaded.",
                retry_limit=1,
                metadata={
                    "local_verifier": "docs_share_dialog_opened",
                    "requires_doc_share_guard": True,
                    "share_recipient": recipient,
                    "preserve_foreground": True,
                },
            ),
            PlanStep(
                id="type_doc_share_recipient",
                action="type_text",
                target_description="Docs share recipient input",
                input_text=recipient,
                expected_state=f"Docs share recipient input contains {recipient!r}.",
                retry_limit=1,
                metadata={
                    "local_verifier": "docs_share_recipient_entered",
                    "requires_doc_share_guard": True,
                    "locator_strategy": "docs_share_recipient_input",
                    "locator_kind": "text_input",
                    "share_recipient": recipient,
                    "clear_before_type": True,
                    "require_lark_locator": True,
                    "preserve_foreground": True,
                },
            ),
            PlanStep(
                id="wait_doc_share_recipient_results",
                action="wait",
                wait_seconds=1.5,
                expected_state=f"Docs share search results for {recipient!r} have loaded.",
                retry_limit=1,
                metadata={
                    "local_verifier": "visible_screen",
                    "requires_doc_share_guard": True,
                    "share_recipient": recipient,
                    "preserve_foreground": True,
                },
            ),
            PlanStep(
                id="select_doc_share_recipient",
                action="conditional_click",
                target_description=f"Docs share recipient result {recipient}",
                expected_state=f"Recipient {recipient!r} is selected for sharing.",
                retry_limit=3,
                metadata={
                    "local_verifier": "visible_screen",
                    "requires_doc_share_guard": True,
                    "locator_strategy": "docs_share_recipient_result",
                    "locator_kind": "button",
                    "share_recipient": recipient,
                    "require_lark_locator": True,
                    "preserve_foreground": True,
                },
            ),
            PlanStep(
                id="add_doc_share_recipient",
                action="conditional_click",
                target_description="Docs share add recipient plus button",
                expected_state=f"Recipient {recipient!r} is added to the share collaborator list.",
                retry_limit=2,
                metadata={
                    "local_verifier": "visible_screen",
                    "requires_doc_share_guard": True,
                    "locator_strategy": "docs_share_add_recipient_button",
                    "locator_kind": "button",
                    "share_recipient": recipient,
                    "require_lark_locator": True,
                    "skip_if_docs_share_recipient_ready_for_send": True,
                    "preserve_foreground": True,
                },
            ),
            PlanStep(
                id="wait_doc_share_recipient_added",
                action="wait",
                wait_seconds=1.0,
                expected_state=f"Recipient {recipient!r} remains added for sharing.",
                retry_limit=1,
                metadata={
                    "local_verifier": "visible_screen",
                    "requires_doc_share_guard": True,
                    "share_recipient": recipient,
                    "preserve_foreground": True,
                },
            ),
            PlanStep(
                id="confirm_doc_share",
                action="click",
                target_description="Docs share confirm button",
                expected_state=f"Document share invitation is sent or applied for {recipient!r}.",
                retry_limit=2,
                metadata={
                    "local_verifier": "visible_screen",
                    "requires_doc_share_guard": True,
                    "dangerous_doc_share": True,
                    "locator_strategy": "docs_share_confirm_button",
                    "locator_kind": "button",
                    "share_recipient": recipient,
                    "require_lark_locator": True,
                    "preserve_foreground": True,
                },
            ),
            PlanStep(
                id="wait_after_doc_share_send",
                action="wait",
                wait_seconds=3.0,
                expected_state=f"Document share invitation has finished sending for {recipient!r}.",
                retry_limit=1,
                metadata={
                    "local_verifier": "visible_screen",
                    "requires_doc_share_guard": True,
                    "share_recipient": recipient,
                    "preserve_foreground": True,
                },
            ),
            PlanStep(
                id="verify_doc_share_completed",
                action="verify",
                target_description="Docs share completion state",
                expected_state=f"Document share invitation has completed for {recipient!r}.",
                retry_limit=1,
                metadata={
                    "local_verifier": "docs_shared",
                    "requires_doc_share_guard": True,
                    "share_recipient": recipient,
                    "preserve_foreground": True,
                },
            ),
        ]
    )
    plan.goal = case.instruction
    plan.raw_model_output = {"provider": "product_template", "template": "docs_share_doc_guarded"}
    plan.success_criteria.append(f"Share recipient {recipient!r} is used only when CUA_LARK_ALLOW_DOC_SHARE=true.")
    return plan


def _calendar_create_event_guarded_plan(case: TestCase) -> TestPlan:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    title = str(case.metadata.get("event_title") or f"CUA-Lark calendar test {stamp}")
    raw_event_time = str(case.metadata.get("event_time") or "").strip()
    has_event_time = bool(raw_event_time)
    event_time = raw_event_time
    event_date, start_time, end_time = _calendar_time_parts(event_time) if has_event_time else ("", "", "")
    attendees = [str(item) for item in case.metadata.get("attendees", []) if str(item).strip()]
    attendees_text = ", ".join(attendees)
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
            id="dismiss_calendar_blockers",
            action="conditional_hotkey",
            hotkeys=["esc"],
            expected_state="A stale Calendar detail card, assistant panel, or modal blocker is dismissed only when present.",
            retry_limit=1,
            metadata={
                "local_verifier": "visible_screen",
                "locator_strategy": "calendar_blocking_panel",
                "require_lark_locator": True,
            },
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
            id="refocus_lark_after_calendar_cleanup",
            action="focus_window",
            target_description="Feishu/Lark desktop window after stale Calendar editor cleanup",
            expected_state="Feishu/Lark is foreground before Calendar sidebar navigation.",
            retry_limit=1,
            metadata={"local_verifier": "lark_focused", "foreground_window_keywords": ["飞书", "Feishu", "Lark"]},
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
            retry_limit=2,
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
            wait_seconds=3.0,
            expected_state="Calendar event editor has finished loading.",
            retry_limit=3,
            metadata={"local_verifier": "calendar_editor_opened", "event_title": title},
        ),
        PlanStep(
            id="type_event_title",
            action="type_text",
            target_description="calendar event title field",
            input_text=title,
            expected_state=f"Calendar event title contains {title!r}.",
            retry_limit=2,
            metadata={
                "local_verifier": "calendar_title_entered",
                "requires_calendar_create_guard": True,
                "locator_strategy": "calendar_event_title_input",
                "locator_kind": "text_input",
                "event_title": title,
                "clear_before_type": True,
            },
        ),
    ]
    if has_event_time:
        steps.extend(
            [
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
                        "dry_run_simulated_target": True,
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
        )
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
        steps.append(
            PlanStep(
                id="select_event_attendee",
                action="click",
                target_description="calendar attendee search result",
                expected_state=f"Calendar attendee {attendees_text!r} is selected into the event.",
                retry_limit=1,
                metadata={
                    "local_verifier": "visible_screen",
                    "requires_calendar_create_guard": True,
                    "requires_calendar_invite_guard": True,
                    "locator_strategy": "calendar_attendee_result",
                    "locator_kind": "button",
                    "attendees": attendees,
                },
            )
        )
        steps.append(
            PlanStep(
                id="confirm_add_event_attendee",
                action="conditional_click",
                target_description="add participant dialog confirm button if shown",
                expected_state="If Feishu opens the add-participant dialog, the selected attendee is confirmed before saving.",
                retry_limit=1,
                metadata={
                    "local_verifier": "visible_screen",
                    "requires_calendar_create_guard": True,
                    "requires_calendar_invite_guard": True,
                    "locator_strategy": "calendar_add_participant_confirm_button",
                    "locator_kind": "button",
                    "attendees": attendees,
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
                id="confirm_calendar_create_confirmation",
                action="conditional_click",
                target_description="Calendar create confirmation confirm button if shown",
                expected_state="If Feishu asks for final create confirmation, the event creation is confirmed.",
                retry_limit=1,
                metadata={
                    "local_verifier": "visible_screen",
                    "requires_calendar_create_guard": True,
                    "dangerous_calendar_create": True,
                    "locator_strategy": "calendar_create_confirm_button",
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
        ]
    )
    if has_event_time:
        steps.extend(
            [
                PlanStep(
                    id="click_saved_event_view_date",
                    action="conditional_click",
                    target_description="Calendar current date selector after saving an event",
                    expected_state="Calendar date picker is opened if the saved event date is not already visible.",
                    retry_limit=1,
                    metadata={
                        "local_verifier": "visible_screen",
                        "locator_strategy": "calendar_view_date_button",
                        "locator_kind": "button",
                        "event_date": event_date,
                        "skip_if_event_date_visible": True,
                    },
                ),
                PlanStep(
                    id="click_saved_event_view_day",
                    action="conditional_click",
                    target_description=f"Calendar saved event day {event_date}",
                    expected_state=f"Calendar selects the saved event day {event_date}.",
                    retry_limit=1,
                    metadata={
                        "local_verifier": "calendar_visible",
                        "locator_strategy": "calendar_date_picker_day",
                        "locator_kind": "button",
                        "event_date": event_date,
                        "skip_if_event_date_visible": True,
                        "require_lark_locator": True,
                    },
                ),
                PlanStep(
                    id="scroll_saved_calendar_to_event_time",
                    action="scroll",
                    target_description=f"Calendar main time axis near {start_time}",
                    scroll_amount=None,
                    expected_state=f"Calendar time axis is scrolled near {start_time}.",
                    retry_limit=4,
                    metadata={
                        "local_verifier": "calendar_time_axis_target_visible",
                        "locator_strategy": "calendar_main_time_axis",
                        "locator_kind": "generic",
                        "event_title": title,
                        "event_date": event_date,
                        "start_time": start_time,
                    },
                ),
                PlanStep(
                    id="wait_after_saved_event_scroll",
                    action="wait",
                    wait_seconds=0.8,
                    expected_state="Calendar settles after scrolling to the saved event time.",
                    retry_limit=1,
                    metadata={"local_verifier": "visible_screen"},
                ),
            ]
        )
    verify_metadata = {
        "local_verifier": "calendar_event_visible",
        "event_title": title,
        "attendees": attendees,
    }
    if has_event_time:
        verify_metadata.update(
            {
                "event_time": event_time,
                "event_date": event_date,
                "start_time": start_time,
                "end_time": end_time,
            }
        )
    steps.append(
        PlanStep(
            id="verify_event",
            action="verify",
            target_description="current calendar",
            expected_state=(
                f"The calendar visibly contains event title {title!r} around {event_time!r}."
                if has_event_time
                else f"The calendar visibly contains event title {title!r}."
            ),
            retry_limit=1,
            metadata=verify_metadata,
        )
    )
    time_criterion = (
        f"Event title {title!r} and time {event_time!r} are visible after saving."
        if has_event_time
        else f"Event title {title!r} is visible after saving; no explicit time is set by the workflow."
    )
    return TestPlan(
        goal=case.instruction,
        product="calendar",
        steps=steps,
        success_criteria=[
            f"Calendar event editor is used only when CUA_LARK_ALLOW_CALENDAR_CREATE=true.",
            time_criterion,
        ],
        assumptions=[
            "Feishu/Lark is already installed and logged in.",
            "Use a harmless test event before trying real work calendars.",
            "Attendees are parsed but not filled unless CUA_LARK_ALLOW_CALENDAR_INVITE=true.",
        ],
        raw_model_output={"provider": "product_template", "template": "calendar_create_event_guarded"},
    )


def _calendar_invite_attendee_guarded_plan(case: TestCase) -> TestPlan:
    attendees = [str(item) for item in case.metadata.get("attendees", []) if str(item).strip()] or ["李新元"]
    base_case = case.model_copy(
        update={
            "metadata": {
                **case.metadata,
                "plan_template": "calendar_create_event_guarded",
                "event_title": case.metadata.get("event_title") or "CUA-Lark attendee invite test",
                "event_time": case.metadata.get("event_time") or "明天 10:00",
                "attendees": attendees,
            }
        }
    )
    plan = _calendar_create_event_guarded_plan(base_case)
    attendees_text = ", ".join(attendees)
    if attendees_text and not any(step.id == "type_event_attendees" for step in plan.steps):
        insert_at = next((idx for idx, step in enumerate(plan.steps) if step.id == "save_event"), len(plan.steps))
        plan.steps.insert(
            insert_at,
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
                    "requires_calendar_invite_guard": True,
                    "locator_strategy": "calendar_event_attendee_input",
                    "locator_kind": "text_input",
                    "attendees": attendees,
                    "clear_before_type": True,
                },
            ),
        )
    plan.goal = case.instruction
    plan.raw_model_output = {"provider": "product_template", "template": "calendar_invite_attendee_guarded"}
    plan.success_criteria.append(f"Attendees {attendees!r} are filled only when CUA_LARK_ALLOW_CALENDAR_INVITE=true.")
    return plan


def _calendar_modify_event_time_guarded_plan(case: TestCase) -> TestPlan:
    old_time = str(case.metadata.get("event_time") or "明天 10:00")
    new_time = str(case.metadata.get("new_event_time") or "明天 11:00")
    title = str(case.metadata.get("event_title") or "CUA-Lark modify time test")
    base_case = case.model_copy(
        update={
            "metadata": {
                **case.metadata,
                "plan_template": "calendar_create_event_guarded",
                "event_title": title,
                "event_time": old_time,
            }
        }
    )
    plan = _calendar_create_event_guarded_plan(base_case)
    new_date, new_start, new_end = _calendar_time_parts(new_time)
    insert_at = next((idx for idx, step in enumerate(plan.steps) if step.id == "save_event"), len(plan.steps))
    plan.steps[insert_at:insert_at] = [
        PlanStep(
            id="modify_event_start_time",
            action="type_text",
            target_description="calendar event start time field",
            input_text=new_start,
            expected_state=f"Calendar event start time is modified to {new_start!r}.",
            retry_limit=1,
            metadata={
                "local_verifier": "visible_screen",
                "requires_calendar_modify_guard": True,
                "locator_strategy": "calendar_event_start_time",
                "locator_kind": "text_input",
                "event_time": new_time,
                "new_event_time": new_time,
                "calendar_time_from_text": True,
                "clear_before_type": True,
                "double_click_before_type": True,
                "press_enter_after_type": True,
            },
        ),
        PlanStep(
            id="modify_event_end_time",
            action="type_text",
            target_description="calendar event end time field",
            input_text=new_end,
            expected_state=f"Calendar event end time is modified to {new_end!r}.",
            retry_limit=1,
            metadata={
                "local_verifier": "visible_screen",
                "requires_calendar_modify_guard": True,
                "locator_strategy": "calendar_event_end_time",
                "locator_kind": "text_input",
                "event_time": new_time,
                "new_event_time": new_time,
                "event_date": new_date,
                "start_time": new_start,
                "end_time": new_end,
                "calendar_time_from_text": True,
                "clear_before_type": True,
                "double_click_before_type": True,
                "press_enter_after_type": True,
            },
        ),
    ]
    for step in plan.steps:
        if step.id in {"save_event", "verify_event"}:
            step.metadata["event_time"] = new_time
            step.metadata["event_date"] = new_date
            step.metadata["start_time"] = new_start
            step.metadata["end_time"] = new_end
        if step.id == "save_event":
            step.metadata["dangerous_calendar_modify"] = True
    plan.goal = case.instruction
    plan.raw_model_output = {"provider": "product_template", "template": "calendar_modify_event_time_guarded"}
    plan.success_criteria.append(f"Event time is changed from {old_time!r} to {new_time!r} only when CUA_LARK_ALLOW_CALENDAR_MODIFY=true.")
    return plan


def _calendar_view_busy_free_guarded_plan(case: TestCase) -> TestPlan:
    attendees = [str(item) for item in case.metadata.get("attendees", []) if str(item).strip()] or ["李新元"]
    attendee_text = ", ".join(attendees)
    event_time = str(case.metadata.get("event_time") or "明天 10:00")
    event_date, start_time, _end_time = _calendar_time_parts(event_time)
    return TestPlan(
        goal=case.instruction,
        product="calendar",
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
                id="close_stale_calendar_editor",
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
                id="confirm_stale_calendar_editor_exit",
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
                id="cancel_stale_calendar_create_confirmation",
                action="conditional_click",
                target_description="Calendar create confirmation cancel button if shown",
                expected_state="A stale Calendar create confirmation is cancelled only when the dialog is visible.",
                retry_limit=1,
                metadata={
                    "local_verifier": "visible_screen",
                    "locator_strategy": "calendar_create_confirm_cancel_button",
                    "locator_kind": "button",
                },
            ),
            PlanStep(
                id="cancel_stale_add_participant_dialog",
                action="conditional_click",
                target_description="Calendar add-participant dialog cancel button if shown",
                expected_state="A stale Calendar add-participant dialog is cancelled only when it is visible.",
                retry_limit=1,
                metadata={
                    "local_verifier": "visible_screen",
                    "locator_strategy": "calendar_add_participant_cancel_button",
                    "locator_kind": "button",
                },
            ),
            PlanStep(
                id="close_stale_meeting_room_panel",
                action="conditional_click",
                target_description="Calendar meeting-room side panel back button if shown",
                expected_state="A stale Calendar meeting-room panel is closed only when it is visible.",
                retry_limit=1,
                metadata={
                    "local_verifier": "visible_screen",
                    "locator_strategy": "calendar_meeting_room_back_button",
                    "locator_kind": "button",
                },
            ),
            PlanStep(
                id="refocus_lark_after_calendar_cleanup",
                action="focus_window",
                target_description="Feishu/Lark desktop window after stale Calendar panel cleanup",
                expected_state="Feishu/Lark is foreground before Calendar sidebar navigation.",
                retry_limit=1,
                metadata={"local_verifier": "lark_focused"},
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
                expected_state="The main Calendar tab is selected.",
                retry_limit=1,
                metadata={"local_verifier": "calendar_visible", "locator_strategy": "calendar_main_tab", "locator_kind": "button"},
            ),
            PlanStep(
                id="focus_calendar_people_search",
                action="click",
                target_description="Calendar contact or public-calendar search box",
                expected_state="The Calendar people/calendar search box is focused.",
                retry_limit=1,
                metadata={
                    "local_verifier": "visible_screen",
                    "locator_strategy": "calendar_people_search_box",
                    "locator_kind": "text_input",
                    "require_lark_locator": True,
                },
            ),
            PlanStep(
                id="type_busy_free_contact",
                action="type_text",
                target_description="Calendar contact search box",
                input_text=attendee_text,
                expected_state=f"Calendar search results contain contact {attendee_text!r}.",
                retry_limit=1,
                metadata={
                    "local_verifier": "visible_screen",
                    "locator_strategy": "calendar_people_search_box",
                    "locator_kind": "text_input",
                    "attendees": attendees,
                    "clear_before_type": True,
                    "require_lark_locator": True,
                },
            ),
            PlanStep(
                id="wait_contact_results",
                action="wait",
                wait_seconds=1.5,
                expected_state="Calendar contact search results are visible.",
                retry_limit=1,
                metadata={"local_verifier": "visible_screen", "attendees": attendees, "event_time": event_time},
            ),
            PlanStep(
                id="select_busy_free_contact",
                action="conditional_click",
                target_description="Calendar contact search result for busy/free lookup",
                expected_state=f"Calendar for contact {attendee_text!r} is selected into the time axis when it is not already visible.",
                retry_limit=1,
                metadata={
                    "local_verifier": "visible_screen",
                    "locator_strategy": "calendar_people_search_result",
                    "locator_kind": "button",
                    "attendees": attendees,
                    "require_lark_locator": True,
                },
            ),
            PlanStep(
                id="expand_subscribed_calendars",
                action="conditional_click",
                target_description="Calendar subscribed calendars section",
                expected_state="The subscribed calendars section is expanded if it is currently collapsed.",
                retry_limit=1,
                metadata={
                    "local_verifier": "visible_screen",
                    "locator_strategy": "calendar_subscribed_section_header",
                    "locator_kind": "button",
                    "attendees": attendees,
                    "require_lark_locator": True,
                    "skip_if_calendar_busy_free_visible": True,
                },
            ),
            PlanStep(
                id="select_subscribed_busy_free_calendar",
                action="conditional_click",
                target_description="Subscribed Calendar entry for busy/free contact",
                expected_state=f"The subscribed calendar for {attendee_text!r} is checked into the time axis.",
                retry_limit=1,
                metadata={
                    "local_verifier": "visible_screen",
                    "locator_strategy": "calendar_subscribed_contact_row",
                    "locator_kind": "button",
                    "attendees": attendees,
                    "require_lark_locator": True,
                    "skip_if_calendar_busy_free_visible": True,
                },
            ),
            PlanStep(
                id="observe_busy_free_timeline",
                action="wait",
                wait_seconds=1.5,
                expected_state=f"Calendar time axis shows {attendee_text!r} around {event_time!r}.",
                retry_limit=1,
                metadata={
                    "local_verifier": "visible_screen",
                    "attendees": attendees,
                    "event_time": event_time,
                    "event_date": event_date,
                    "start_time": start_time,
                },
            ),
            PlanStep(
                id="scroll_calendar_to_event_time",
                action="scroll",
                target_description=f"Calendar busy/free time axis near {start_time}",
                scroll_amount=None,
                expected_state=f"Calendar busy/free time axis is scrolled to a readable area around {start_time}.",
                retry_limit=4,
                metadata={
                    "local_verifier": "calendar_time_axis_target_visible",
                    "locator_strategy": "calendar_main_time_axis",
                    "locator_kind": "generic",
                    "event_date": event_date,
                    "start_time": start_time,
                },
            ),
            PlanStep(
                id="wait_after_busy_free_scroll",
                action="wait",
                wait_seconds=0.8,
                expected_state="Calendar busy/free timeline settles after dynamic scroll calibration.",
                retry_limit=1,
                metadata={"local_verifier": "visible_screen"},
            ),
            PlanStep(
                id="verify_busy_free_timeline",
                action="verify",
                target_description="Calendar contact time axis",
                expected_state=f"Calendar busy/free time axis for {attendee_text!r} is visible at {event_time!r}.",
                retry_limit=1,
                metadata={
                    "local_verifier": "calendar_busy_free_visible",
                    "attendees": attendees,
                    "event_time": event_time,
                    "event_date": event_date,
                    "start_time": start_time,
                },
            ),
        ],
        success_criteria=[
            f"Calendar contact {attendee_text!r} is searched and selected from the Calendar UI.",
            f"The Calendar time axis for {event_date} {start_time} is observed without creating or saving an event.",
        ],
        assumptions=["Busy/free visibility depends on account permissions and whether the searched contact exposes calendar availability."],
        raw_model_output={"provider": "product_template", "template": "calendar_view_busy_free_guarded"},
    )


def _vc_start_meeting_guarded_plan(case: TestCase) -> TestPlan:
    steps = _vc_open_steps()
    has_device_request = _vc_has_device_request(case)
    meeting_title = str(case.metadata.get("meeting_title") or "").strip()
    steps.extend(
        [
            PlanStep(
                id="click_vc_start_meeting",
                action="click",
                target_description="Video meeting start button in Feishu",
                expected_state="The video meeting prejoin or in-meeting screen is visible.",
                retry_limit=2,
                metadata={
                    "local_verifier": "vc_prejoin_or_in_meeting",
                    "locator_strategy": "vc_start_meeting_button_fresh" if meeting_title else "vc_start_meeting_button",
                    "locator_kind": "button",
                    "requires_vc_start_guard": True,
                    "preserve_after_foreground": True,
                },
            ),
            PlanStep(
                id="allow_vc_permission",
                action="conditional_click",
                target_description="camera/microphone permission allow button if shown",
                expected_state="Camera/microphone permission prompt is accepted only if present.",
                retry_limit=1,
                metadata={
                    "local_verifier": "visible_screen",
                    "locator_strategy": "vc_permission_allow_button",
                    "locator_kind": "button",
                    "require_lark_locator": True,
                    "preserve_foreground": True,
                },
            ),
        ]
    )
    steps.append(
        PlanStep(
            id="wait_started_prejoin",
            action="wait",
            target_description="started meeting prejoin window",
            expected_state="The started meeting prejoin or meeting window is visible.",
            retry_limit=1,
            wait_seconds=0.8,
            metadata={"local_verifier": "vc_prejoin_or_in_meeting", "preserve_foreground": True},
        )
    )
    if meeting_title:
        steps.append(
            PlanStep(
                id="type_vc_meeting_title",
                action="type_text",
                target_description="video meeting title input",
                input_text=meeting_title,
                expected_state=f"Meeting title {meeting_title!r} is entered.",
                retry_limit=1,
                metadata={
                    "local_verifier": "vc_meeting_title_entered",
                    "locator_strategy": "vc_meeting_title_input",
                    "locator_kind": "text_input",
                    "meeting_title": meeting_title,
                    "clear_before_type": True,
                    "double_click_before_type": True,
                    "type_via_keyboard": meeting_title.isascii(),
                    "require_lark_locator": True,
                    "requires_vc_start_guard": True,
                    "preserve_foreground": True,
                },
            )
        )
    steps.append(
        PlanStep(
            id="confirm_start_meeting",
            action="conditional_click",
            target_description="prejoin start or join meeting button",
            expected_state="The video meeting room is visible.",
            retry_limit=2,
            metadata={
                "local_verifier": "vc_in_meeting",
                "locator_strategy": "vc_prejoin_join_button",
                "locator_kind": "button",
                "requires_vc_start_guard": True,
                "dangerous_vc_start": True,
                "preserve_foreground": True,
                "wait_after_action_seconds": 6,
            },
        )
    )
    if has_device_request:
        steps.extend(_vc_start_device_steps(case))
    steps.append(
        PlanStep(
            id="verify_vc_started",
            action="verify",
            target_description="created video meeting",
            expected_state="The video meeting is created; if devices were requested, the meeting room is active.",
            retry_limit=1,
            metadata={
                "local_verifier": "vc_device_state" if has_device_request else "vc_in_meeting",
                "desired_camera_on": case.metadata.get("desired_camera_on"),
                "desired_mic_on": case.metadata.get("desired_mic_on"),
                "preserve_foreground": True,
            },
        )
    )
    return TestPlan(
        goal=case.instruction,
        product="vc",
        steps=steps,
        success_criteria=[
            "Feishu Video Meeting screen is reached through the GUI.",
            "Meeting start is guarded by CUA_LARK_ALLOW_VC_START=true.",
            "Optional meeting title is entered before starting the meeting when provided.",
            "Requested camera/microphone states are handled after the meeting starts when provided.",
        ],
        assumptions=["The account can start a harmless test meeting and system camera/microphone permissions are available."],
        raw_model_output={"provider": "product_template", "template": "vc_start_meeting_guarded"},
    )


def _vc_join_meeting_guarded_plan(case: TestCase) -> TestPlan:
    meeting_id = str(settings.vc_meeting_id or case.metadata.get("meeting_id") or "259427455").strip()
    steps = _vc_open_steps()
    steps.extend(
        [
            PlanStep(
                id="click_vc_join_meeting",
                action="click",
                target_description="Video meeting join button in Feishu",
                expected_state="The meeting ID input screen is visible.",
                retry_limit=2,
                metadata={
                    "local_verifier": "vc_join_dialog_visible",
                    "locator_strategy": "vc_join_meeting_button",
                    "locator_kind": "button",
                    "requires_vc_join_guard": True,
                    "foreground_window_keywords": ["飞书", "Feishu", "Lark"],
                    "preserve_after_foreground": True,
                },
            ),
            PlanStep(
                id="type_vc_meeting_id",
                action="type_text",
                target_description="meeting ID input",
                input_text=meeting_id,
                expected_state=f"Meeting ID {meeting_id!r} is entered.",
                retry_limit=1,
                metadata={
                    "local_verifier": "vc_meeting_id_entered",
                    "locator_strategy": "vc_meeting_id_input",
                    "locator_kind": "text_input",
                    "meeting_id": meeting_id,
                    "clear_before_type": True,
                    "double_click_before_type": True,
                    "require_lark_locator": True,
                    "requires_vc_join_guard": True,
                    "preserve_foreground": True,
                },
            ),
            PlanStep(
                id="allow_vc_permission",
                action="conditional_click",
                target_description="camera/microphone permission allow button if shown",
                expected_state="Camera/microphone permission prompt is accepted only if present.",
                retry_limit=1,
                metadata={
                    "local_verifier": "visible_screen",
                    "locator_strategy": "vc_permission_allow_button",
                    "locator_kind": "button",
                    "require_lark_locator": True,
                    "preserve_foreground": True,
                },
            ),
        ]
    )
    steps.extend(
        [
            PlanStep(
                id="confirm_join_meeting",
                action="click",
                target_description="prejoin join meeting button",
                expected_state="The video meeting room is visible.",
                retry_limit=2,
                metadata={
                    "local_verifier": "vc_in_meeting",
                    "locator_strategy": "vc_join_confirm_button",
                    "locator_kind": "button",
                    "meeting_id": meeting_id,
                    "require_lark_locator": True,
                    "requires_vc_join_guard": True,
                    "dangerous_vc_join": True,
                    "preserve_foreground": True,
                    "wait_after_action_seconds": 8,
                },
            ),
        ]
    )
    steps.extend(_vc_join_device_steps(case))
    steps.extend(
        [
            PlanStep(
                id="verify_vc_joined",
                action="verify",
                target_description="video meeting room",
                expected_state="The video meeting is active and device controls are visible.",
                retry_limit=1,
                metadata={
                    "local_verifier": "vc_in_meeting",
                    "meeting_id": meeting_id,
                    "desired_camera_on": case.metadata.get("desired_camera_on"),
                    "desired_mic_on": case.metadata.get("desired_mic_on"),
                    "preserve_foreground": True,
                },
            ),
        ]
    )
    return TestPlan(
        goal=case.instruction,
        product="vc",
        steps=steps,
        success_criteria=[
            f"Meeting ID {meeting_id!r} is entered through the GUI.",
            "Meeting join is guarded by CUA_LARK_ALLOW_VC_JOIN=true.",
            "Requested camera/microphone states are handled after joining when provided.",
        ],
        assumptions=["The provided meeting ID is valid for the current test account."],
        raw_model_output={"provider": "product_template", "template": "vc_join_meeting_guarded"},
    )


def _vc_toggle_devices_guarded_plan(case: TestCase) -> TestPlan:
    steps = [
        _vc_focus_meeting_window_step(
            "focus_vc_meeting",
            "vc_in_meeting",
            "The Feishu meeting child window is foreground before device control.",
        ),
        PlanStep(
            id="verify_vc_in_meeting_before_toggle",
            action="verify",
            target_description="video meeting room",
            expected_state="The video meeting is active before toggling devices.",
            retry_limit=1,
            metadata={"local_verifier": "vc_in_meeting", "preserve_foreground": True},
        ),
    ]
    steps.extend(_vc_device_steps(case, require_device_guard=True))
    return TestPlan(
        goal=case.instruction,
        product="vc",
        steps=steps,
        success_criteria=[
            "The current video meeting is visually confirmed before touching devices.",
            "Camera/microphone toggles are guarded by CUA_LARK_ALLOW_VC_DEVICE_TOGGLE=true.",
        ],
        assumptions=["A video meeting is already active when running the standalone device-toggle case."],
        raw_model_output={"provider": "product_template", "template": "vc_toggle_devices_guarded"},
    )


def _vc_has_device_request(case: TestCase) -> bool:
    return case.metadata.get("desired_camera_on") is not None or case.metadata.get("desired_mic_on") is not None


def _vc_focus_meeting_window_step(step_id: str, verifier: str, expected_state: str) -> PlanStep:
    return PlanStep(
        id=step_id,
        action="focus_window",
        target_description="visible Feishu/Lark meeting child window",
        expected_state=expected_state,
        retry_limit=1,
        metadata={"local_verifier": verifier, "focus_vc_meeting": True},
    )


def _vc_open_steps() -> list[PlanStep]:
    return [
        PlanStep(
            id="focus_lark",
            action="focus_window",
            target_description="Feishu/Lark desktop window",
            expected_state="Feishu/Lark is foreground and ready for VC navigation.",
            retry_limit=1,
            metadata={"local_verifier": "lark_focused"},
        ),
        PlanStep(
            id="dismiss_overlays",
            action="conditional_hotkey",
            hotkeys=["esc"],
            expected_state="A stale overlay is dismissed only if present.",
            retry_limit=1,
            metadata={"local_verifier": "visible_screen", "locator_strategy": "docs_transient_overlay"},
        ),
        PlanStep(
            id="dismiss_vc_account_modal",
            action="conditional_hotkey",
            hotkeys=["esc"],
            expected_state="A Feishu account-switch modal is dismissed only if present.",
            retry_limit=1,
            metadata={
                "local_verifier": "visible_screen",
                "locator_strategy": "vc_account_switch_modal",
                "preserve_foreground": True,
            },
        ),
        PlanStep(
            id="open_vc",
            action="click",
            target_description="Feishu video meeting sidebar entry",
            expected_state="Video meeting product screen is visible.",
            retry_limit=2,
            metadata={"local_verifier": "vc_visible", "locator_strategy": "vc_sidebar_entry", "locator_kind": "button"},
        ),
        PlanStep(
            id="wait_vc_screen",
            action="wait",
            wait_seconds=0.2,
            expected_state="Video meeting screen settles after navigation.",
            retry_limit=1,
            metadata={"local_verifier": "visible_screen", "preserve_foreground": True},
        ),
    ]


def _vc_device_steps(case: TestCase, *, require_device_guard: bool = False) -> list[PlanStep]:
    steps: list[PlanStep] = []
    desired_camera = case.metadata.get("desired_camera_on")
    desired_mic = case.metadata.get("desired_mic_on")
    if desired_camera is not None:
        steps.append(
            PlanStep(
                id="set_vc_camera_state",
                action="conditional_click",
                target_description="video meeting camera control",
                expected_state=f"Camera is {'on' if desired_camera else 'off'}.",
                retry_limit=2,
                metadata={
                    "local_verifier": "vc_device_state",
                    "locator_strategy": "vc_camera_button",
                    "locator_kind": "button",
                    "desired_camera_on": bool(desired_camera),
                    "requires_vc_device_toggle_guard": True,
                    "dangerous_vc_device_toggle": require_device_guard,
                    "skip_if_vc_device_state_matches": True,
                    "preserve_foreground": True,
                    "wait_after_action_seconds": 1,
                },
            )
        )
    if desired_mic is not None:
        steps.append(
            PlanStep(
                id="set_vc_mic_state",
                action="conditional_click",
                target_description="video meeting microphone control",
                expected_state=f"Microphone is {'on' if desired_mic else 'muted'}.",
                retry_limit=2,
                metadata={
                    "local_verifier": "vc_device_state",
                    "locator_strategy": "vc_microphone_button",
                    "locator_kind": "button",
                    "desired_mic_on": bool(desired_mic),
                    "requires_vc_device_toggle_guard": True,
                    "dangerous_vc_device_toggle": require_device_guard,
                    "skip_if_vc_device_state_matches": True,
                    "preserve_foreground": True,
                    "wait_after_action_seconds": 1,
                },
            )
        )
    return steps


def _vc_join_device_steps(case: TestCase) -> list[PlanStep]:
    steps: list[PlanStep] = []
    desired_camera = case.metadata.get("desired_camera_on")
    desired_mic = case.metadata.get("desired_mic_on")
    if desired_camera is not None:
        steps.append(
            PlanStep(
                id="set_vc_camera_state",
                action="conditional_click",
                target_description="joined meeting camera control",
                expected_state=f"Camera is {'on' if desired_camera else 'off'}.",
                retry_limit=2,
                metadata={
                    "local_verifier": "vc_device_state",
                    "locator_strategy": "vc_join_camera_button",
                    "locator_kind": "button",
                    "desired_camera_on": bool(desired_camera),
                    "requires_vc_device_toggle_guard": True,
                    "dangerous_vc_device_toggle": False,
                    "skip_if_vc_device_state_matches": True,
                    "preserve_foreground": True,
                    "wait_after_action_seconds": 1,
                },
            )
        )
    if desired_mic is not None:
        steps.append(
            PlanStep(
                id="set_vc_mic_state",
                action="conditional_click",
                target_description="joined meeting microphone control",
                expected_state=f"Microphone is {'on' if desired_mic else 'muted'}.",
                retry_limit=2,
                metadata={
                    "local_verifier": "vc_device_state",
                    "locator_strategy": "vc_join_microphone_button",
                    "locator_kind": "button",
                    "desired_mic_on": bool(desired_mic),
                    "requires_vc_device_toggle_guard": True,
                    "dangerous_vc_device_toggle": False,
                    "skip_if_vc_device_state_matches": True,
                    "preserve_foreground": True,
                    "wait_after_action_seconds": 1,
                },
            )
        )
    return steps


def _vc_start_device_steps(case: TestCase) -> list[PlanStep]:
    steps: list[PlanStep] = []
    desired_camera = case.metadata.get("desired_camera_on")
    desired_mic = case.metadata.get("desired_mic_on")
    if desired_camera is not None:
        steps.append(
            PlanStep(
                id="set_vc_camera_state",
                action="conditional_click",
                target_description="started meeting camera control",
                expected_state=f"Camera is {'on' if desired_camera else 'off'}.",
                retry_limit=2,
                metadata={
                    "local_verifier": "vc_device_state",
                    "locator_strategy": "vc_start_camera_button",
                    "locator_kind": "button",
                    "desired_camera_on": bool(desired_camera),
                    "requires_vc_device_toggle_guard": True,
                    "dangerous_vc_device_toggle": False,
                    "skip_if_vc_device_state_matches": True,
                    "preserve_foreground": True,
                    "wait_after_action_seconds": 1,
                },
            )
        )
    if desired_mic is not None:
        steps.append(
            PlanStep(
                id="set_vc_mic_state",
                action="conditional_click",
                target_description="started meeting microphone control",
                expected_state=f"Microphone is {'on' if desired_mic else 'muted'}.",
                retry_limit=2,
                metadata={
                    "local_verifier": "vc_device_state",
                    "locator_strategy": "vc_start_microphone_button",
                    "locator_kind": "button",
                    "desired_mic_on": bool(desired_mic),
                    "requires_vc_device_toggle_guard": True,
                    "dangerous_vc_device_toggle": False,
                    "skip_if_vc_device_state_matches": True,
                    "preserve_foreground": True,
                    "wait_after_action_seconds": 1,
                },
            )
        )
    return steps


def _calendar_time_parts(raw_time: str) -> tuple[str, str, str]:
    now = datetime.now()
    if "后天" in raw_time or "後天" in raw_time:
        day_offset = 2
    elif "明天" in raw_time or "鏄庡ぉ" in raw_time:
        day_offset = 1
    else:
        day_offset = 0
    event_date = now + timedelta(days=day_offset)
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


def _calendar_scroll_amount_for_time(start_time: str) -> int:
    import re

    match = re.search(r"(\d{1,2}):(\d{2})", start_time or "")
    hour = int(match.group(1)) if match else 10
    if hour <= 7:
        return 0
    # Feishu's week/day timeline scrolls in small notches under pyautogui.
    # Use a deliberately larger bounded amount so post-save verification lands
    # near the target hour instead of staying in the early-morning viewport.
    return -max(24, min(120, max(hour - 1, 1) * 12))
