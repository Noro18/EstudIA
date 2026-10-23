---
name: django-tdd-loop
description: Use this skill when implementing core Django features, views, utility models, or API endpoints.
---

# Strict Django TDD Cycle

You are strictly forbidden from writing functional features without code verification. Execute this exact state machine:

1. **Stage 1 (Red):** Locate the relevant test file or create a new test case under the app's `tests/` directory. Write a unit test using `pytest-django` (fixtures, `@pytest.mark.django_db`). All test-data creation must go through `factory_boy` factories — one `factories.py` per app under `tests/` (pattern from EC-Backlog-Management, adopted Oct 23; see AGENTS.md "Test factories"). Exception: none — even RED-stage tests must be written factory-first; create the factory for a missing test-data entity before the test that needs it. Run the test via the bash tool:
   `uv run pytest <path_to_test>`
   Confirm that the test explicitly fails, and log the failure output to the context tree.
2. **Stage 2 (Green):** Implement the minimum required code adjustments in your models or views to satisfy the failing test. Rerun the command to verify it passes.
3. **Stage 3 (Refactor):** Clean up variable styling, enforce DRY code splits, and optimize queries using `select_related` or `prefetch_related`. Rerun the entire application test suite before finalizing.