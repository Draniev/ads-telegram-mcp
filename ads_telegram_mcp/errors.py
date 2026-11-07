"""Public messages for failures detected by application operations."""


class OperationError(Exception):
    """A local operation failure whose message is safe to return to the caller."""
