import pytest

from material import cloudinary_test_stub


@pytest.fixture(scope="session", autouse=True)
def _offline_cloudinary():
    """Same protection as material.test_runner, for pytest runs."""
    cloudinary_test_stub.start()
    yield
    cloudinary_test_stub.stop()
