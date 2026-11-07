"""Fetch full targeting catalogues or all pages of a location search."""

from collections.abc import Sequence
from typing import Literal

from telead import Client
from telead.models import TargetCountry, TargetLanguage, TargetLocation, TargetTopic

from ..errors import OperationError

TargetCatalog = Literal["languages", "topics", "countries"]
TargetOption = TargetLanguage | TargetTopic | TargetCountry


def get_targeting_options(
    client: Client, *, catalog: TargetCatalog,
) -> Sequence[TargetOption]:
    """Return a full catalogue, preserving API order and repeated entries."""
    if catalog == "languages":
        return client.get_target_languages_list()
    if catalog == "topics":
        return client.get_target_topics_list()
    return client.get_target_countries_list()


def get_target_locations(
    client: Client, *, country_code: str, query: str,
) -> list[TargetLocation]:
    """Fetch all pages of a country-specific location search without caching."""
    if not query.strip():
        raise OperationError("Location search requires a nonblank query.")
    locations: list[TargetLocation] = []
    offset: str | None = None
    seen_offsets: set[str] = set()
    while True:
        page = client.get_target_locations_list(
            country_code, query, offset=offset, limit=100,
        )
        locations.extend(page.locations)
        offset = page.next_offset
        if not offset:
            return locations
        if not page.locations or offset in seen_offsets:
            raise OperationError(
                "Cannot retrieve all locations: the API returned an empty page "
                "with a next cursor or repeated a pagination cursor."
            )
        seen_offsets.add(offset)
