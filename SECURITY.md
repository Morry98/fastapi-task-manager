# Security Policy

## Supported Versions

Security fixes are released as a new patch version of the latest minor release. Older minor releases do not receive backports, so upgrade to the latest release to get fixes.

| Version              | Supported |
|----------------------|-----------|
| Latest 1.x minor     | Yes       |
| Older 1.x minors     | No        |
| < 1.0                | No        |

## Reporting a Vulnerability

**Do NOT open a public GitHub issue, discussion or pull request for security vulnerabilities.**

Report vulnerabilities privately through GitHub Security Advisories:

1. Go to the [Security tab](https://github.com/Morry98/fastapi-task-manager/security) of the repository.
2. Click **Report a vulnerability**.
3. Fill in the form.

If you cannot use GitHub, send an email to **matteo.morando98@gmail.com** instead.

Please include:

- A description of the vulnerability and the affected versions
- Steps to reproduce it, or a minimal proof of concept
- The potential impact
- Any suggested fix (if available)

## Response Timeline

This project is maintained by a single maintainer on a best-effort basis. The targets below are goals, not guarantees:

- **Acknowledgement**: within 7 days
- **Initial assessment**: within 14 days
- **Fix and disclosure**: as soon as a patch is ready; we will keep you informed of progress and agree on a disclosure date with you

## Scope

The following are **not** considered vulnerabilities in this library:

- **Unauthenticated access to the management router.** The router returned by `get_manager_router()` has no built-in authentication by design; protecting it is the responsibility of the application that mounts it (see [Known Issues](https://fastapi-task-manager.morry98.com/known-issues.html)). Missing or incorrect documentation about this is welcome as a regular issue.
- **Attacks that require write access to the Redis instance** used by the library. Anyone who can write to that Redis can control task scheduling; secure Redis with authentication and network isolation.
- **Behavior of the task functions** registered by the application, including what they do with the arguments they receive.
- **Vulnerabilities in dependencies** (FastAPI, Starlette, redis-py, Pydantic, cronsim) that are not exploitable through this library. Report them to the affected project.
- **Denial of service caused by the application configuration**, such as very frequent cron expressions or a high `concurrent_tasks` value.

## Disclosure Policy

We follow a coordinated disclosure process. We ask that you:

1. Allow us reasonable time to investigate and address the issue before public disclosure
2. Avoid exploiting the vulnerability beyond what is necessary to demonstrate it
3. Do not access or modify other users' data

Fixed vulnerabilities are published as GitHub Security Advisories. We will credit reporters in the advisory and in the release notes, unless anonymity is preferred.
