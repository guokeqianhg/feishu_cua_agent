# CUA-Lark Test Report

## Basic Info
- Run ID: 5d1a32096b7446c5a618df3b1b6c1692
- Case ID: docs_create_doc_001
- Case Name: Create project weekly report document
- Product: docs
- Instruction: 在飞书中创建一个名为「项目周报」的新文档，并输入标题「2026年Q2项目进展」
- Status: pass
- Duration Seconds: 1.30
- Failure Category: none

## Metrics
- Total Steps: 4
- Passed Steps: 4
- Failed Steps: 0
- Retry Count: 0
- Replan Count: 0
- Success Rate: 100.00%
- Evidence Complete: True

## Step Details
| Step | Action | Target | Attempt | Status | Duration | Screenshot | Reason |
|---|---|---|---:|---|---:|---|---|
| open_docs | click | Docs entry in Lark sidebar or workplace | 1 | pass | 0.14 | runs\reports\run_20260424_131636_5d1a3209\screenshots\001_open_docs_after_a1.png | Mock verification passed for step open_docs: Docs page is open |
| create_doc | click | new document button | 1 | pass | 0.15 | runs\reports\run_20260424_131636_5d1a3209\screenshots\002_create_doc_after_a1.png | Mock verification passed for step create_doc: new document editor is open |
| type_title | type_text | document title field | 1 | pass | 0.15 | runs\reports\run_20260424_131636_5d1a3209\screenshots\003_type_title_after_a1.png | Mock verification passed for step type_title: document title appears |
| verify_doc | verify | document title | 1 | pass | 0.14 | runs\reports\run_20260424_131636_5d1a3209\screenshots\004_verify_doc_after_a1.png | Mock verification passed for step verify_doc: new document title is visible |

## Final Verification
Mock final verification passed. The full plan executed and produced step evidence.

## Failure Analysis
No failure.

## Summary
Run pass: 4/4 steps passed. Product=docs. Evidence complete=True.
