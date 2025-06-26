from pydantic import BaseModel


class Config(BaseModel):
    # --------- Logging config variables ---------
    level: str = "WARNING"
    # --------- End of logging config variables ---------

    # --------- Redis config variables ---------
    redis_host: str | None = None
    redis_port: int = 6379
    redis_password: str | None = None
    redis_db: int = 1  # Default Redis database to use
    # --------- End of redis config variables ---------
