# Release Notes

## Latest Changes

### Reworks

* ♻️ Rename config `app_name` to `redis_key_prefix` to better reflect its purpose.

### Docs

* 📝 Add first implementation of docs available at [https://fastapi-task-manager.morando.uk](https://fastapi-task-manager.morando.uk)

### Internals

* ♻️ Move pre-commit checks from mypy+vermin to [ty from astral](https://docs.astral.sh/ty/)
* ♻️ Change pypi package 'cronexpr'  with 'croniter' due to maintenance issues.
     No side effects in package usage.
* ⬆️ Pre-commit bump uv-pre-commit from 0.9.7 to 0.9.18.
* ⬆️ Pre-commit bump ruff-pre-commit from 0.14.3 to 0.14.10.
* ⬆️ Bump dependencies in uv.lock file, for dev purposes:
   - anyio from 4.11.0 to 4.12.0
   - coverage from 7.11.1 to 7.13.0
   - fastapi from 0.121.0 to 0.126.0
   - markdown-include-variants from 0.0.5 to 0.0.8
   - mkdocs-macros-plugin from 1.4.1 to 1.5.0
   - mkdocs-material from 9.6.23 to 9.7.1
   - platformdirs from 4.5.0 to 4.5.1
   - pydantic from 2.12.4 to 2.12.5
   - pymdown-extensions from 10.16.1 to 10.19.1
   - pytest from 9.0.1 to 9.0.2
   - redis from 7.0.1 to 7.1.0
   - selectolax from 0.4.3 to 0.4.6
   - starlette from 0.49.3 to 0.50.0
   - urllib3 from 2.5.0 to 2.6.2

## 0.7.0 - 2025-xx-xx

TBC
