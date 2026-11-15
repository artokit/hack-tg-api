class EmployeeCacheUnavailableError(RuntimeError):
    pass


class BanUnavailableError(RuntimeError):
    pass


class ConfluenceNotConfiguredError(RuntimeError):
    pass


class ConfluenceUnavailableError(RuntimeError):
    pass


class ConfluenceTimeoutError(ConfluenceUnavailableError):
    pass
