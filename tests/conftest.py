import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest  # noqa: E402

from company_people.fetch import Response  # noqa: E402
from company_people.models import CollectorConfig  # noqa: E402


class FakeTransport:
    """Транспорт без сети: словарь URL -> тело (str) | статус (int) | Response."""

    def __init__(self, mapping: dict):
        self.mapping = mapping
        self.requests: list[str] = []

    def get(self, url: str, headers: dict | None = None) -> Response:
        self.requests.append(url)
        value = self.mapping.get(url)
        if value is None:
            return Response(url=url, status=404)
        if isinstance(value, int):
            return Response(url=url, status=value)
        if isinstance(value, Response):
            return value
        return Response(url=url, status=200, text=value)


@pytest.fixture
def config() -> CollectorConfig:
    return CollectorConfig(
        max_pages_per_site=4,
        max_people_per_company=100,
        max_requests_per_run=40,
        min_interval_seconds=0.0,
        timeout_seconds=5.0,
        retries=1,
    )


@pytest.fixture
def fake_transport() -> FakeTransport:
    return FakeTransport({})
