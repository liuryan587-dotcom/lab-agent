from email import errors
from os import error

from fastapi import Request
from fastapi.responses import JSONResponse
from app.common.response import Response
from fastapi.exceptions import HTTPException
from fastapi.exceptions import RequestValidationError


class BusinessException(Exception):
    """
    自定义的业务异常类
    """

    def __init__(self, code: int, message: str):
        self.message = message
        self.code = code
        super().__init__(message)


async def business_exception_handler(request: Request, exc: BusinessException):
    """
    处理自定义的业务异常
    """
    return JSONResponse(
        status_code=200,
        content=Response.error(code=exc.code, message=exc.message).model_dump(),
    )


async def http_exception_handler(request: Request, exc: HTTPException):
    """
    http异常处理器
    """
    return JSONResponse(
        status_code=exc.status_code,
        content=Response.error(code=exc.status_code, message=exc.detail).model_dump(),
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    参数异常处理器
    """
    errors = []
    for e in exc.errors():
        field = e["loc"][-1] if e["loc"] else "unknown"
        errors.append({"field": field, "message": e["msg"]})

    return JSONResponse(
        status_code=422,
        content=Response.error(
            code=422, message="请求参数校验错误", data=errors
        ).model_dump(),
    )


async def global_exception_handler(request: Request, exc: Exception):
    """
    全局异常处理器
    """
    return JSONResponse(
        status_code=500,
        content=Response.error(code=500, message="服务器内部错误").model_dump(),
    )
