# Testing

## Overview

Fragrance Advisor includes a test suite covering the main application layers, from individual parsing functions to complete conversational scenarios.

The tests are implemented with **pytest**.

The current test suite covers:

- parsing and data-processing logic;
- API behavior;
- session persistence;
- end-to-end recommendation scenarios.

---

## Test Structure

```text
tests/
├── test_api.py
├── test_parsers.py
├── test_scenarios_e2e.py
└── test_session_store.py
```

---

## Unit Tests

### `test_parsers.py`

Tests individual parsing and data-processing functions.

These tests verify that product information is correctly interpreted and transformed into the expected structures.

They provide fast feedback for changes to the ingestion and parsing logic.

---

## Session Store Tests

### `test_session_store.py`

Tests the persistent session layer.

The test suite covers scenarios such as:

- creating and retrieving sessions;
- updating existing sessions;
- session isolation;
- clearing sessions;
- cleaning inactive sessions;
- handling invalid or corrupted session data;
- persistence across application lifecycle changes.

The goal is to ensure that conversational state can be reliably stored and restored.

---

## API Tests

### `test_api.py`

Tests the FastAPI layer and its interaction with the advisor.

The API tests cover request handling and the behavior of the exposed HTTP endpoints.

They help verify that frontend requests can be correctly processed by the backend.

---

## End-to-End Tests

### `test_scenarios_e2e.py`

The E2E suite verifies complete user interaction scenarios.

Examples include:

- searching by fragrance characteristics;
- guided recommendation flows;
- follow-up questions;
- requests for cheaper alternatives;
- product context;
- changing price constraints;
- handling requests with no suitable results;
- session persistence across restarts;
- HTTP-level interaction with FastAPI.

These tests validate the behavior of multiple application components working together.

---

## Running the Tests

Run the complete suite with:

```bash
pytest
```

For more detailed output:

```bash
pytest -v
```

To run a specific test file:

```bash
pytest tests/test_session_store.py
```

or:

```bash
pytest tests/test_api.py
```

---

## Test Configuration

The project uses:

```text
pytest.ini
```

for pytest configuration.

This keeps test discovery and execution settings separate from the application code.

---

## External Dependencies

Some integration and E2E scenarios can depend on external application components or services.

When tests require LLM access, the necessary environment variables must be configured before execution.

For example:

```env
GROQ_API_KEY=your_api_key_here
```

Secrets should never be stored directly in the test files or committed to Git.

---

## Testing Strategy

The test structure follows multiple levels of verification:

```text
        Unit Tests
            │
            ▼
    Component Behavior
            │
            ▼
      API / Integration
            │
            ▼
       E2E Scenarios
            │
            ▼
     Complete User Flow
```

This approach allows failures to be isolated at different levels.

A parsing failure, for example, can be identified independently from a failure in the complete conversational flow.

---

## Adding New Tests

New functionality should ideally be accompanied by tests at the appropriate level.

Examples:

| New functionality       | Suggested test     |
| ----------------------- | ------------------ |
| New parser              | Unit test          |
| New session behavior    | Session store test |
| New API parameter       | API test           |
| New conversational flow | E2E scenario       |
| New recommendation rule | Unit + E2E test    |

The objective is to keep the documented application behavior aligned with the behavior verified by the test suite.
