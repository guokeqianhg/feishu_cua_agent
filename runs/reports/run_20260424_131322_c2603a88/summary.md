# CUA-Lark Test Report

## Basic Info
- Run ID: c2603a88fc3946e5a0991fbdd83766d9
- Case ID: calendar_create_event_001
- Case Name: Create tomorrow afternoon meeting
- Product: calendar
- Instruction: 打开日历，创建一个明天下午2点的会议，邀请张三参加
- Status: pass
- Duration Seconds: 1.63
- Failure Category: none

## Metrics
- Total Steps: 5
- Passed Steps: 5
- Failed Steps: 0
- Retry Count: 0
- Replan Count: 0
- Success Rate: 100.00%
- Evidence Complete: True

## Step Details
| Step | Action | Target | Attempt | Status | Duration | Screenshot | Reason |
|---|---|---|---:|---|---:|---|---|
| open_calendar | click | Calendar entry in Lark sidebar | 1 | pass | 0.16 | runs\reports\run_20260424_131322_c2603a88\screenshots\001_open_calendar_after_a1.png | Mock verification passed for step open_calendar: Calendar page is open |
| create_event | click | create event button or target time slot | 1 | pass | 0.16 | runs\reports\run_20260424_131322_c2603a88\screenshots\002_create_event_after_a1.png | Mock verification passed for step create_event: event editor is open |
| type_event | type_text | event title or attendee field | 1 | pass | 0.15 | runs\reports\run_20260424_131322_c2603a88\screenshots\003_type_event_after_a1.png | Mock verification passed for step type_event: event details are filled |
| save_event | click | save or confirm event button | 1 | pass | 0.14 | runs\reports\run_20260424_131322_c2603a88\screenshots\004_save_event_after_a1.png | Mock verification passed for step save_event: event is saved |
| verify_event | verify | calendar event | 1 | pass | 0.14 | runs\reports\run_20260424_131322_c2603a88\screenshots\005_verify_event_after_a1.png | Mock verification passed for step verify_event: calendar event appears |

## Final Verification
Mock final verification passed. The full plan executed and produced step evidence.

## Failure Analysis
No failure.

## Summary
Run pass: 5/5 steps passed. Product=calendar. Evidence complete=True.
