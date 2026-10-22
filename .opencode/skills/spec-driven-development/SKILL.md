---
name: spec-driven-development
description: Use this skill whenever starting a new feature, creating complex components, or mapping system architectures.
---

# Spec-Driven Development Protocol

Before altering the application state or creating code files, you must halt execution and complete the following steps:

1. **Write the Spec File:** Create a `.opencode/specs/FEATURE_NAME.md` document.
2. **Mandatory Elements:** The spec document must outline:
   - System architecture and affected components.
   - Database schema changes (Django model definitions, constraints, migrations).
   - Expected input/output payloads and edge-cases (e.g., race conditions, empty data).
3. **Execution Block:** Do not write code or apply patches until the user reviews this file and explicitly responds with "SPEC_APPROVED".