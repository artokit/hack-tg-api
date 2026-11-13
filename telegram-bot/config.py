from pydantic import BaseSettings

class Settings(BaseSettings):
    ADMIN_IDS: list[int] = []  # TODO: сделать нормальный парсинг из .env
