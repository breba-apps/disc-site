import os

import pytest

from breba_app.config import load_env, init_db


def test_load_env():
    load_env()
    assert os.getenv("MONGO_URI") is not None


def test_secrets_not_found(mocker):
    mocker.patch("breba_app.config.Path.exists", return_value=False)

    with pytest.raises(FileNotFoundError):
        load_env()

@pytest.mark.asyncio
async def test_init_db__without_load_env():
    with pytest.raises(ValueError):
        await init_db()
