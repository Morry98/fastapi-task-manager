from pydantic import BaseModel


class Config(BaseModel):
    # --------- Logging config variables ---------
    level: str = "NOTSET"  # Default log level, can be overridden by log_level
    # --------- End of logging config variables ---------

    # --------- App config variables ---------
    concurrent_tasks: int = 2
    # --------- End of app config variables ---------

    # --------- Redis config variables ---------
    redis_host: str
    redis_port: int = 6379
    redis_password: str | None = None
    redis_db: int = 1  # Default Redis database to use
    # --------- End of redis config variables ---------
