from fastapi import FastAPI

from lifespan import internal_lifespan
from routes.tickets import private_router as tickets_router

app = FastAPI(title="БАРС Internal API", lifespan=internal_lifespan)
app.include_router(tickets_router)
