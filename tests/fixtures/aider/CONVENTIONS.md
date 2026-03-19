# Coding Conventions

## Language

All code should be written in Python 3.10+ using type hints.

## Style

- Use ruff for linting and formatting.
- Maximum line length is 100 characters.
- Prefer dataclasses over plain dicts for structured data.
- Every public function must have a docstring.

## Testing

- Use pytest for all tests.
- Tests should be independent and not share mutable state.
- Coverage must stay above 80%.

## Architecture

- Prefer composition over inheritance.
- Keep modules under 300 lines.
- Use dependency injection for external services.
- All I/O should happen at the boundary, not in business logic.

## Git

- Commits should be atomic and self-contained.
- Branch names follow the pattern: type/short-description.
- Pull requests require at least one approval before merge.

## Security

- Never commit secrets or credentials.
- Validate all external input at system boundaries.
- Use parameterized queries for database access.
