"""
Base adapter class defining the interface all data source adapters must implement.
"""

import logging
import time
from abc import ABC, abstractmethod
from typing import Generator, Optional

import requests

from ..config import StateSourceConfig, IngestionSettings
from ..models import UCCFiling

logger = logging.getLogger(__name__)

# HTTP status codes that are transient and worth retrying
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _is_retryable(error: Exception) -> bool:
    """Check if an error is transient and worth retrying."""
    # Network-level transient errors
    if isinstance(error, (requests.ConnectionError, requests.Timeout)):
        return True
    # HTTP errors — only retry on transient status codes
    if isinstance(error, requests.HTTPError) and error.response is not None:
        return error.response.status_code in _RETRYABLE_STATUS_CODES
    # All other exceptions (parse errors, auth errors, etc.) are not retryable
    return False


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
        """Execute a request function with exponential backoff on transient failure.

        Only retries on transient errors (429, 5xx, ConnectionError, Timeout).
        Fails immediately on permanent errors (401, 403, 404, parse errors).

        Args:
            request_fn: Callable that performs the HTTP request.
                        Should raise on failure.
            max_retries: Override for self.settings.max_retries.

        Returns:
            The return value of request_fn on success.

        Raises:
            The last exception if all retries are exhausted, or immediately
            for non-retryable errors.
        """
        retries = max_retries if max_retries is not None else self.settings.max_retries
        last_error = None

        for attempt in range(retries + 1):
            try:
                return request_fn()
            except Exception as e:
                last_error = e
                if not _is_retryable(e):
                    logger.error(
                        "Non-retryable error for %s: %s",
                        self.config.abbreviation, e,
                    )
                    raise
                if attempt < retries:
                    wait = self.settings.retry_backoff_seconds * (2 ** attempt)
                    logger.warning(
                        "Attempt %d/%d failed for %s: %s. Retrying in %.1fs...",
                        attempt + 1, retries + 1, self.config.abbreviation, e, wait,
                    )
                    time.sleep(wait)

        raise last_error
