from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.modules.appointments.notifications import send_email
from app.modules.password_recovery.schemas import (
    PasswordRecoveryRequest,
    PasswordRecoveryResponse,
)
from app.modules.password_recovery.service import PasswordRecoveryService

router = APIRouter(prefix="/auth", tags=["Auth"])


def get_password_recovery_service(
    session: Annotated[Session, Depends(get_db)],
) -> PasswordRecoveryService:
    return PasswordRecoveryService(session, settings.PASSWORD_RESET_URL)


@router.post(
    "/password-recovery",
    response_model=PasswordRecoveryResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def request_password_recovery(
    data: PasswordRecoveryRequest,
    background_tasks: BackgroundTasks,
    service: Annotated[PasswordRecoveryService, Depends(get_password_recovery_service)],
) -> PasswordRecoveryResponse:
    message = service.request(data.email)
    if message is not None:
        background_tasks.add_task(send_email, *message)
    return PasswordRecoveryResponse()
