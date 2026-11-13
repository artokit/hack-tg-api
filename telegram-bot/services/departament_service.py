from models.departments import Department

class DepartamentService:
    async def get_user_departments_ids_by_user_id(self, user_id: int) -> list[Department]:
        pass


service = DepartamentService()
