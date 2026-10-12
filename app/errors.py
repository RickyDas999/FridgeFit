class InvalidInputError(ValueError):
    """Raised when input to FridgeFit violates a domain rule or would produce a wrong result.

    Subclasses ValueError so generic ``ValueError`` handling still catches it, while callers
    such as the API layer can catch this type specifically.
    """
