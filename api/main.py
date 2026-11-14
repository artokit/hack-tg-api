import uvicorn
from fastapi import FastAPI

from lifespan import lifespan
from routes.health import router as health_router
from routes.users import router as users_router

app = FastAPI(title="БАРС API", lifespan=lifespan)
app.include_router(users_router)
app.include_router(health_router)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
