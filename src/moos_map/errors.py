class MoosMapError(Exception):
    """Base exception for expected, user-facing failures."""


class ValidationError(MoosMapError):
    """Input or output failed validation."""


class SourcePolicyError(MoosMapError):
    """The selected provider does not permit this operation."""


class FetchError(MoosMapError):
    """A source tile could not be acquired or decoded."""
