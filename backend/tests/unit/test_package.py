import ledgerlens


def test_package_exposes_version() -> None:
    assert ledgerlens.__version__ == "0.1.0"
