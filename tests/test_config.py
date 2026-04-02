import os

import pytest

from breba_app.config import load_env

mock_stat = {
    "exists": False
}


def test_load_env():
    load_env()
    assert os.getenv("MONGO_URI") is not None


def test_secrets_not_found(mocker):
    mocker.patch("breba_app.config.Path.exists", return_value=False)

    with pytest.raises(FileNotFoundError):
        load_env()
