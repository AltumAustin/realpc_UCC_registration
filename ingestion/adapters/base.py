"""
Base adapter class defining the interface all data source adapters must implement.
"""

import logging
import time
from abc import ABC, abstractmethod
from typing import Generator, Optional

from ..config import StateSourceConfig, IngestionSettings
from ..models import UCCFiling

logger = logging.getLogger(__name__)


class BaseAdapter(ABC):
    """Abstract base for all data source adapters."""

    def __init__(self, config: StateSourceConfig, settings: IngestionSettings):
        self.config = config
        self.settings = settings

    @abstractmethod
    def fetch(self, since: Optional[str] = None) -> Generator[UCCFiling, None, None]:
        """Fetch UCC filings, optionally only those filed since a given date.

        Args:
            since: ISO 8601 date string. If provided, only return filings
                   filed on or after this date (for incremental pulls).

        Yields:
            UCCFiling objects normalized to our common schema.
        """
        ...

    @abstractmethod
    def test_connection(self) -> bool:
        """Verify that the data source is reachable and credentials work."""
        ...

    def _retry_request(self, request_fn, max_retries: Optional[int] = None):
        """Execute a request function with exponential backoff on failure.

        Args:
            request_fn: Callable that performs the HTTP request.
                        Should raise on failure.
            max_retries: Override for self.settings.max_retries.

        Returns:
            The return value of request_fn on success.

        Raises:
            The last exception if all retries are exhausted.
        """
        retries = max_retries if max_retries is not None else self.settings.max_retries
        last_error = None

        for attempt in range(retries + 1):
            try:
                return request_fn()
            except Exception as e:
                last_error = e
                if attempt < retries:
                    wait = self.settings.retry_backoff_seconds * (2 ** attempt)
                    logger.warning(
                        "Attempt %d/%d failed for %s: %s. Retrying in %.1fs...",
                        attempt + 1, retries + 1, self.config.abbreviation, e, wait,
                    )
                    time.sleep(wait)

        raise last_error
