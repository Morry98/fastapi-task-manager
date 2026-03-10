# About

## FastAPI Task Manager

FastAPI Task Manager is an open-source library that provides scheduled task management for FastAPI applications. It uses Redis for distributed locking, task state persistence, and inter-worker coordination via Redis Streams.

## Goals

- **Simplicity**: Make scheduled task management as easy as decorating a function
- **Reliability**: Ensure tasks run exactly once, even across multiple instances
- **Minimal overhead**: No message broker infrastructure required — just Redis
- **Native integration**: Built as a FastAPI extension, not a standalone service

## License

This project is licensed under the terms of the [MIT license](https://github.com/Morry98/fastapi-task-manager/blob/main/LICENSE){ .external-link target="_blank" }.

## Links

- **Documentation**: [https://fastapi-task-manager.morry98.com](https://fastapi-task-manager.morry98.com){ .external-link target="_blank" }
- **Source Code**: [https://github.com/Morry98/fastapi-task-manager](https://github.com/Morry98/fastapi-task-manager){ .external-link target="_blank" }
- **PyPI**: [https://pypi.org/project/fastapi-task-manager](https://pypi.org/project/fastapi-task-manager){ .external-link target="_blank" }
