from fastapi import FastAPI

from app.modules.businesses.exceptions import BusinessError
from app.modules.businesses.router import (
    business_error_handler,
    router as businesses_router,
)

app = FastAPI(
    title="Organizaê API",
    description="API de gerenciamento e agendamentos",
    version="0.1.0",
)

app.include_router(businesses_router, prefix="/api/v1")
app.add_exception_handler(BusinessError, business_error_handler)


@app.get("/health")
def health():
    return {"status": "ok"}