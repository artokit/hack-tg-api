import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers.files import router as file_router

app = FastAPI(docs_url="/file-service/docs", openapi_url="/file-service/openapi.json")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(file_router, prefix="/file-service")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=3000)
