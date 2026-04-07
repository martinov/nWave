---
description: "Creates E2E acceptance tests in Given-When-Then format from requirements and architecture. Use when preparing executable specifications before implementation."
argument-hint: "[story-id] - Optional: --test-framework=[cucumber|specflow|pytest-bdd] --integration=[real-services|mocks]"
---

# NW-DISTILL: Acceptance Test Creation and Business Validation

**Wave**: DISTILL (wave 5 of 6) | **Agent**: Quinn (nw-acceptance-designer)

## Overview

Orchestrate acceptance test creation from prior wave artifacts, then gate the result through parallel reviews before handoff to DELIVER. You (main Claude instance) are the orchestrator. You dispatch agents and enforce gates.

## REVIEW GATE SUMMARY (read this first)

After the acceptance designer produces scenarios, you MUST dispatch 3 parallel reviewers if scenario count exceeds 3. This is the single most important orchestration step in DISTILL. The procedure is: dispatch designer -> count scenarios -> dispatch 3 reviewers in parallel -> AND-gate results -> handoff. Details in Phase 3 below.

## Phase 1: Decisions and Context

### Interactive Decision Points

#### Decision 1: Feature Scope
**Question**: What is the scope of this feature?
**Options**:
1. Core feature -- primary application functionality
2. Extension -- modular add-on or integration
3. Bug fix -- regression tests for a known defect

#### Decision 2: Test Framework
**Question**: Which test framework to use?
**Options**:
1. pytest-bdd -- Python BDD framework
2. Cucumber -- Ruby/JS BDD framework
3. SpecFlow -- .NET BDD framework
4. Custom -- user provides details

#### Decision 3: Integration Approach
**Question**: How should integration tests connect to services?
**Options**:
1. Real services -- test against actual running services
2. Test containers -- ephemeral containers for dependencies
3. Mocks for external only -- real internal, mocked external services

#### Decision 4: Infrastructure Testing
**Question**: Should acceptance tests cover infrastructure concerns?
**Options**:
1. Yes -- include CI/CD validation, deployment smoke tests
2. No -- functional acceptance tests only

### Prior Wave Consultation

DISTILL is the conjunction point — it reads all three SSOT dimensions plus the feature delta.

**SSOT (all three dimensions):**
1. **Journeys** (behavior): Read `docs/product/journeys/{name}.yaml` — extract embedded Gherkin as starting scenarios, identify integration checkpoints and failure_modes
2. **Architecture** (structure): Read `docs/product/architecture/brief.md` — identify driving ports (from `## For Acceptance Designer` section) for port-entry test scenarios
3. **KPI contracts** (observability): Read `docs/product/kpi-contracts.yaml` — identify which behaviors need `@kpi` tagged scenarios (soft gate — warn if missing, proceed)

