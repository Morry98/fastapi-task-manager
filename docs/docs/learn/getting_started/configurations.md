# Configurations

This is the entire code example for the configurations tutorial.

We will see each config in detail with his own section in the next parts of this tutorial.

{* ./docs_src/tutorial/configurations_py310.py *}

## Log Level
{* ./docs_src/tutorial/configurations_py310.py ln[4] *}

//// note | Logger name
The package uses the standard logging library from python and the logger is named `fastapi.task-manager`
////

This configuration is used to set the `log_level` used by the package logger.
The default value is set to `NOTSET` and the suggestion is to keep the default value and manage the logging level, handler and formatters in your application logging configuration.

## Redis Key Prefix
{* ./docs_src/tutorial/configurations_py310.py ln[5] *}

TODO

## Concurrent Tasks
{* ./docs_src/tutorial/configurations_py310.py ln[6] *}

TODO

## Statistics Redis Expiration
{* ./docs_src/tutorial/configurations_py310.py ln[7] *}

TODO

## Redis Host
{* ./docs_src/tutorial/configurations_py310.py ln[8] *}

TODO

## Redis Port
{* ./docs_src/tutorial/configurations_py310.py ln[9] *}

TODO

## Redis Password
{* ./docs_src/tutorial/configurations_py310.py ln[10] *}

TODO

## Redis DB
{* ./docs_src/tutorial/configurations_py310.py ln[11] *}

TODO
