---
title: FastAPI Task Manager
description: Lightweight, efficient and fast to code scheduled task management system built on FastAPI
tags:
  - fastapi
  - task manager
  - scheduling
  - redis
hide:
  - navigation
---


<style>
.md-content .md-typeset h1 { display: none; }
</style>

<p align="center">
  <a href="https://fastapi-task-manager.morando.uk"><img src="assets/images/logo-text-purple.svg" alt="FastAPI Task Manager"></a>
</p>
<p align="center">
    <em>Lightweight, efficient and fast to code scheduled task management system built on FastAPI</em>
</p>

[![PyPI - Version](https://img.shields.io/pypi/v/fastapi-task-manager?style=plastic&color=964de0)](https://pypi.org/project/fastapi-task-manager/){ .external-link target="_blank" }
[![PyPI - Downloads](https://img.shields.io/pypi/dm/fastapi-task-manager?style=plastic&label=pypi%20download&color=964de0)](https://pypi.org/project/fastapi-task-manager/){ .external-link target="_blank" }
[![PyPI - License](https://img.shields.io/pypi/l/fastapi-task-manager?style=plastic&color=964de0)](https://github.com/Morry98/fastapi-task-manager/blob/main/LICENSE){ .external-link target="_blank" }
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/fastapi-task-manager?style=plastic&color=964de0)](https://pypi.org/project/fastapi-task-manager/){ .external-link target="_blank" }
[![Pepy Total Downloads](https://img.shields.io/pepy/dt/fastapi-task-manager?style=plastic&color=964de0)](https://pepy.tech/project/fastapi-task-manager){ .external-link target="_blank" }
[![Coveralls](https://img.shields.io/coverallsCoverage/github/Morry98/fastapi-task-manager?style=plastic&color=964de0)](https://coveralls.io/github/Morry98/fastapi-task-manager){ .external-link target="_blank" }

---

**Documentation**: [https://fastapi-task-manager.morando.uk](https://fastapi-task-manager.morando.uk){ .external-link target="_blank" }

**Source Code**: [https://github.com/Morry98/fastapi-task-manager](https://github.com/Morry98/fastapi-task-manager){ .external-link target="_blank" }

---

## Overview

FastAPI Task Manager is a lightweight and efficient scheduled task management system built on top of FastAPI and Redis. It is designed to help developers easily create, manage, and execute scheduled tasks within their FastAPI applications.

## Key Features

- **FastAPI Extension** - Built as an extension to FastAPI, making it easy to integrate into existing FastAPI applications and leverage its features
- **Redis Streams Architecture** - Uses Redis Streams with leader election for distributed task scheduling and single-instance execution safety
- **Fast to Code** - Increase the speed to develop scheduled tasks by about 400% to 500%, only a wrapper function is needed*
- **Fewer Bugs** - Reduce about 60% of human (developer) induced errors managing lock, Redis keys and task execution*
- **Scheduled Tasks** - Provides a simple and intuitive API for defining and scheduling tasks to run at specific intervals or times
- **Task Management** - Includes FastAPI router with 12 endpoints to manage tasks: disable, enable, trigger, monitor health, and more
- **Dynamic Tasks** - Create and delete tasks at runtime via REST API without redeploying
- **Retry with Backoff** - Automatic exponential backoff on task failures with configurable per-task overrides
- **Fault Tolerant** - Task heartbeat monitoring, automatic reconciliation of stale tasks, and leader failover
- **Easy to Use** - Designed to be easy to use and learn. Less time reading docs
- **Robust** - Get production-ready code

<small>* estimation based on real production task migrated to FastAPI task manager from custom "cron job" solution.</small>

## Requirements

FastAPI Task Manager stands on the shoulders of giants:

- [FastAPI](https://fastapi.tiangolo.com){ .external-link target="_blank" } - Modern, fast web framework for building APIs
- [Redis](https://redis.io/){ .external-link target="_blank" } - In-memory data structure store for task storage and locking

## Installation

//// note | Prerequisites
You need to have a FastAPI project set up. If you don't have one, check the [FastAPI installation tutorial](https://fastapi.tiangolo.com/#installation){ .external-link target="_blank" }.
////

Install FastAPI Task Manager:

//// tab | uv
<!-- termynal -->
```
$ uv add fastapi-task-manager

---> 100%
Resolved XX packages in XXms
Installed 1 package in XXms
  + fastapi-task-manager==x.x.x
```
////

//// tab | pip
<!-- termynal -->
```
$ pip install fastapi-task-manager

---> 100%
Successfully installed fastapi-task-manager
```
////

//// tab | poetry
<!-- termynal -->
```
$ poetry add fastapi-task-manager

---> 100%
Using version ^x.x.x for fastapi-task-manager

Updating dependencies
Resolving dependencies... (0.1s)

Package operations: 1 install, 0 updates, 0 removals
```
////

## Quick Example

Here's a one file simple example to get you started.

In this example, we create a FastAPI application with FastAPI Task Manager integrated.  
We define a scheduled task that runs every five minutes and we include the optional task management router to manage our tasks.

//// note | Non production example
This is a simple example contained in a single file for demonstration purposes only. In a real-world application, you would typically organize your code into multiple files and modules for better maintainability and scalability.  
In learn section of the docs, you can find a more complete explanation of how to set up FastAPI Task Manager in a more structured way.
////


### Imports
{* ./docs_src/tutorial/base_example_py310.py ln[4:5] *}

### FastAPI Task Manager setup
{* ./docs_src/tutorial/base_example_py310.py ln[33:48] *}

### Add task management router
{* ./docs_src/tutorial/base_example_py310.py ln[50:55] *}

### Define a scheduled task
{* ./docs_src/tutorial/base_example_py310.py ln[60:68] *}

## License

This project is licensed under the terms of the [MIT license](https://github.com/Morry98/fastapi-task-manager/blob/main/LICENSE){ .external-link target="_blank" }.
