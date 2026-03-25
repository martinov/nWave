---
name: nw-distill
description: "Creates E2E acceptance tests in Given-When-Then format from requirements and architecture. Use when preparing executable specifications before implementation."
user-invocable: true
argument-hint: '[story-id] - Optional: --test-framework=[cucumber|specflow|pytest-bdd] --integration=[real-services|mocks]'
---

# NW-DISTILL: Acceptance Test Creation and Business Validation

**Wave**: DISTILL (wave 5 of 6) | **Agent**: Quinn (nw-acceptance-designer)

## Overview

Create E2E acceptance tests from requirements|architecture|infrastructure design using Given-When-Then format. Produces executable specifications bridging business requirements and technical implementation. Infrastructure design from DEVOPS informs test environment setup.

## Interactive Decision Points

### Decision 1: Feature Scope
**Question**: What is the scope of this feature?
**Options**:
1. Core feature -- primary application functionality
2. Extension -- modular add-on or integration
3. Bug fix -- regression tests for a known defect

### Decision 2: Test Framework
**Question**: Which test framework to use?
**Options**:
1. pytest-bdd -- Python BDD framework
2. Cucumber -- Ruby/JS BDD framework
3. SpecFlow -- .NET BDD framework
4. Custom -- user provides details

### Decision 3: Integration Approach
**Question**: How should integration tests connect to services?
**Options**:
1. Real services -- test against actual running services
2. Test containers -- ephemeral containers for dependencies
3. Mocks for external only -- real internal, mocked external services

### Decision 4: Infrastructure Testing
**Question**: Should acceptance tests cover infrastructure concerns?
**Options**:
1. Yes -- include CI/CD validation, deployment smoke tests
2. No -- functional acceptance tests only

## Acceptance Criteria: Port-to-Port Principle

Every AC MUST name the driving port (entry point) through which the behavior is exercised. This enables port-to-port acceptance tests that make TBU (Tested But Unwired) defects structurally impossible.

Each AC includes:
1. **Observable outcome**: what the user/system sees
2. **Driving port**: the entry point that triggers the behavior (service, handler, endpoint, CLI command)

Without the driving port, a crafter can write correct code that is never wired into the system.

**Features**: "When user {action} via {driving_port}, {observable_outcome}"
**Bug fixes**: "When {trigger}, {modified_code_path} produces {correct_outcome} instead of {current_broken_behavior}"

## Prior Wave Consultation

Before beginning DISTILL work, read targeted prior wave artifacts:

1. **DISCOVER** (skip): DISCUSS already synthesized DISCOVER evidence into requirements and acceptance criteria.
2. **DISCUSS** (primary input): Read from `docs/feature/{feature-id}/discuss/`:
   - `acceptance-criteria.md` — primary input for test creation
   - `story-map.md` — drives walking skeleton priority and release slicing
   - `user-stories.md` — story-to-test traceability
   - `wave-decisions.md` — quick check for upstream changes
3. **DESIGN** (structural context): Read from `docs/feature/{feature-id}/design/`:
   - `architecture-design.md` — port boundaries define test scope
   - `component-boundaries.md` — determines which components tests exercise
   - `wave-decisions.md` — check for upstream changes from DISCUSS
4. **DEVOPS** (test environment): Read from `docs/feature/{feature-id}/devops/`:
   - `platform-architecture.md` — test environment setup
   - `ci-cd-pipeline.md` — test execution context
   - `wave-decisions.md` — check for infrastructure constraints affecting tests

DISTILL is the major synthesis point. Its job is to translate all prior wave knowledge into executable acceptance tests. The acceptance criteria from DISCUSS + architecture from DESIGN + infra from DEVOPS are sufficient. Raw DISCOVER artifacts are not needed — they were already synthesized into DISCUSS requirements.

**READING ENFORCEMENT**: You MUST read every file listed in Prior Wave Consultation above using the Read tool before proceeding. After reading, output a confirmation checklist (`✓ {file}` for each read, `⊘ {file} (not found)` for missing). Do NOT skip files that exist — skipping causes acceptance tests disconnected from requirements and architecture.

