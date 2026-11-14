import os

import dotenv
from sqlalchemy.engine import URL

dotenv.load_dotenv(".env")
DB_USER = os.getenv("DB_USER")
DB_NAME = os.getenv("DB_NAME")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_PASS = os.getenv("DB_PASS")
S3_STORAGE_URL = os.getenv("S3_STORAGE_URL")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")

DATABASE_URL = URL.create(
    "postgresql+asyncpg",
    username=DB_USER,
    password=DB_PASS,
    host=DB_HOST,
    port=int(DB_PORT) if DB_PORT else 5432,
    database=DB_NAME,
).render_as_string(hide_password=False)
