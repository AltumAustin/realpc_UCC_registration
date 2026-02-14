"""
Data source adapters for UCC filing ingestion.

Each adapter knows how to connect to a specific data source type,
fetch records, and yield normalized UCCFiling objects.
"""

from .base import BaseAdapter
from .socrata import SocrataAdapter
from .state_bulk import StateBulkAdapter
from .commercial import CommercialProviderAdapter
