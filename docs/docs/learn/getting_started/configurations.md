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

This configuration is used as custom prefix for all the keys used by the package in redis. Pay attention to make it unique if you are using the same redis instance for multiple applications on the same redis db.  
Default value is `__name__`.

## Concurrent Tasks
{* ./docs_src/tutorial/configurations_py310.py ln[6] *}

This configuration is used to set the maximum number of concurrent tasks that can be executed by each worker.  
Default value is `2`.

## Statistics Redis Expiration
{* ./docs_src/tutorial/configurations_py310.py ln[7] *}

TODO

## Statistics History Runs
{* ./docs_src/tutorial/configurations_py310.py ln[8] *}

TODO

## Redis Host
{* ./docs_src/tutorial/configurations_py310.py ln[9] *}

TODO

## Redis Port
{* ./docs_src/tutorial/configurations_py310.py ln[10] *}

TODO

## Redis Password
{* ./docs_src/tutorial/configurations_py310.py ln[11] *}

TODO

## Redis DB
{* ./docs_src/tutorial/configurations_py310.py ln[12] *}

TODO
