from tickets.base import TicketSystem
from tickets.jsm import JsmAdapter

# Справочник "имя системы -> класс адаптера".
# Новая система = одна строка здесь + один файл адаптера.
ADAPTERS: dict[str, type[TicketSystem]] = {
    "jsm": JsmAdapter,
}

# Кэш уже созданных адаптеров (аналог AddSingleton: один клиент на систему,
# чтобы не плодить httpx-клиенты на каждый запрос).
_adapters: dict[str, TicketSystem] = {}


def build_adapter(route: dict) -> TicketSystem:
    """Создаёт (или отдаёт уже созданный) адаптер для маршрута из конфига.

    route: {"system": "jsm", ...аргументы конструктора адаптера}
    Остальные ключи route распаковываются в __init__ адаптера.
    """
    name = route["system"]
    if name not in ADAPTERS:
        raise ValueError(f"Unknown ticket system: {name}")
    if name not in _adapters:
        config = {k: v for k, v in route.items() if k != "system"}
        _adapters[name] = ADAPTERS[name](**config)
    return _adapters[name]
