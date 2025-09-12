"""Composio Test Auth Provider - provides authentication services for other integrations."""

import time
from typing import Any, Dict, List, Optional

import httpx
from fastapi import HTTPException

from airweave.platform.auth.schemas import AuthType
from airweave.platform.auth_providers._base import BaseAuthProvider
from airweave.platform.decorators import auth_provider


@auth_provider(
    name="Composio",
    short_name="composio",
    auth_type=AuthType.api_key,
    auth_config_class="ComposioAuthConfig",
    config_class="ComposioConfig",
)
class ComposioAuthProvider(BaseAuthProvider):
    """Composio authentication provider."""

    # Mapping of Composio field names to Airweave field names
    # Key: Composio field name, Value: Airweave field name
    FIELD_NAME_MAPPING = {
        "generic_api_key": "api_key",  # Stripe and other API key sources
        "access_token": "personal_access_token",  # GitHub and other OAuth sources
        # Add more mappings as needed
    }

    # Mapping of Airweave source short names to Composio toolkit slugs
    # Key: Airweave short name, Value: Composio slug
    SLUG_NAME_MAPPING = {
        "google_drive": "googledrive",
        "google_calendar": "googlecalendar",
        "outlook_mail": "outlook",
        "outlook_calendar": "outlook",
        "onedrive": "one_drive",
        # Previously blocked sources - now supported
        "confluence": "confluence",
        "jira": "jira",
        "bitbucket": "bitbucket",
        "github": "github",
        "ctti": "ctti",  # May need to verify this slug
        "monday": "monday",
        "postgresql": "postgresql",  # May need to verify this slug
        # Add more mappings as needed
    }

    def __init__(self):
        """Initialize the Composio auth provider with caching."""
        super().__init__()
        self._cache_ttl = 3600  # 1 hour
        self._auth_fields_cache = {}  # Cache for auth fields per toolkit

    @classmethod
    async def create(
        cls, credentials: Optional[Any] = None, config: Optional[Dict[str, Any]] = None
    ) -> "ComposioAuthProvider":
        """Create a new Composio auth provider instance.

        Args:
            credentials: Auth credentials containing api_key
            config: Configuration parameters

        Returns:
            A Composio test auth provider instance
        """
        instance = cls()
        instance.api_key = credentials["api_key"]
        instance.auth_config_id = config["auth_config_id"]
        instance.account_id = config["account_id"]
        return instance

    def _get_composio_slug(self, airweave_short_name: str) -> str:
        """Get the Composio toolkit slug for an Airweave source short name.

        Args:
            airweave_short_name: The Airweave source short name

        Returns:
            The corresponding Composio toolkit slug
        """
        return self.SLUG_NAME_MAPPING.get(airweave_short_name, airweave_short_name)

    async def _get_with_auth(
        self, client: httpx.AsyncClient, url: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Make authenticated API request using Composio API key.

        Args:
            client: HTTP client
            url: API endpoint URL
            params: Optional query parameters

        Returns:
            JSON response

        Raises:
            httpx.HTTPStatusError: If the request fails
        """
        headers = {"x-api-key": self.api_key}

        try:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            self.logger.error(f"HTTP error from Composio API: {e.response.status_code} for {url}")
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error accessing Composio API: {url}, {str(e)}")
            raise

    async def get_creds_for_source(
        self, source_short_name: str, source_auth_config_fields: List[str]
    ) -> Dict[str, Any]:
        """Get credentials for a specific source integration.

        Args:
            source_short_name: The short name of the source to get credentials for
            source_auth_config_fields: The fields required for the source auth config

        Returns:
            Credentials dictionary for the source

        Raises:
            HTTPException: If no credentials found for the source
        """
        self.logger.info(
            f"🚨 [DEBUG] Composio get_creds_for_source called for {source_short_name} with fields {source_auth_config_fields}"
        )
        # Map Airweave source name to Composio slug if needed
        composio_slug = self._get_composio_slug(source_short_name)

        self.logger.info(
            f"🔍 [Composio] Starting credential retrieval for source '{source_short_name}'"
        )
        if composio_slug != source_short_name:
            self.logger.info(
                f"📝 [Composio] Mapped source name '{source_short_name}' "
                f"to Composio slug '{composio_slug}'"
            )

        self.logger.info(f"📋 [Composio] Required auth fields: {source_auth_config_fields}")
        self.logger.info(
            f"🔑 [Composio] Using auth_config_id='{self.auth_config_id}', "
            f"account_id='{self.account_id}'"
        )

        async with httpx.AsyncClient() as client:
            # Get accounts matching the source
            source_connected_accounts = await self._get_source_connected_accounts(
                client, composio_slug, source_short_name
            )

            # Find the matching connection
            source_creds_dict = self._find_matching_connection(
                source_connected_accounts, source_short_name
            )

            # Map and validate required fields
            found_credentials = self._map_and_validate_fields(
                source_creds_dict, source_auth_config_fields, source_short_name
            )

            # TODO: pagination

            self.logger.info(f"\n🔑 [Composio] Found credentials: {found_credentials}\n")
            return found_credentials

    async def _get_source_connected_accounts(
        self, client: httpx.AsyncClient, composio_slug: str, source_short_name: str
    ) -> List[Dict[str, Any]]:
        """Get connected accounts for a specific source from Composio.

        Args:
            client: HTTP client
            composio_slug: The Composio toolkit slug
            source_short_name: The original source short name

        Returns:
            List of connected accounts for the source

        Raises:
            HTTPException: If no accounts found for the source
        """
        self.logger.info("🌐 [Composio] Fetching connected accounts from Composio API...")

        connected_accounts_response = await self._get_with_auth(
            client,
            "https://backend.composio.dev/api/v3/connected_accounts",
        )

        total_accounts = len(connected_accounts_response.get("items", []))
        self.logger.info(f"\n📊 [Composio] Total connected accounts found: {total_accounts}\n")

        # Log all available toolkits/slugs for debugging
        all_toolkits = {
            acc.get("toolkit", {}).get("slug", "unknown")
            for acc in connected_accounts_response.get("items", [])
        }
        self.logger.info(f"\n🔧 [Composio] Available toolkit slugs: {sorted(all_toolkits)}\n")

        source_connected_accounts = [
            connected_account
            for connected_account in connected_accounts_response.get("items", [])
            if connected_account.get("toolkit", {}).get("slug") == composio_slug
        ]

        self.logger.info(
            f"\n🎯 [Composio] Found {len(source_connected_accounts)} accounts matching "
            f"slug '{composio_slug}'\n"
        )

        if not source_connected_accounts:
            self.logger.error(
                f"\n❌ [Composio] No connected accounts found for slug '{composio_slug}'. "
                f"Available slugs: {sorted(all_toolkits)}\n"
            )
            raise HTTPException(
                status_code=404,
                detail=f"No connected accounts found for source "
                f"'{source_short_name}' (Composio slug: '{composio_slug}') in Composio.",
            )

        # Log details of each matching account
        for i, account in enumerate(source_connected_accounts):
            acc_id = account.get("id")
            int_id = account.get("auth_config", {}).get("id")
            self.logger.info(
                f"\n  📌 Account {i + 1}: account_id='{acc_id}', auth_config_id='{int_id}'\n"
            )

        return source_connected_accounts

    def _find_matching_connection(
        self, source_connected_accounts: List[Dict[str, Any]], source_short_name: str
    ) -> Dict[str, Any]:
        """Find the matching connection in the list of connected accounts.

        Args:
            source_connected_accounts: List of connected accounts
            source_short_name: The source short name

        Returns:
            The credential dictionary for the matching connection

        Raises:
            HTTPException: If no matching connection found
        """
        source_creds_dict = None

        for connected_account in source_connected_accounts:
            account_id = connected_account.get("id")
            auth_config_id = connected_account.get("auth_config", {}).get("id")

            self.logger.debug(
                f"🔍 [Composio] Checking account: auth_config_id='{auth_config_id}' "
                f"(looking for '{self.auth_config_id}'), account_id='{account_id}' "
                f"(looking for '{self.account_id}')"
            )

            if auth_config_id == self.auth_config_id and account_id == self.account_id:
                self.logger.info(
                    f"\n✅ [Composio] Found matching connection! "
                    f"auth_config_id='{auth_config_id}', account_id='{account_id}'\n"
                )
                source_creds_dict = connected_account.get("state", {}).get("val")

                # Log available credential fields
                if source_creds_dict:
                    available_fields = list(source_creds_dict.keys())
                    self.logger.info(
                        f"\n🔓 [Composio] Available credential fields: {available_fields}\n"
                    )
                    for field, value in source_creds_dict.items():
                        if isinstance(value, str) and len(value) > 10:
                            preview = f"{value[:5]}...{value[-3:]}"
                        else:
                            preview = "<non-string or short value>"
                        self.logger.debug(f"\n  - {field}: {preview}\n")
                break

        if not source_creds_dict:
            self.logger.error(
                f"\n❌ [Composio] No matching connection found with "
                f"auth_config_id='{self.auth_config_id}' and account_id='{self.account_id}'\n"
            )
            raise HTTPException(
                status_code=404,
                detail=f"No matching connection in Composio with auth_config_id="
                f"'{self.auth_config_id}' and account_id='{self.account_id}' "
                f"for source '{source_short_name}'.",
            )

        return source_creds_dict

    def _map_and_validate_fields(
        self,
        source_creds_dict: Dict[str, Any],
        source_auth_config_fields: List[str],
        source_short_name: str,
    ) -> Dict[str, Any]:
        """Map Composio fields to Airweave fields and validate all required fields exist.

        Args:
            source_creds_dict: The credentials dictionary from Composio
            source_auth_config_fields: Required auth fields for the source
            source_short_name: The source short name

        Returns:
            Dictionary with mapped credentials (Airweave field names as keys)

        Note:
            Fields not provided by Composio will be marked as missing and need to be
            provided by the user (e.g., repo_name for GitHub).
        """
        missing_fields = []
        found_credentials = {}

        self.logger.info("🔍 [Composio] Checking for required auth fields...")

        # Only check for fields that Composio can actually provide
        # Composio can provide: access_token (mapped to personal_access_token), generic_api_key (mapped to api_key)
        composio_provided_fields = set(self.FIELD_NAME_MAPPING.values())

        for airweave_field in source_auth_config_fields:
            # Only check fields that Composio can provide
            if airweave_field not in composio_provided_fields:
                self.logger.info(
                    f"\n  ⏭️ Skipping field '{airweave_field}' - not provided by Composio\n"
                )
                continue

            # Check if we have a mapping from Composio to Airweave
            composio_field = None
            for composio_key, airweave_value in self.FIELD_NAME_MAPPING.items():
                if airweave_value == airweave_field:
                    composio_field = composio_key
                    break

            # If no mapping found, use the field name as-is
            if composio_field is None:
                composio_field = airweave_field

            if airweave_field != composio_field:
                self.logger.info(
                    f"\n  🔄 Mapped Composio field '{composio_field}' to Airweave field '{airweave_field}'\n"
                )

            if composio_field in source_creds_dict:
                # Store with the original Airweave field name
                found_credentials[airweave_field] = source_creds_dict[composio_field]
                self.logger.info(
                    f"\n  ✅ Found field: '{airweave_field}' (from Composio field '{composio_field}')\n"
                )
            else:
                missing_fields.append(airweave_field)
                self.logger.warning(
                    f"\n  ❌ Missing field: '{airweave_field}' (looked for "
                    f"Composio field '{composio_field}')\n"
                )

        if missing_fields:
            available_fields = list(source_creds_dict.keys())
            self.logger.warning(
                f"\n⚠️ [Composio] Some fields not available from Composio: {missing_fields}. "
                f"These will need to be provided by the user. "
                f"Available in Composio: {available_fields}\n"
            )
            # Don't raise an error - let the system handle missing fields
            # The user will need to provide the missing fields separately

        self.logger.info(
            f"\n✅ [Composio] Successfully retrieved {len(found_credentials)} credential fields "
            f"for source '{source_short_name}'. "
            f"Fields provided: {list(found_credentials.keys())}. "
            f"Fields still needed from user: {missing_fields if missing_fields else 'none'}\n"
        )

        return found_credentials

    # Phase 1: New capability checking methods

    async def can_handle_source(self, source_short_name: str) -> bool:
        """Check if this auth provider can handle the given source.

        This checks if Composio supports this source

        Args:
            source_short_name: The source to check (e.g., 'github', 'slack')

        Returns:
            True if Composio supports this source in general, False otherwise
        """
        try:
            # Map Airweave source to Composio slug
            composio_slug = self._get_composio_slug(source_short_name)

            # Check if Composio supports this toolkit (general support, not personal connections)
            async with httpx.AsyncClient() as client:
                try:
                    # Get toolkit details to check if it exists and is enabled
                    toolkit_response = await self._get_with_auth(
                        client,
                        f"https://backend.composio.dev/api/v3/toolkits/{composio_slug}",
                    )

                    # Check if toolkit is enabled and has auth config details
                    if not toolkit_response.get("enabled", False):
                        self.logger.debug(f"Toolkit '{composio_slug}' is disabled in Composio")
                        return False

                    if not toolkit_response.get("auth_config_details"):
                        self.logger.debug(f"Toolkit '{composio_slug}' has no auth config details")
                        return False

                    return True

                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 404:
                        self.logger.debug(f"Toolkit '{composio_slug}' not found in Composio")
                        return False
                    else:
                        self.logger.error(f"HTTP error checking toolkit '{composio_slug}': {e}")
                        return False

        except Exception as e:
            self.logger.error(f"Error checking if can handle source '{source_short_name}': {e}")
            return False

    async def _get_composio_auth_fields(self, composio_slug: str) -> List[str]:
        """Get available auth fields for a Composio toolkit.

        This calls Composio's API to get auth config creation fields.
        """
        # Check cache first
        if composio_slug in self._auth_fields_cache:
            cache_entry = self._auth_fields_cache[composio_slug]
            if time.time() < cache_entry["expiry"]:
                return cache_entry["fields"]

        try:
            async with httpx.AsyncClient() as client:
                # Get toolkit details which includes auth config details
                response = await self._get_with_auth(
                    client,
                    f"https://backend.composio.dev/api/v3/toolkits/{composio_slug}",
                )

                # Extract auth fields from the toolkit response
                fields = []
                auth_config_details = response.get("auth_config_details", [])
                for auth_config in auth_config_details:
                    auth_config_creation = auth_config.get("fields", {}).get(
                        "auth_config_creation", {}
                    )

                    # Add required fields
                    for field in auth_config_creation.get("required", []):
                        field_name = field.get("name")
                        if field_name:
                            fields.append(field_name)

                    # Add optional fields
                    for field in auth_config_creation.get("optional", []):
                        field_name = field.get("name")
                        if field_name:
                            fields.append(field_name)

                # Cache the result
                self._auth_fields_cache[composio_slug] = {
                    "fields": fields,
                    "expiry": time.time() + self._cache_ttl,
                }

                self.logger.info(f"Retrieved auth fields for {composio_slug}: {fields}")
                return fields

        except Exception as e:
            self.logger.error(f"Error getting auth fields for {composio_slug}: {e}")
            # Return empty list if API call fails
            return []

    def _get_auth_scheme_for_source(self, source_short_name: str) -> str:
        """Determine what auth scheme a source should use in Composio.

        This is a simplified mapping based on common patterns.
        In a real implementation, this would be more sophisticated.
        """
        # Map based on common source patterns
        if source_short_name in ["github", "bitbucket"]:
            return "API_KEY"
        elif source_short_name in ["confluence", "jira", "monday"]:
            return "OAUTH2"
        elif source_short_name in ["postgresql", "mysql", "sqlite"]:
            return "BASIC"
        else:
            return "API_KEY"  # default
