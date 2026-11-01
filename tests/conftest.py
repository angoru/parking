from datetime import time

import pytest

from app import calendario


@pytest.fixture(autouse=True)
def hora_fija(monkeypatch):
    """Mediodía, con las reservas ya abiertas: los tests no dependen de la hora a la que se ejecutan."""
    monkeypatch.setattr(calendario, "hora_actual", lambda: time(12, 0))
