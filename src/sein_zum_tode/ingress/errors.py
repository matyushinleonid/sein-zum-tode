class IngressError(Exception):
    pass


class UpdateSourceError(IngressError):
    pass


class UpdateStoreError(IngressError):
    pass


class UpdateHandoffError(IngressError):
    pass


class PollingLeaseError(IngressError):
    pass