**Feature delta:**
4. **DISCUSS**: Read from `docs/feature/{feature-id}/discuss/`:
   - `user-stories.md` (scope boundary — generate tests for THIS feature's stories only) | `story-map.md` | `wave-decisions.md`
5. **DEVOPS** (test environment): Read from `docs/feature/{feature-id}/devops/`:
   - `platform-architecture.md` | `ci-cd-pipeline.md` | `wave-decisions.md`

**Scope rule**: DISTILL generates tests for the behaviors described in `user-stories.md`, not for the entire SSOT. The SSOT provides context (which port to enter through, which KPI to verify) but the scope is bounded by the feature delta.

**READING ENFORCEMENT**: Read every file above using the Read tool. Output confirmation checklist (`+ {file}` for each read, `- {file} (not found)` for missing). Do NOT skip files that exist.

**Fallback**: If `docs/product/` does not exist, fall back to `docs/feature/{feature-id}/` for all inputs (old model).

### Graceful Degradation

- **KPI contracts missing**: Log warning: "KPI contracts missing — acceptance tests cover behavior only, not observability." Proceed without `@kpi` scenarios.
- **DEVOPS missing**: Log warning, use default environment matrix (clean, with-pre-commit, with-stale-config). Proceed.
- **DISCUSS missing**: Log warning, derive AC from architecture. Skip story-to-scenario traceability. Proceed.
- **Architecture SSOT missing**: BLOCK. Ask user to identify driving ports. Without them, hexagonal boundary is unverifiable.

### Rigor Profile

Read rigor config from `.nwave/des-config.json` (key: `rigor`). If absent, use standard defaults.
- `agent_model`: Pass as `model` to acceptance designer. If `"inherit"`, omit.
- `reviewer_model`: Pass as `model` to all 3 reviewers. If `"skip"`, skip Triple Review Gate entirely.

### Wave-Decision Reconciliation

BEFORE dispatching the acceptance designer:
1. Read ALL `wave-decisions.md` files from prior waves
2. Check for contradictions between DISCUSS, DESIGN, and DEVOPS decisions
3. If ANY contradiction: list them all, BLOCK until user resolves each one
4. If zero contradictions: log "Reconciliation passed" and proceed

## Phase 2: Dispatch Acceptance Designer

@nw-acceptance-designer

Execute \*create-acceptance-tests for {feature-id}.

**Prompt must include:**
- All prior wave context read in Phase 1
- Decisions 1-4 configuration
- Instruction to load skills at `~/.claude/skills/nw-{skill-name}/SKILL.md`

**Configuration:**
- model: rigor.agent_model (omit if "inherit")
- test_type: {Decision 1} | test_framework: {Decision 2}
- integration_approach: {Decision 3} | infrastructure_testing: {Decision 4}
- interactive: moderate | output_format: gherkin

**After the agent returns**: Count the total scenarios produced. Store this number. You need it for Phase 3.

## Phase 3: TRIPLE REVIEW GATE (mandatory orchestrator action)

This phase determines whether the acceptance tests are ready for DELIVER handoff. You MUST execute this phase. There is no path to Phase 5 (Handoff) that bypasses this gate.

### Step 3.1: Count scenarios

Count total scenarios across all `.feature` files produced by the acceptance designer. Store the count.

### Step 3.2: Fast-path (3 or fewer scenarios)

If total scenarios <= 3:
1. Skip the triple review. Run ONE acceptance-designer review pass only:
   - Dispatch `@nw-acceptance-designer-reviewer` with the feature files
2. Run behavioral smoke test:
   ```bash
   pipenv run pytest tests/acceptance/{feature-id}/ -v --tb=short -x
   ```
   First scenario MUST fail for a business logic reason (not import error, not missing fixture).
3. Proceed to Phase 4.

### Step 3.3: Triple review (more than 3 scenarios)

If total scenarios > 3, DISPATCH ALL THREE REVIEWERS IN PARALLEL. Use the Agent tool three times in a single response — do not wait for one to finish before dispatching the next.

**Reviewer 1 — Product Owner (@nw-product-owner-reviewer)**:
```
Agent(
    subagent_type="nw-product-owner-reviewer",
    model=rigor.reviewer_model,  # omit if "inherit"
    prompt="""
    Review the acceptance tests for feature {feature-id}.

    TASK: Verify story-to-scenario traceability.
    For EACH user story in docs/feature/{feature-id}/discuss/user-stories.md,
    confirm at least one scenario in tests/acceptance/{feature-id}/ covers it.

    OUTPUT: mapping table [story_id -> scenario_name].
    Flag unmapped stories as BLOCKER.

    Acceptance test files: tests/{test-type-path}/{feature-id}/acceptance/
    Story files: docs/feature/{feature-id}/discuss/user-stories.md

    Load your skills from ~/.claude/skills/nw-{skill-name}/SKILL.md before starting.

    Return structured YAML with approval_status: approved | rejected_pending_revisions
    """,
    description="PO review: story-to-scenario traceability for {feature-id}"
)
```

**Reviewer 2 — Solution Architect (@nw-solution-architect-reviewer)**:
```
Agent(
    subagent_type="nw-solution-architect-reviewer",
    model=rigor.reviewer_model,  # omit if "inherit"
    prompt="""
    Review the acceptance tests for feature {feature-id}.

    TASK: Verify hexagonal boundary compliance.
    For EACH scenario in tests/{test-type-path}/{feature-id}/acceptance/,
    confirm Then steps assert observable outcomes through driving ports -- not internal state.
    Cross-reference with docs/feature/{feature-id}/design/architecture-design.md for port definitions.

    Flag scenarios that assert internal state, mock calls, or private fields as BLOCKER.

    Acceptance test files: tests/{test-type-path}/{feature-id}/acceptance/
    Architecture: docs/feature/{feature-id}/design/architecture-design.md

    Load your skills from ~/.claude/skills/nw-{skill-name}/SKILL.md before starting.

    Return structured YAML with approval_status: approved | rejected_pending_revisions
    """,
    description="SA review: hexagonal boundary compliance for {feature-id}"
)
```

**Reviewer 3 — Platform Architect (@nw-platform-architect-reviewer)**:
```
Agent(
    subagent_type="nw-platform-architect-reviewer",
    model=rigor.reviewer_model,  # omit if "inherit"
    prompt="""
    Review the acceptance tests for feature {feature-id}.

    TASK: Verify environment coverage.
    For EACH target environment in docs/feature/{feature-id}/devops/ inventory,
    confirm at least one walking skeleton scenario includes that environment's preconditions.
    If DEVOPS artifacts are missing, check against defaults: clean, with-pre-commit, with-stale-config.

    Flag uncovered environments as HIGH.

    Acceptance test files: tests/{test-type-path}/{feature-id}/acceptance/
    DEVOPS artifacts: docs/feature/{feature-id}/devops/

    Load your skills from ~/.claude/skills/nw-{skill-name}/SKILL.md before starting.

    Return structured YAML with approval_status: approved | rejected_pending_revisions
    """,
    description="PA review: environment coverage for {feature-id}"
)
```

### Step 3.4: AND-Gate (all three must approve)

After all three reviewers return:
1. Check each reviewer's `approval_status`
2. ANY `rejected_pending_revisions` BLOCKS the DISTILL handoff
3. On rejection:
   - Collect specific findings from rejecting reviewer(s)
   - Re-dispatch `@nw-acceptance-designer` with reviewer findings attached
   - After revision, re-submit ONLY to the rejecting reviewer(s) — do not re-run approving reviewers
4. On ALL APPROVE: proceed to Phase 4

Max 2 revision cycles. If still rejected after 2 cycles, STOP and escalate to user.

## Phase 4: Produce Wave Decisions

Before completing DISTILL, produce `docs/feature/{feature-id}/distill/wave-decisions.md`:

```markdown
# DISTILL Decisions -- {feature-id}

## Key Decisions
- [D1] {decision}: {rationale} (see: {source-file})

## Test Coverage Summary
- Total scenarios: {N}
- Walking skeleton scenarios: {N}
- Milestone features: {list}
- Test framework: {framework}
- Integration approach: {approach}

## Review Gate Result
- Review type: {triple-review | fast-path | skipped (reviewer_model=skip)}
- PO reviewer: {approved | rejected -> revised -> approved}
- SA reviewer: {approved | rejected -> revised -> approved}
- PA reviewer: {approved | rejected -> revised -> approved}

## Upstream Issues
- {any gaps found in prior wave artifacts}
```

## Phase 5: Handoff to DELIVER

Deliver these artifacts to the next wave:

```
tests/{test-type-path}/{feature-id}/acceptance/
  walking-skeleton.feature
  milestone-{N}-{description}.feature
  integration-checkpoints.feature
  steps/
    conftest.py
    {domain}_steps.py

docs/feature/{feature-id}/distill/
  test-scenarios.md
  walking-skeleton.md
  acceptance-review.md
  wave-decisions.md
```

Bug fix regression tests:
```
tests/regression/{component-or-module}/
  bug-{ticket-or-description}.feature
  steps/
    conftest.py
    {domain}_steps.py
```

**Handoff To**: nw-software-crafter (DELIVER wave)
**Deliverables**: Feature files | step definitions | test-scenarios.md | walking-skeleton.md

## Progress Tracking

The invoked agent MUST create a task list from its workflow phases at the start of execution using TaskCreate. Each phase becomes a task with the gate condition as completion criterion. Mark tasks in_progress when starting each phase and completed when the gate passes. This gives the user real-time visibility into progress.

## Success Criteria

- [ ] All user stories have corresponding acceptance tests
- [ ] Step methods call real production services (no mocks at acceptance level)
- [ ] One-at-a-time implementation strategy established (@skip/@pending tags)
- [ ] Tests exercise driving ports, not internal components (hexagonal boundary)
- [ ] Walking skeleton created first with user-centric scenarios (features only; optional for bugs)
- [ ] Infrastructure test scenarios included (if Decision 4 = Yes)
- [ ] Triple Review Gate passed (or fast-path for <=3 scenarios)
- [ ] Handoff package ready for nw-software-crafter (DELIVER wave)

## Examples

### Example 1: Core feature with triple review
```
/nw-distill payment-webhook --test-framework=pytest-bdd --integration=real-services
```
Orchestrator reads prior waves -> dispatches Quinn -> Quinn produces 12 scenarios -> orchestrator dispatches PO + SA + PA reviewers in parallel -> SA rejects (internal state assertion in scenario 7) -> Quinn revises -> SA re-reviews -> approved -> handoff to DELIVER.

### Example 2: Small bug fix with fast-path
```
/nw-distill fix-timeout-bug --test-framework=pytest-bdd
```
Orchestrator reads prior waves -> dispatches Quinn -> Quinn produces 2 regression scenarios -> fast-path (<=3) -> single AD reviewer pass -> smoke test fails for business reason -> handoff to DELIVER.

### Example 3: Reviewer model skip
`.nwave/des-config.json` has `rigor.reviewer_model: "skip"`. Orchestrator dispatches Quinn -> scenarios produced -> Triple Review Gate skipped entirely -> handoff to DELIVER.

DISTILL is the major synthesis point. DELIVER reads DISTILL output as its authoritative specification.
