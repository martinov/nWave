---
name: nw-test-design-mandates
description: Four design mandates for acceptance tests - hexagonal boundary enforcement, business language abstraction, user journey completeness, walking skeleton strategy, and pure function extraction
user-invocable: false
disable-model-invocation: true
---

# Acceptance Test Design Mandates

Four mandates enforced during peer review. All must pass before handoff to software-crafter.

## Mandate 1: Hexagonal Boundary Enforcement

Tests invoke through driving ports (entry points), never internal components.

### Driving Ports (Test Through These)
Application services/orchestrators | API controllers/CLI handlers | Message consumers/event handlers | Public API facade classes

### Not Entry Points (Never Test Directly)
Internal validators, parsers, formatters | Domain entities/value objects | Repository implementations | Internal service components

### Correct Pattern

```python
# Invoke through system entry point (driving port)
from myapp.orchestrator import AppOrchestrator

def when_user_performs_action(self):
    orchestrator = AppOrchestrator()
    self.result = orchestrator.perform_action(
        context=self.context
    )
```

### Violation Pattern

```python
# Invoking internal component directly
from myapp.validator import InputValidator  # INTERNAL

def when_user_validates_input(self):
    validator = InputValidator()  # WRONG BOUNDARY
    self.result = validator.validate(self.input)
```

Testing internal components creates Testing Theater: tests pass but users cannot access feature through actual entry point. Integration wiring bugs remain hidden.

## Mandate 2: Business Language Abstraction

Step methods speak business language, abstract all technical details.

### Three Abstraction Layers

**Layer 1 - Gherkin**: Pure business language, all stakeholders. Domain terms from ubiquitous language | Zero technical jargon | Describe WHAT user does, not HOW system does it

```gherkin
Scenario: Customer places order for available product
  Given customer has items in shopping cart
  When customer submits order
  Then order is confirmed
  And customer receives confirmation email
```

**Layer 2 - Step Methods**: Business service delegation. Method names use domain terms | Delegate to business service layer (OrderService, not HTTP client) | Assert business outcomes (order.is_confirmed()), not technical state (status_code == 201)

```python
def when_customer_submits_order(self):
    self.result = self.order_service.place_order(
        customer=self.customer, items=self.cart_items
    )

def then_order_is_confirmed(self):
    assert self.result.is_confirmed()
    assert self.result.has_order_number()
```

**Layer 3 - Business Services**: Production services handle technical implementation. HTTP calls, DB transactions, SMTP hidden inside service layer.

### Test Smell Indicators
`requests.post()` in step method | `db.execute()` in step method | `assert response.status_code` | Technical terms in Gherkin

## Mandate 3: User Journey Completeness

Tests validate complete user journeys with business value, not isolated technical operations.

### Complete Journey Structure
Every scenario includes: **User trigger** (Given/When) | **Business logic** (When - system processes rules) | **Observable outcome** (Then - user sees result) | **Business value** (Then - value delivered)

### Correct Example

```gherkin
Scenario: Customer successfully completes purchase
  Given customer has selected products worth $150
  And customer has valid payment method
  When customer submits order
  Then order is confirmed with order number
  And customer receives email confirmation
  And order appears in customer's order history
```

### Violation Example

```gherkin
Scenario: Order validator accepts valid order data
  Given valid order JSON exists
  When validator.validate() is called
  Then validation passes
# Tests isolated validation, not user journey
```

### Scenario Name Test
Does name express user value or technical operation? "Customer completes purchase" = correct. "Validator accepts JSON" = violation.

## Walking Skeleton Strategy

Balance user-centric E2E integration tests with focused boundary tests.

### Walking Skeletons (2-5 per feature)
Trace thin vertical slice delivering observable user value E2E | Each answers: "Can a user accomplish this goal and see the result?" | Express simplest complete user journey | Validate system delivers demo-able stakeholder value | Touch all layers as consequence of journey, not as design goal

### Walking Skeleton Litmus Test
1. Title describes user goal ("Customer purchases a product") not technical flow ("Order passes through all layers")
2. Given/When describe user actions/context, not system state setup
3. Then describe user observations (confirmation, email, receipt), not internal side effects (DB row, message queued)
4. Non-technical stakeholder can confirm "yes, that is what users need"

### Focused Scenarios (15-20 per feature, majority)
Test specific business rules at driving port boundary | Test doubles for external dependencies (faster, isolated) | Cover business rule variations and edge cases | Invoke through entry point (OrderService, Orchestrator)

### Recommended Ratio
For typical feature with 20 scenarios: 2-3 walking skeletons (user value E2E) | 17-18 focused scenarios (boundary tests with test doubles). Walking skeletons prove users achieve goals. Focused scenarios run fast, cover breadth. Both use business language and invoke through entry points.

## Mandate 4: Pure Function Extraction Before Fixtures

BEFORE parametrizing any test fixture with environment variants:

1. Identify ALL business logic in the code under test
2. Extract every piece of business logic into a pure function:
   - Pure function: takes inputs, returns outputs, no side effects
   - Impure code: subprocess calls, file I/O, network, environment variables
3. Test pure functions directly — no fixtures, no mocks, no environment setup needed
4. Test impure code (subprocess, file I/O) through adapter interfaces:
   - Define a port (interface) for each impure operation
   - Create a test adapter (in-memory, fake) for each port
   - Acceptance tests use real adapters; unit tests use fakes
5. Parametrize fixtures ONLY for the thin adapter layer that connects to real environments

**Rationale**: Parametrizing fixtures across environments is expensive. Pure functions need zero environment setup. Extract first, parametrize the minimum.

### Violation Pattern

```python
# WRONG: parametrizing entire test across environments
@pytest.fixture(params=["clean", "with-pre-commit", "with-stale-config"])
def environment(request):
    return setup_environment(request.param)

def test_install_detects_conflicts(environment):
    result = full_install_pipeline(environment)  # Impure: touches filesystem
    assert result.conflicts == []
```

### Correct Pattern

```python
# Step 1: Extract pure logic
def detect_conflicts(config: Config, existing: list[str]) -> list[Conflict]:
    """Pure function — no I/O, no environment dependency."""
    return [Conflict(k) for k in existing if k in config.keys]

# Step 2: Test pure function directly (no fixture needed)
def test_detect_conflicts_with_overlapping_keys():
    conflicts = detect_conflicts(Config(keys=["a", "b"]), existing=["b", "c"])
    assert conflicts == [Conflict("b")]

# Step 3: Parametrize ONLY the adapter layer
@pytest.fixture(params=["clean", "with-pre-commit"])
def fs_adapter(request):
    return create_real_fs_adapter(request.param)

def test_adapter_reads_config_from_environment(fs_adapter):
    config = fs_adapter.read_config()  # Only I/O is parametrized
    assert config is not None
```

### Mandate Compliance (CM-D)

- **CM-D**: Business logic extracted to pure functions. Impure code isolated behind adapters. Fixture parametrization applies only to adapter layer.

## Mandate Compliance Verification

Handoff to software-crafter includes proof all four mandates pass:
- **CM-A**: All test files import entry points (driving ports), zero internal component imports
- **CM-B**: Gherkin uses business terms only, step methods delegate to services
- **CM-C**: Scenarios validate complete user journeys with business value
- **CM-D**: Business logic extracted to pure functions. Impure code isolated behind adapters. Fixture parametrization applies only to adapter layer.

Evidence: import listings, grep for technical terms, walking skeleton identification, focused scenario count, pure function extraction inventory (list of extracted functions + their adapter boundaries).