After reading, check whether any acceptance test assumptions contradict prior wave decisions. Use `wave-decisions.md` files to detect upstream changes. Example: DISCUSS acceptance criteria reference a "notification email" but DESIGN's wave-decisions.md notes email was removed in favor of in-app notifications — tests must reflect the DESIGN decision.

## Document Update (Back-Propagation)

When DISTILL work reveals gaps or contradictions in prior waves:
1. Document findings in `docs/feature/{feature-id}/distill/upstream-issues.md`
2. Reference the original prior-wave document and describe the gap
3. If acceptance criteria from DISCUSS are untestable as written, note the specific criteria and why
4. Resolve with user before writing tests against ambiguous or contradictory requirements

## Rigor Profile Integration

Before dispatching the acceptance designer, read rigor config from `.nwave/des-config.json` (key: `rigor`). If absent, use standard defaults.

- **`agent_model`**: Pass as `model` parameter to Task tool. If `"inherit"`, omit `model` (inherits from session).

## Wave-Decision Reconciliation (Pre-DISTILL Gate)

BEFORE writing any scenario, execute this reconciliation procedure:

1. Read ALL wave-decisions.md files from prior waves:
   - `docs/feature/{feature-id}/discuss/wave-decisions.md`
   - `docs/feature/{feature-id}/design/wave-decisions.md`
   - `docs/feature/{feature-id}/devops/wave-decisions.md`
2. For EACH decision in DISCUSS, check whether DESIGN or DEVOPS contradicts it:
   - DISCUSS says "email notifications" but DESIGN says "in-app only" = CONTRADICTION
   - DISCUSS says "REST API" but DESIGN says "gRPC" = CONTRADICTION
   - DISCUSS says "single-tenant" but DEVOPS says "multi-tenant" = CONTRADICTION
3. If ANY contradiction is found:
   a. List ALL contradictions with exact file paths and decision text
   b. BLOCK scenario writing until the user resolves each contradiction
   c. Return `{CLARIFICATION_NEEDED: true, questions: [{contradiction details}]}`
4. If zero contradictions: log "Reconciliation passed — 0 contradictions" and proceed.

Do NOT silently pick one side of a contradiction. Do NOT write scenarios against ambiguous specifications. The cost of blocking is minutes; the cost of implementing the wrong behavior is hours.

## Graceful Degradation for Missing Upstream Artifacts

When upstream wave artifacts are missing, apply these rules:

**DEVOPS missing** (no `docs/feature/{feature-id}/devops/` directory):
1. Log warning: "DEVOPS artifacts missing — using default environment matrix"
2. Use default environment matrix for all environment-dependent scenarios:
   - `clean` — fresh install, no prior state
   - `with-pre-commit` — pre-commit hooks installed and active
   - `with-stale-config` — outdated configuration from prior version
3. Proceed with scenario writing. Do NOT block.

**DISCUSS missing** (no `docs/feature/{feature-id}/discuss/` directory):
1. Log warning: "DISCUSS artifacts missing — using DESIGN only"
2. Derive acceptance criteria from DESIGN architecture documents
3. Skip Dim 8 Check A (story-to-scenario traceability) — no stories to trace
4. Proceed with scenario writing. Do NOT block.

**DESIGN missing** (no `docs/feature/{feature-id}/design/` directory):
1. Log warning: "DESIGN artifacts missing — driving ports unknown"
2. Ask user to identify driving ports before writing any scenario
3. BLOCK until driving ports are identified — without them, Mandate 1 (hexagonal boundary) is unverifiable

Missing artifacts trigger warnings, not failures — EXCEPT when the missing artifact makes a design mandate unverifiable (DESIGN for Mandate 1). In that case, BLOCK.

## Agent Invocation

@nw-acceptance-designer

Execute \*create-acceptance-tests for {feature-id}.

Context files: see above.

**Configuration:**
- model: rigor.agent_model (omit if "inherit")
- test_type: {Decision 1: core|extension|bugfix}
- test_framework: {Decision 2: specflow|cucumber|pytest-bdd}
- integration_approach: {Decision 3} | infrastructure_testing: {Decision 4}
- interactive: moderate | output_format: gherkin

## Fast-Path for Small Features

When the total scenario count is 3 or fewer:

