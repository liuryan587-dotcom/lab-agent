from fastapi import APIRouter, Depends
from app.schemas.auth import LoginRequest, RegisterRequest
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.utils.password import verify_password, hash_password
from app.common.response import Response
from app.common.exceptions import BusinessException
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["权限验证"])


@router.post("/login")
def login(data: LoginRequest, db: Session = Depends(get_db)):

    result = auth_service.login(db, data)
    return Response.success(
        message="登录成功",
        data=result,
    )


@router.post("/register")
def register(data: RegisterRequest, db: Session = Depends(get_db)):
    """注册"""
    auth_service.register(db, data)

    return Response.success(message="注册成功")
