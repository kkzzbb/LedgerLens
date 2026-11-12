"""The `DEMOBANK_DATABASE_URL` rule: which schemes are accepted, and the driver.

The `postgresql://`, `postgres://` and `postgresql+psycopg://` schemes are
accepted, and the psycopg 3 driver is used. This is the backend's
`DATABASE_URL` rule (#6), written again here because DemoBank imports nothing
from `ledgerlens`. Error messages never contain the URL, which holds the
database password.
"""

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

DRIVER_SCHEME = "postgresql+psycopg"
_ACCEPTED_SCHEMES = {"postgresql", "postgres", DRIVER_SCHEME}


class UnsupportedSchemeError(ValueError):
    """The URL does not start with one of the accepted schemes."""

    def __init__(self) -> None:
        super().__init__(
            "database URL has an unsupported scheme; expected postgresql://, "
            "postgres:// or postgresql+psycopg://"
        )


def database_url(url: str | URL) -> URL:
    """The URL with the psycopg 3 driver.

    Raises `UnsupportedSchemeError` for another scheme (or none), and
    `ValueError` when the URL cannot be parsed. No message contains the URL.
    Accepts a string or a SQLAlchemy `URL` (whose repr hides the password).
    """
    if isinstance(url, URL):
        if url.drivername not in _ACCEPTED_SCHEMES:
            raise UnsupportedSchemeError
        return url.set(drivername=DRIVER_SCHEME)
    scheme, separator, rest = url.strip().partition("://")
    if not separator or scheme not in _ACCEPTED_SCHEMES:
        raise UnsupportedSchemeError
    try:
        return make_url(f"{DRIVER_SCHEME}://{rest}")
    except (ArgumentError, ValueError):
        # SQLAlchemy's message may quote the URL, so it is not chained.
        pass
    raise ValueError("database URL could not be parsed")
