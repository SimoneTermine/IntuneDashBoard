"""
Collector for Entra ID groups referenced in Intune assignments.
Only downloads groups that are actually referenced (not all groups).
"""

import json
import logging
from datetime import datetime

from app.db.database import session_scope
from app.db.models import Group, Assignment
from app.graph.client import GraphClient
from app.graph.endpoints import GROUPS, GROUP_SELECT_FIELDS

logger = logging.getLogger(__name__)


class GroupCollector:
    """Downloads only groups referenced in Intune assignments."""

    def __init__(self, client: GraphClient):
        self.client = client

    def sync_groups(self) -> int:
        """
        Find all group IDs referenced in assignments and fetch their metadata.
        Returns count of groups synced.
        """
        logger.info("Collecting referenced group IDs...")

        # Get unique group IDs from assignments table
        with session_scope() as db:
            group_ids = [
                row[0] for row in
                db.query(Assignment.target_id)
                .filter(Assignment.target_type == "group")
                .distinct()
                .all()
            ]

        if not group_ids:
            logger.info("No group assignments found, skipping group sync")
            return 0

        logger.info(f"Fetching metadata for {len(group_ids)} referenced groups...")
        count = 0

        # Batch fetch groups (Graph supports $filter with 'id in (...)' batches)
        batch_size = 15  # Stay well under URL length limits
        for i in range(0, len(group_ids), batch_size):
            batch = group_ids[i:i + batch_size]
            try:
                count += self._fetch_groups_batch(batch)
            except Exception as e:
                logger.error(f"Error fetching group batch: {e}")

        logger.info(f"Groups synced: {count}")
        return count

    def _fetch_groups_batch(self, group_ids: list[str]) -> int:
        """Fetch a batch of groups by ID using $filter."""
        id_filter = " or ".join([f"id eq '{gid}'" for gid in group_ids])
        params = {
            "$filter": id_filter,
            "$select": GROUP_SELECT_FIELDS,
        }
        try:
            items = self.client.get_all(GROUPS, params=params)
        except Exception as e:
            logger.warning(f"Batch group fetch failed: {e}. Falling back to individual fetches.")
            # Fall back to one-by-one
            items = []
            for gid in group_ids:
                try:
                    g = self.client.get(f"groups/{gid}", params={"$select": GROUP_SELECT_FIELDS})
                    items.append(g)
                except Exception as ie:
                    logger.debug(f"Could not fetch group {gid}: {ie}")

        count = 0
        with session_scope() as db:
            for raw in items:
                gid = raw.get("id", "")
                if not gid:
                    continue
                group = db.get(Group, gid) or Group(id=gid)
                group.display_name = raw.get("displayName", "")
                group.description = raw.get("description", "")
                group.group_types = json.dumps(raw.get("groupTypes", []))
                group.mail = raw.get("mail", "")
                is_dynamic = "DynamicMembership" in raw.get("groupTypes", [])
                group.is_dynamic = is_dynamic
                group.synced_at = datetime.utcnow()
                group.raw_json = json.dumps(raw)
                db.merge(group)
                count += 1

        return count

    def get_group_member_count(self, group_id: str) -> int | None:
        """
        Fetch member count for a group.
        Uses $count header (ConsistencyLevel: eventual required).
        Returns None if not available.
        """
        try:
            result = self.client.get(
                f"groups/{group_id}/members/$count",
                params={"ConsistencyLevel": "eventual"},
            )
            return int(result) if isinstance(result, (int, str)) else None
        except Exception as e:
            logger.debug(f"Could not get member count for {group_id}: {e}")
            return None