1. Skip triple DISTILL review cycle. Run ONE acceptance-designer review pass only.
2. Run behavioral smoke test in the CURRENT environment (the one the developer is working in):
   ```bash
   pipenv run pytest tests/acceptance/{feature-id}/ -v --tb=short -x
   ```
   The first scenario MUST fail for a business logic reason (not import error, not missing fixture).
3. Skip the full fixture matrix. Full environment matrix testing applies only when scenario count exceeds 3.
4. All other gates remain in effect: mandate compliance (CM-A through CM-D), business language purity, hexagonal boundary enforcement.

This fast-path reduces DISTILL overhead for trivial features without sacrificing the core quality gates.

## Triple Review Gate (>3 scenarios)

When the feature has MORE than 3 scenarios, run THREE parallel reviews on the FROZEN acceptance test artifact.

All three reviewers use `rigor.reviewer_model` from `.nwave/des-config.json` (default: haiku). Pass as `model` parameter to each reviewer's Agent tool invocation. If `rigor.reviewer_model` is `"skip"`, skip the triple review entirely.

1. Dispatch ALL THREE reviewers in parallel (Agent tool, 3 concurrent calls):
   - `@nw-product-owner-reviewer`: "Verify story-to-scenario traceability. For EACH user story in DISCUSS, confirm at least one scenario covers it. Output: mapping table [story_id → scenario_name]. Flag unmapped stories as BLOCKER."
   - `@nw-solution-architect-reviewer`: "Verify hexagonal boundary compliance. For EACH scenario, confirm Then steps assert observable outcomes through driving ports — not internal state. Flag Dim 7 violations."
   - `@nw-platform-architect-reviewer`: "Verify environment coverage. For EACH target environment in DEVOPS inventory, confirm at least one walking skeleton includes that environment's preconditions. Flag uncovered environments as HIGH."

2. AND-gate: ANY rejection from ANY reviewer BLOCKS the DISTILL handoff.
   - Rejecting reviewer provides specific findings with file:line references
   - Non-rejecting reviewers do NOT re-run after revision
   - Only the rejecting reviewer re-reviews the revised artifact

3. On ALL APPROVE: proceed to Success Criteria and handoff to DELIVER.

4. On REJECTION: return acceptance test artifact to @nw-acceptance-designer with reviewer findings. Acceptance designer revises and re-submits to the rejecting reviewer(s) only.

## Success Criteria

- [ ] All user stories have corresponding acceptance tests
- [ ] Step methods call real production services (no mocks at acceptance level)
- [ ] One-at-a-time implementation strategy established (@skip/@pending tags)
- [ ] Tests exercise driving ports, not internal components (hexagonal boundary)
- [ ] Walking skeleton created first with user-centric scenarios (features only; optional for bugs)
- [ ] Infrastructure test scenarios included (if Decision 4 = Yes)
- [ ] Handoff package ready for nw-software-crafter (DELIVER wave)

## Examples

### Example 1: Core feature acceptance tests
```
/nw-distill payment-webhook --test-framework=pytest-bdd --integration=real-services
```
Quinn creates Given-When-Then acceptance tests from requirements and architecture, establishes walking skeleton first, then milestone features with @skip tags for one-at-a-time implementation.

## Next Wave

**Handoff To**: nw-software-crafter (DELIVER wave)
**Deliverables**: Feature files|step definitions|test-scenarios.md|walking-skeleton.md

## Wave Decisions Summary

Before completing DISTILL, produce `docs/feature/{feature-id}/distill/wave-decisions.md`:

```markdown
# DISTILL Decisions — {feature-id}

## Key Decisions
- [D1] {decision}: {rationale} (see: {source-file})

## Test Coverage Summary
- Total scenarios: {N}
- Walking skeleton scenarios: {N}
- Milestone features: {list}
- Test framework: {framework}
- Integration approach: {approach}

## Constraints Established
- {test boundary constraint}

## Upstream Issues
- {any gaps found in prior wave artifacts}
```

DISTILL is the major synthesis point. DELIVER reads DISTILL output as its authoritative specification — the acceptance tests encode all prior wave decisions into executable form.

## Expected Outputs

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

tests/unit/{component-or-module}/
  test_{module}_bug_{ticket-or-description}.py
```
