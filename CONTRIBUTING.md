# Contributing to FastAPI Task Manager

Thank you for your interest in contributing to FastAPI Task Manager! This guide will help you get started.

## Getting Started

### Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (package manager)
- Redis (for running the full test suite)
- [pre-commit](https://pre-commit.com/)

### Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/Morry98/fastapi-task-manager.git
   cd fastapi-task-manager
   ```
2. Install dependencies:
   ```bash
   uv sync
   ```
3. Install pre-commit hooks:
   ```bash
   pre-commit install
   ```
4. Create a branch for your changes:
   ```bash
   git checkout -b your-branch-name
   ```

> **Tip:** This project includes a `CLAUDE.md` file with detailed instructions for [Claude Code](https://claude.ai/code). If you use Claude Code as your development tool, it will automatically pick up project context, commands, and conventions.

## Development Workflow

### Running Tests

```bash
uv run pytest
```

With coverage:
```bash
uv run coverage run -m pytest && uv run coverage report
```

### Code Quality

The project uses pre-commit hooks that run automatically on `git commit`. You can also run them manually:

```bash
pre-commit run --all-files
```

This includes:
- **Ruff** for linting and formatting (line length: 120)
- **Bandit** for security checks
- **ty** for type checking

### Pruning Stale Tags

Before pushing tags, run the manual pre-commit hook to remove local tags that have been deleted on the remote:

```bash
pre-commit run --hook-stage manual prune-stale-tags
```

It's good practice to run this periodically to keep your local tags in sync with the remote.

### Code Style

- Line length: 120 characters
- Add clear and concise comments to explain non-obvious logic
- All code, comments, and documentation must be in **English**
- Follow existing patterns in the codebase

### Documentation

Documentation is built with MkDocs Material. To preview locally:

```bash
uv run mkdocs serve
```

## How to Contribute

### Reporting Bugs

Use the [Bug Report](https://github.com/Morry98/fastapi-task-manager/issues/new?template=bug_report.yml) issue template. Include:
- Steps to reproduce
- Expected vs actual behavior
- Python version and OS
- Relevant logs or error messages

### Suggesting Features

Use the [Feature Request](https://github.com/Morry98/fastapi-task-manager/issues/new?template=feature_request.yml) issue template. Please describe:
- The problem your feature would solve
- Your proposed solution
- Any alternatives you considered

### Submitting Pull Requests

1. **Open an issue first** to discuss the change, unless it's a small fix
2. Create a branch from `main`
3. Write your code following the project's code style
4. Add or update tests as needed
5. Ensure all checks pass (`pre-commit run --all-files` and `uv run pytest`)
6. Update documentation if your change affects the public API
7. Submit your PR against the `main` branch

#### PR Guidelines

- Keep PRs focused — one feature or fix per PR
- Write a clear title and description
- Reference related issues (e.g., `Closes #123`)
- Be responsive to review feedback

## Project Structure

```
src/fastapi_task_manager/
├── task_manager.py       # Entry point, FastAPI lifespan integration
├── task_group.py         # Task grouping and registration
├── runner.py             # Stream mode orchestrator
├── leader_election.py    # Distributed leader election via Redis
├── coordinator.py        # Task scheduling and stream publishing
├── stream_consumer.py    # Redis Streams consumer groups
├── reconciler.py         # Stale/failed task recovery
├── statistics.py         # Execution history tracking
├── config.py             # Pydantic configuration model
├── redis_keys.py         # Redis key pattern definitions
├── task_router_services.py # Management API service layer
├── async_utils.py        # Shared async utilities
└── schema/               # Pydantic response models
```

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
