# Agent Studio Proposals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace hard-coded tiny gameplay objectives with a proposal-driven studio loop where specialist agents pitch, critique, and hand off meaningful feature concepts.

**Architecture:** Add structured proposal artifacts before Director selection. Specialist roles generate proposals from their own agenda, QA critiques the shortlist, and Director/Designer/Builder receive the accepted collaboration context. Keep patch validation strict, but remove HP-style fallback objectives and churn seeds.

**Tech Stack:** Python studio orchestrator, markdown role prompts, JSON artifacts under `studio/state`, existing pytest suite.

---

### Task 1: Proposal Model And Board

**Files:**
- Create: `studio/proposals.py`
- Test: `studio/tests/test_proposals.py`

- [ ] Add `AgentProposal`, `ProposalCritique`, and `ProposalBoard` dataclasses.
- [ ] Parse role markdown into resilient proposal records using `Title:`, `Goal:`, and `Implementation hint:` fields.
- [ ] Serialize board artifacts to JSON and render a markdown context block for Director/Designer/Builder.
- [ ] Verify board round-trips with pytest.

### Task 2: Specialist Role Prompts

**Files:**
- Create: `studio/roles/enemy_designer.md`
- Create: `studio/roles/systems_designer.md`
- Create: `studio/roles/art_director_concept.md`
- Create: `studio/roles/qa_critic.md`

- [ ] Give each specialist a standing goal and a structured output contract.
- [ ] Ensure prompts reject trivial numeric tweaks and prefer memorable, testable concepts.
- [ ] Make QA critique proposals before implementation, not code after implementation.

### Task 3: Orchestrator Proposal Intake

**Files:**
- Modify: `studio/orchestrator.py`
- Test: `studio/tests/test_orchestrator.py`

- [ ] Run available specialist roles before Director in write mode.
- [ ] Write `cycle-NNNN-proposals.json` and `cycle-NNNN-proposals.md`.
- [ ] Feed proposal board context to Director, Designer, Builder, and Reviewer.
- [ ] Keep tests compatible by skipping proposal roles when prompt files are absent.

### Task 4: Remove Bad Steering

**Files:**
- Modify: `studio/churn_guards.py`
- Modify: `studio/cycle_critic.py`
- Modify: `studio/orchestrator.py`

- [ ] Remove hard-coded HP / tiny constant objective seeds.
- [ ] Replace mandatory churn notes with proposal-board guidance.
- [ ] Make patch-failure fallback ask for a simpler proposal, not a numeric stat tweak.

### Task 5: Verify

**Files:**
- Test: `studio/tests/`

- [ ] Run `python -m pytest studio/tests/ -q`.
- [ ] Check lints for changed Python files.
- [ ] Do not launch long sparky cycles until tests pass locally.
