# Fastapi Task Manager
Lightweight, efficient and fast to code scheduled task management system built on FastAPI.

![PyPI - Version](https://img.shields.io/pypi/v/fastapi-task-manager?style=plastic&color=964de0)
![PyPI - Downloads](https://img.shields.io/pypi/dm/fastapi-task-manager?style=plastic&label=pypi%20download&color=964de0)
![PyPI - License](https://img.shields.io/pypi/l/fastapi-task-manager?style=plastic&color=964de0)
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/fastapi-task-manager?style=plastic&color=964de0)
![Pepy Total Downloads](https://img.shields.io/pepy/dt/fastapi-task-manager?style=plastic&color=964de0)
![Coveralls](https://img.shields.io/coverallsCoverage/github/morry98/fastapi-task-manager?style=plastic&color=964de0)

TODO coverage https://coveralls.io/github/Morry98/fastapi-task-manager

---

**Documentation**: <a href="https://morry98.github.io/fastapi-task-manager" target="_blank">https://morry98.github.io/fastapi-task-manager</a>

**Source Code**: <a href="https://github.com/Morry98/fastapi-task-manager" target="_blank">https://github.com/Morry98/fastapi-task-manager</a>

---

FastAPI task manager is a lightweight and efficient scheduled task management system built on top of FastAPI and Redis. It is designed to help developers easily create, manage, and execute scheduled tasks within their FastAPI applications.

The key features are:

* **FastAPI extension**: Built as an extension to FastAPI, making it easy to integrate into existing FastAPI applications and leverage its features.
* **Redis-based**: Uses Redis as the backend for storing task information, ensuring high performance and single-instance execution.
* **Fast to code**: Increase the speed to develop scheduled tasks by about 400% to 500%, only a wrapper function is needed. *
* **Fewer bugs**: Reduce about 60% of human (developer) induced errors managing lock, Redis keys and task execution. *
* **Scheduled tasks**: Provides a simple and intuitive API for defining and scheduling tasks to run at specific intervals or times.
* **Task management**: Includes FastAPI router to manage tasks, such as pausing, resuming, and monitoring execution information.
* **Easy**: Designed to be easy to use and learn. Less time reading docs.
* **Robust**: Get production-ready code. With automatic interactive documentation.

<small>* estimation based on real production task migrated to FastAPI task manager from custom "cron job" solution.</small>

## Requirements

FastAPI task manager stands on the shoulders of giants:

* <a href="https://fastapi.tiangolo.com" class="external-link" target="_blank">FastAPI</a> for the web framework.
* <a href="https://redis.io/" class="external-link" target="_blank">Redis</a> for task storage and locking.

## Installation

You need to have a FastAPI project set up. If you don't have one, you can create it by following the <a href="https://fastapi.tiangolo.com/#installation" class="external-link" target="_blank">FastAPI installation tutorial</a>.  
Then install FastAPI task manager:

````
<!-- termynal -->

```
$ pip install fastapi-task-manager

---> 100%
Installed
```
````

## License

This project is licensed under the terms of the MIT license.
