class DomainError(Exception):
    """Базовая ошибка предметной области."""


class NotFound(DomainError):
    pass


class InvalidState(DomainError):
    """Операция недопустима в текущем состоянии объекта (например, approve уже обработанного сообщения)."""


class ValidationError(DomainError):
    """Входные данные нарушают правила предметной области."""
