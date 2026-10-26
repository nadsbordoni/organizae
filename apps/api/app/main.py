from fastapi import FastAPI

from app.modules.assistant.exceptions import AssistantError
from app.modules.assistant.router import assistant_error_handler
from app.modules.assistant.router import router as assistant_router
from app.modules.businesses.exceptions import BusinessError
from app.modules.businesses.router import (
    business_error_handler,
)
from app.modules.businesses.router import (
    router as businesses_router,
)
from app.modules.services.exceptions import ServiceError
from app.modules.services.route import router as services_router
from app.modules.services.route import service_error_handler

app = FastAPI(
    title="Organizaê API",
    description="API de gerenciamento e agendamentos",
    version="0.1.0",
)

app.include_router(businesses_router, prefix="/api/v1")
app.include_router(services_router, prefix="/api/v1")
app.include_router(assistant_router, prefix="/api/v1")
app.add_exception_handler(AssistantError, assistant_error_handler)
app.add_exception_handler(BusinessError, business_error_handler)
app.add_exception_handler(ServiceError, service_error_handler)


@app.get("/health")
def health():
    return {"status": "ok"}
