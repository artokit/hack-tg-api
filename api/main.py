import uvicorn
from fastapi import FastAPI

from lifespan import lifespan
from routes.auth import router as auth_router
from routes.employees import router as employees_router
from routes.health import router as health_router
from routes.tickets import router as tickets_router

app = FastAPI(
    title="БАРС API",
    lifespan=lifespan,
    docs_url="/docs",
    openapi_url="/openapi.json",
)
app.include_router(auth_router)
app.include_router(health_router)
app.include_router(employees_router)
app.include_router(tickets_router)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
