from config import Settings


def user_is_admin(telegram_user_id: int):
    settings = Settings()
    return telegram_user_id in settings.ADMIN_IDS
