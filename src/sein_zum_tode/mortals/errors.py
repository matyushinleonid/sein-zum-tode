class MortalRepositoryError(Exception):
    pass


class MortalQuotaExhaustedError(MortalRepositoryError):
    pass
