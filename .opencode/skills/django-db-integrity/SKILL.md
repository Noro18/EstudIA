---
name: django-db-integrity
description: Trigger this skill automatically whenever any file named models.py or containing database models is created, updated, or deleted.
---

# Django Database Migration Guardrails

1. **Trace Current State:** Run `uv run python manage.py showmigrations` via the terminal tool to capture the current state of the database tree.
2. **Dry Run Check:** After modifying a model, run:
   `uv run python manage.py makemigrations --check --dry-run`
3. **Generate Files:** If anomalies are clear, compile the migration file. Never modify migration files manually unless fixing a circular dependency error.
4. **Validation:** Execute `uv run python manage.py migrate` and run the Django system validation check framework (`uv run python manage.py check`) to ensure no broken configuration relationships exist.