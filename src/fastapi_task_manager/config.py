from pydantic import BaseModel


class Config(BaseModel):
    # --------- Logging config variables ---------
    level: str = "NOTSET"
    # --------- End of logging config variables ---------

    # --------- App config variables ---------
    app_name: str = __name__
    concurrent_tasks: int = 2
    statistics_redis_expiration: int = 432_000  # 5 days
    # --------- End of app config variables ---------

    # --------- Redis config variables ---------
    redis_host: str
    redis_port: int = 6379
    redis_password: str | None = None
    redis_db: int = 1  # Default Redis database to use
    # --------- End of redis config variables ---------
