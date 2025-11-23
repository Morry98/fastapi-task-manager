from pydantic import BaseModel


class Config(BaseModel):
    # --------- Logging config variables ---------
    log_level: str = "NOTSET"
    # --------- End of logging config variables ---------

    # --------- App config variables ---------
    redis_key_prefix: str = __name__
    concurrent_tasks: int = 2
    statistics_redis_expiration: int = 432_000  # 5 days
    statistics_history_runs: int = 30
    # --------- End of app config variables ---------

    # --------- Redis config variables ---------
    redis_host: str
    redis_port: int = 6379
    redis_password: str | None = None
    redis_db: int = 1  # Default Redis database to use
    # --------- End of redis config variables ---------
