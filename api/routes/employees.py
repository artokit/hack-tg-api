from fastapi import APIRouter, Depends, HTTPException, Query

from depends import get_current_user, get_employee_service
from schemas.employees import EmployeeCreate, EmployeePage, EmployeeRead
from services.employees import EmployeeService

router = APIRouter(tags=["employees"], dependencies=[Depends(get_current_user)])


@router.get("/employees", response_model=EmployeePage)
async def get_employees(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    service: EmployeeService = Depends(get_employee_service),
):
    return await service.get_all(page, page_size)


@router.post(
    "/employees",
    response_model=EmployeeRead,
    status_code=201,
)
async def create_employee(
    data: EmployeeCreate,
    service: EmployeeService = Depends(get_employee_service),
):
    try:
        return await service.create(data)
    except ValueError as error:
        raise HTTPException(status_code=409, detail="Employee already exists") from error


@router.get(
    "/employees/by-telegram-id/{telegram_id}", response_model=EmployeeRead
)
async def get_employee_by_telegram_id(
    telegram_id: int,
    service: EmployeeService = Depends(get_employee_service),
):
    employee = await service.get_by_telegram_id(telegram_id)
    if employee is None:
        raise HTTPException(status_code=404, detail="Employee not found")
    return employee
