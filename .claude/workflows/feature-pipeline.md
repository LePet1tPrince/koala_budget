# Feature Pipeline — Orchestration Workflow

## Trigger

Start this pipeline with:

```
Run the feature pipeline for: [plain English description of the feature]
```

Claude Code reads this file, runs the agents in sequence, manages handoffs, and stops only on a No-Go or Blocked verdict.

---

## Pipeline Sequence

```
Feature Request (plain English)
    ↓
01-designer        → Requirements Document
    ↓
02-feature-engineer → Code changes + Files changed + New patterns
    ↓
03-qa-tester       → Test Report + Go / No-Go verdict
    ↓ (Go only — No-Go stops here, see Stop Conditions)
04-doc-updater     → Updated CLAUDE.md + design-document.md + testing-guide.md + changelog
    ↓
05-security-reviewer → Security Report + Approved / Blocked verdict
    ↓ (Approved only — Blocked stops here, see Stop Conditions)
06-pr-creator      → PR title + PR description + Merge checklist
```

---

## Agent Details

### Step 1 — Designer (`01-designer.md`)

**Receives:** Feature request (plain English)

**Reads:** `docs/design-document.md`

**Must output before Step 2 starts:**
- Requirements Document with all 7 sections complete:
  1. Overview
  2. User Stories
  3. Acceptance Criteria (numbered, testable)
  4. UI/UX Specs
  5. Edge Cases
  6. Out of Scope
  7. Design Decisions

**Do not proceed to Step 2 until:** Requirements Document is complete with no empty sections.

---

### Step 2 — Feature Engineer (`02-feature-engineer.md`)

**Receives:** Requirements Document from Step 1

**Reads:** `CLAUDE.md`

**Must output before Step 3 starts:**
- Working code changes committed to the feature branch
- Handoff summary with:
  - Files Changed (with descriptions)
  - New Dependencies
  - New Patterns Introduced
  - Implementation Notes

**Do not proceed to Step 3 until:** Code is committed and handoff summary is complete.

---

### Step 3 — QA/Tester (`03-qa-tester.md`)

**Receives:** Requirements Document (Step 1) + code changes and handoff summary (Step 2)

**Must output before Step 4 starts:**
- Test Report with:
  - Acceptance Criteria Results (Pass/Fail for each)
  - Edge Case Results
  - Regression Check
  - Bug List (if any)
  - Verdict: **Go** or **No-Go**

**Handoff condition:** Pipeline continues to Step 4 **only on a Go verdict.**

**Stop condition — QA No-Go:** See "Stop Conditions" below.

---

### Step 4 — Documentation Updater (`04-doc-updater.md`)

**Receives:** Requirements Document (Step 1) + handoff summary (Step 2) + Test Report with Go verdict (Step 3)

**Reads:** `CLAUDE.md`, `docs/design-document.md`, `docs/testing-guide.md`

**Must output before Step 5 starts:**
- Updated `CLAUDE.md`
- Updated `docs/design-document.md`
- Updated `docs/testing-guide.md`
- Updated README or user docs (if user-facing behavior changed)
- Changelog entry

**Do not proceed to Step 5 until:** All changed documents are committed.

---

### Step 5 — Security Reviewer (`05-security-reviewer.md`)

**Receives:** Requirements Document (Step 1) + handoff summary (Step 2) + Test Report (Step 3)

**Reads:** `docs/security-log.md`

**Must output before Step 6 starts:**
- Security Report with:
  - Findings list (or explicit "No issues found")
  - Severity ratings
  - Security Log update (to be written to `docs/security-log.md`)
  - Verdict: **Approved** or **Blocked**

**Handoff condition:** Pipeline continues to Step 6 **only on an Approved verdict.**

**Stop condition — Security Blocked:** See "Stop Conditions" below.

---

### Step 6 — PR Creator (`06-pr-creator.md`)

**Receives:** Requirements Document (Step 1) + files changed (Step 2) + Test Report (Step 3) + Security Report (Step 5) + branch name

**Must output:**
- PR title (format: `[Type] Brief description`)
- PR description (using the standard template)
- Merge checklist with confirmed/cannot-confirm status for each item

**Pipeline complete** when PR is created (or PR output is ready for human to submit).

---

## Stop Conditions

### QA No-Go (after Step 3)

When the QA/Tester returns a **No-Go** verdict:

1. **Stop the pipeline.** Do not proceed to Step 4.
2. **Route back to Feature Engineer** with:
   - The original Requirements Document
   - The full bug list from the Test Report, sorted by severity
   - Instruction to fix all Critical and High bugs before resubmitting
3. **Re-run from Step 2** (Feature Engineer) with the bug list as additional input.
4. Do not re-run the Designer (Step 1) unless the bug list reveals a fundamental spec problem.

### Security Blocked (after Step 5)

When the Security Reviewer returns a **Blocked** verdict:

1. **Stop the pipeline.** Do not proceed to Step 6.
2. **Route back to Feature Engineer** with:
   - The original Requirements Document
   - The list of Critical findings from the Security Report with recommendations
   - Instruction to fix all Critical findings before resubmitting
3. **Re-run from Step 2** (Feature Engineer) with the Critical findings as additional input.
4. After fix: re-run Step 3 (QA) and Step 5 (Security) but skip Steps 1 and 4 (already done).

---

## Retry Limits

- Maximum 3 No-Go/Blocked cycles before escalating to human review.
- If the pipeline has cycled 3 times without reaching Step 6, stop and report:
  - What is failing
  - What has been attempted
  - Recommended human action

---

## Notes

- All agent system prompts are in `.claude/agents/`
- Living documents updated by this pipeline: `CLAUDE.md`, `docs/design-document.md`, `docs/testing-guide.md`, `docs/security-log.md`
- Every completed feature improves these documents, which improves the quality of every subsequent feature
