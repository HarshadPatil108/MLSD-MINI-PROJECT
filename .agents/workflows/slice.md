# Workflow: Vertical Slice Execution Protocol

To maintain modularity, test-driven rigor, and architectural integrity, every feature must be developed as an isolated vertical slice following this exact protocol:

## Protocol Steps

1. **State 5-Line Plan:** Before writing code, state a concise 5-line implementation plan describing what will be built, tested, and verified.
2. **Implement:** Write the production code for the slice in the appropriate `src/` modules.
3. **Write Tests:** Create dedicated unit and integration tests under `tests/` covering functional behavior, edge cases, and failure modes.
4. **Run Tests:** Execute `pytest tests/ -v` and verify that all tests pass (100% pass rate).
5. **Update Progress & Stop:** Record the completed slice, test results, and status in `docs/PROGRESS.md`, then stop and await confirmation.

## Guardrail
**Never begin the next slice until all tests for the current slice pass completely.**
