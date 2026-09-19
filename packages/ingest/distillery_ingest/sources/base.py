"""Abstract route source interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal

from distillery_ingest.models import RouteInfo

SourceName = Literal["connect", "ssh", "public", "fixture"]


class RouteSource(ABC):
    name: SourceName

    @abstractmethod
    def available(self) -> bool:
        """True when credentials / connectivity allow this source."""

    @abstractmethod
    def list_routes(self, *, limit: int = 20) -> list[RouteInfo]:
        """List recent routes for the configured dongle."""

    @abstractmethod
    def get_route(self, route_id: str) -> RouteInfo | None:
        """Fetch one route with segments + cam metadata."""
