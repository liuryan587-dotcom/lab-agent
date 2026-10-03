from sqlalchemy.orm import Session
from app.schemas.auth import LoginRequest, LoginResponse, RegisterRequest
from app.models.user import User
from app.utils.password import verify_password, hash_password
from app.utils.jwt import create_access_token
from app.common.exceptions import BusinessException
from app.schemas.user import UserResponse
from sqlalchemy.exc import IntegrityError


def login(db: Session, data: LoginRequest):
    # 根据用户账号查询数据库
    user = db.query(User).filter(User.username == data.username).first()

    # 判断账号和密码是否正确
    if not user or not verify_password(data.password, user.password):
        raise BusinessException(code=400, message="账号或密码错误")

    if user.status != 1:
        raise BusinessException(code=400, message="账号已被禁用，请联系管理员")
    token = create_access_token(user.id)
    return LoginResponse(token=token, user=UserResponse.model_validate(user))


def register(db: Session, data: RegisterRequest):
    user = db.query(User).filter(User.username == data.username).first()

    if user:
        raise BusinessException(code=400, message="账号已存在")

    new_user = User(
        username=data.username,
        password=hash_password(data.password),
        name=data.username,
        role="student",
        status=1,
    )
    try:
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
    except IntegrityError:
        db.rollback()
        raise BusinessException(code=400, message="账号已存在")
