# CUA-Lark Test Report

## Basic Info
- Run ID: c1be564d54ab49a7bb166c1ad480c538
- Case ID: manual_2b2ac3b2
- Case Name: Manual natural-language run
- Product: im
- Instruction: ?IM????????????????Hello World?
- Status: pass
- Duration Seconds: 2.14
- Failure Category: none

## Metrics
- Total Steps: 7
- Passed Steps: 7
- Failed Steps: 0
- Retry Count: 0
- Replan Count: 0
- Success Rate: 100.00%
- Evidence Complete: True

## Step Details
| Step | Action | Target | Attempt | Status | Duration | Screenshot | Reason |
|---|---|---|---:|---|---:|---|---|
| open_im | click | left navigation message or IM entry | 1 | pass | 0.17 | runs\reports\run_20260424_131323_c1be564d\screenshots\001_open_im_after_a1.png | Mock verification passed for step open_im: IM page is open |
| focus_search | click | global or message search box | 1 | pass | 0.14 | runs\reports\run_20260424_131323_c1be564d\screenshots\002_focus_search_after_a1.png | Mock verification passed for step focus_search: search box is focused |
| type_query | type_text | search box | 1 | pass | 0.14 | runs\reports\run_20260424_131323_c1be564d\screenshots\003_type_query_after_a1.png | Mock verification passed for step type_query: search results are visible |
| open_chat | click | target chat in search results | 1 | pass | 0.13 | runs\reports\run_20260424_131323_c1be564d\screenshots\004_open_chat_after_a1.png | Mock verification passed for step open_chat: chat window is open |
| type_message | type_text | chat message input box | 1 | pass | 0.13 | runs\reports\run_20260424_131323_c1be564d\screenshots\005_type_message_after_a1.png | Mock verification passed for step type_message: message text is in input box |
| send_message | hotkey |  | 1 | pass | 0.13 | runs\reports\run_20260424_131323_c1be564d\screenshots\006_send_message_after_a1.png | Mock verification passed for step send_message: message is sent |
| verify_message | verify | latest chat message | 1 | pass | 0.14 | runs\reports\run_20260424_131323_c1be564d\screenshots\007_verify_message_after_a1.png | Mock verification passed for step verify_message: target message appears in chat history |

## Final Verification
Mock final verification passed. The full plan executed and produced step evidence.

## Failure Analysis
No failure.

## Summary
Run pass: 7/7 steps passed. Product=im. Evidence complete=True.
