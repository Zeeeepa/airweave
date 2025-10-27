"""Clean source connection schemas with automatic auth method inference.

This module provides a clean schema hierarchy for source connections:
- Input schemas for create/update operations
- Response schemas optimized for API endpoints with computed fields
- Builder classes with type-safe construction and validation
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional, Union
from uuid import UUID

from pydantic import BaseModel, Field, computed_field, model_validator

from airweave.core.shared_models import SourceConnectionStatus, SyncJobStatus


class AuthenticationMethod(str, Enum):
    """Authentication methods for source connections."""

    DIRECT = "direct"
    OAUTH_BROWSER = "oauth_browser"
    OAUTH_TOKEN = "oauth_token"
    OAUTH_BYOC = "oauth_byoc"
    AUTH_PROVIDER = "auth_provider"


class OAuthType(str, Enum):
    """OAuth token types for sources."""

    OAUTH1 = "oauth1"  # OAuth 1.0a flow (consumer key/secret)
    ACCESS_ONLY = "access_only"  # Just access token, no refresh
    WITH_REFRESH = "with_refresh"  # Access + refresh token
    WITH_ROTATING_REFRESH = "with_rotating_refresh"  # Refresh token rotates on use


# ===========================
# Schedule Configuration
# ===========================


class ScheduleConfig(BaseModel):
    """Schedule configuration for syncs."""

    cron: Optional[str] = Field(None, description="Cron expression for scheduled syncs")
    continuous: bool = Field(False, description="Enable continuous sync mode")
    cursor_field: Optional[str] = Field(None, description="Field for incremental sync")


# ===========================
# Authentication Schemas - Nested structure without explicit type fields
# ===========================


class DirectAuthentication(BaseModel):
    """Direct authentication with API keys or passwords."""

    credentials: Dict[str, Any] = Field(..., description="Authentication credentials")

    @model_validator(mode="after")
    def validate_credentials(self):
        """Ensure credentials are not empty."""
        if not self.credentials:
            raise ValueError("Credentials cannot be empty")
        return self


class OAuthTokenAuthentication(BaseModel):
    """OAuth authentication with pre-obtained token."""

    access_token: str = Field(..., description="OAuth access token")
    refresh_token: Optional[str] = Field(None, description="OAuth refresh token")
    expires_at: Optional[datetime] = Field(None, description="Token expiry time")

    @model_validator(mode="after")
    def validate_token(self):
        """Validate token is not expired."""
        if self.expires_at and self.expires_at < datetime.utcnow():
            raise ValueError("Token has already expired")
        return self


class OAuthBrowserAuthentication(BaseModel):
    """OAuth authentication via browser flow.

    Supports both OAuth2 and OAuth1 BYOC (Bring Your Own Client):
    - OAuth2 BYOC: Provide client_id + client_secret
    - OAuth1 BYOC: Provide consumer_key + consumer_secret
    """

    redirect_uri: Optional[str] = Field(None, description="OAuth redirect URI")

    # OAuth2 BYOC fields
    client_id: Optional[str] = Field(None, description="OAuth2 client ID (for custom apps)")
    client_secret: Optional[str] = Field(None, description="OAuth2 client secret (for custom apps)")

    # OAuth1 BYOC fields
    consumer_key: Optional[str] = Field(None, description="OAuth1 consumer key (for custom apps)")
    consumer_secret: Optional[str] = Field(
        None, description="OAuth1 consumer secret (for custom apps)"
    )

    @model_validator(mode="after")
    def validate_byoc_credentials(self):
        """Validate BYOC credentials are both provided or neither.

        OAuth2: client_id + client_secret
        OAuth1: consumer_key + consumer_secret
        Cannot mix OAuth1 and OAuth2 credentials.
        """
        has_oauth2 = bool(self.client_id) or bool(self.client_secret)
        has_oauth1 = bool(self.consumer_key) or bool(self.consumer_secret)

        # Validate OAuth2 BYOC
        if bool(self.client_id) != bool(self.client_secret):
            raise ValueError("OAuth2 BYOC requires both client_id and client_secret or neither")

        # Validate OAuth1 BYOC
        if bool(self.consumer_key) != bool(self.consumer_secret):
            raise ValueError(
                "OAuth1 BYOC requires both consumer_key and consumer_secret or neither"
            )

        # Cannot mix OAuth1 and OAuth2 credentials
        if has_oauth2 and has_oauth1:
            raise ValueError(
                "Cannot provide both OAuth2 (client_id/client_secret) and "
                "OAuth1 (consumer_key/consumer_secret) credentials"
            )

        return self


class AuthProviderAuthentication(BaseModel):
    """Authentication via external provider."""

    provider_readable_id: str = Field(..., description="Auth provider readable ID")
    provider_config: Optional[Dict[str, Any]] = Field(
        None, description="Provider-specific configuration"
    )


# Authentication configuration without explicit type field
AuthenticationConfig = Union[
    DirectAuthentication,
    OAuthTokenAuthentication,
    OAuthBrowserAuthentication,
    AuthProviderAuthentication,
]


# ===========================
# Input Schema - Nested structure


class SourceConnectionCreate(BaseModel):
    """Create source connection with nested authentication."""

    name: Optional[str] = Field(
        None,
        min_length=4,
        max_length=42,
        description="Connection name (defaults to '{Source Name} Connection')",
    )
    short_name: str = Field(..., description="Source identifier (e.g., 'slack', 'github')")
    readable_collection_id: str = Field(..., description="Collection readable ID")
    description: Optional[str] = Field(None, max_length=255, description="Connection description")
    config: Optional[Dict[str, Any]] = Field(None, description="Source-specific configuration")
    schedule: Optional[ScheduleConfig] = None
    sync_immediately: Optional[bool] = Field(
        None,
        description=(
            "Run initial sync after creation. Defaults to True for direct/token/auth_provider, "
            "False for OAuth browser/BYOC flows (which sync after authentication)"
        ),
    )
    authentication: Optional[AuthenticationConfig] = Field(
        None,
        description="Authentication config (defaults to OAuth browser flow for OAuth sources)",
    )
    redirect_url: Optional[str] = Field(
        None,
        description="URL to redirect to after OAuth flow completes (only used for OAuth flows)",
    )

    @model_validator(mode="after")
    def set_sync_immediately_default(self):
        """Set sync_immediately default based on authentication type."""
        if self.sync_immediately is None and self.authentication is not None:
            # OAuth browser or BYOC should NOT sync immediately
            if isinstance(self.authentication, OAuthBrowserAuthentication):
                self.sync_immediately = False
            # Direct, token, or auth provider SHOULD sync immediately
            else:
                # All other auth types default to True
                self.sync_immediately = True
        # If auth is None, service layer handles it (depends on source type)
        return self


class SourceConnectionUpdate(BaseModel):
    """Update schema for source connections."""

    name: Optional[str] = Field(None, min_length=4, max_length=42)
    description: Optional[str] = Field(None, max_length=255)
    config: Optional[Dict[str, Any]] = Field(None, description="Source-specific configuration")
    schedule: Optional[ScheduleConfig] = None

    authentication: Optional[AuthenticationConfig] = Field(
        None,
        description="Authentication config (defaults to OAuth browser flow for OAuth sources)",
    )

    @model_validator(mode="after")
    def validate_minimal_change(self):
        """Ensure at least one field is being updated."""
        # Check which fields were explicitly provided (even if None)
        provided_fields = self.model_fields_set
        if not provided_fields:
            raise ValueError("At least one field must be provided for update")
        return self

    @model_validator(mode="after")
    def validate_direct_auth(self):
        """Ensure only direct auth can be updated with authentication."""
        if self.authentication and not isinstance(self.authentication, DirectAuthentication):
            raise ValueError("Direct auth can only be updated with authentication")
        return self


# ===========================
# Output Schemas
# ===========================


class SyncSummary(BaseModel):
    """Sync summary for list views."""

    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    success_rate: Optional[float] = None


class SourceConnectionListItem(BaseModel):
    """Clean source connection for list views."""

    # Core fields
    id: UUID
    name: str
    short_name: str
    readable_collection_id: str
    created_at: datetime
    modified_at: datetime

    # Authentication
    is_authenticated: bool

    # Stats
    entity_count: int = 0

    # Source configuration
    federated_search: bool = Field(False, description="Whether this source uses federated search")

    # Internal fields for computation (excluded from API response)
    authentication_method: Optional[str] = Field(None, exclude=True)
    is_active: bool = Field(True, exclude=True)
    last_job_status: Optional[str] = Field(None, exclude=True)

    @computed_field  # type: ignore[misc]
    @property
    def auth_method(self) -> AuthenticationMethod:
        """Get authentication method from database value."""
        if self.authentication_method:
            # Map database string to enum
            if self.authentication_method == "oauth_token":
                return AuthenticationMethod.OAUTH_TOKEN
            elif self.authentication_method == "oauth_browser":
                return AuthenticationMethod.OAUTH_BROWSER
            elif self.authentication_method == "oauth_byoc":
                return AuthenticationMethod.OAUTH_BYOC
            elif self.authentication_method == "direct":
                return AuthenticationMethod.DIRECT
            elif self.authentication_method == "auth_provider":
                return AuthenticationMethod.AUTH_PROVIDER

        # Default fallback based on authentication status
        if self.is_authenticated:
            return AuthenticationMethod.DIRECT
        else:
            return AuthenticationMethod.OAUTH_BROWSER

    @computed_field  # type: ignore[misc]
    @property
    def status(self) -> SourceConnectionStatus:
        """Compute connection status from current state."""
        if not self.is_authenticated:
            return SourceConnectionStatus.PENDING_AUTH

        # Check if manually disabled
        if not self.is_active:
            return SourceConnectionStatus.INACTIVE

        # Check last job status if provided
        if self.last_job_status:
            # Handle both string and enum values
            job_status = (
                self.last_job_status
                if isinstance(self.last_job_status, str)
                else self.last_job_status.value
            )
            if job_status in ("running", "cancelling"):
                return SourceConnectionStatus.SYNCING
            elif job_status == "failed":
                return SourceConnectionStatus.ERROR

        return SourceConnectionStatus.ACTIVE


class AuthenticationDetails(BaseModel):
    """Authentication information."""

    method: AuthenticationMethod
    authenticated: bool
    authenticated_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None

    # OAuth-specific
    auth_url: Optional[str] = Field(None, description="For pending OAuth flows")
    auth_url_expires: Optional[datetime] = None
    redirect_url: Optional[str] = None

    # Provider-specific
    provider_readable_id: Optional[str] = None
    provider_id: Optional[str] = None


class ScheduleDetails(BaseModel):
    """Schedule information."""

    cron: Optional[str] = None
    next_run: Optional[datetime] = None
    continuous: bool = False
    cursor_field: Optional[str] = None
    cursor_value: Optional[Any] = None


class SyncJobDetails(BaseModel):
    """Sync job details."""

    id: UUID
    status: SyncJobStatus
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    entities_inserted: int = 0
    entities_updated: int = 0
    entities_deleted: int = 0
    entities_failed: int = 0
    error: Optional[str] = None


class SyncDetails(BaseModel):
    """Sync execution details."""

    total_runs: int = 0
    successful_runs: int = 0
    failed_runs: int = 0
    last_job: Optional[SyncJobDetails] = None


class EntityTypeStats(BaseModel):
    """Statistics for a specific entity type."""

    count: int
    last_updated: Optional[datetime] = None


class EntitySummary(BaseModel):
    """Entity state summary."""

    total_entities: int = 0
    by_type: Dict[str, EntityTypeStats] = Field(default_factory=dict)


class SourceConnectionSimple(BaseModel):
    """Simple source connection details."""

    id: UUID
    name: str
    description: Optional[str]
    short_name: str
    sync_id: Optional[UUID] = None
    readable_collection_id: str
    created_at: datetime
    modified_at: datetime

    # Fields needed for computing status
    is_authenticated: bool = False

    @computed_field  # type: ignore[misc]
    @property
    def status(self) -> SourceConnectionStatus:
        """Compute simple status based on authentication."""
        if not self.is_authenticated:
            return SourceConnectionStatus.PENDING_AUTH
        return SourceConnectionStatus.ACTIVE


class SourceConnection(BaseModel):
    """Complete source connection details."""

    id: UUID
    name: str
    description: Optional[str]
    short_name: str
    readable_collection_id: str
    status: SourceConnectionStatus
    created_at: datetime
    modified_at: datetime

    # Authentication
    auth: AuthenticationDetails

    # Configuration
    config: Optional[Dict[str, Any]] = None
    schedule: Optional[ScheduleDetails] = None

    # Sync information
    sync: Optional[SyncDetails] = None
    sync_id: Optional[UUID] = Field(None, description="ID of the associated sync")

    # Entity information
    entities: Optional[EntitySummary] = None

    # Source configuration
    federated_search: bool = Field(False, description="Whether this source uses federated search")


class SourceConnectionJob(BaseModel):
    """Individual sync job for a source connection."""

    id: UUID
    source_connection_id: UUID
    status: SyncJobStatus
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None

    # Metrics
    entities_inserted: int = 0
    entities_updated: int = 0
    entities_deleted: int = 0
    entities_failed: int = 0

    # Error info
    error: Optional[str] = None
    error_details: Optional[Dict[str, Any]] = None


# ===========================
# Helper Functions (Deprecated - use computed fields in schemas instead)
# ===========================


def determine_auth_method(source_conn: Any) -> AuthenticationMethod:
    """DEPRECATED: Use SourceConnectionListItem computed field instead.

    Determine authentication method from database fields.
    """
    # Auth provider takes precedence
    if hasattr(source_conn, "readable_auth_provider_id") and source_conn.readable_auth_provider_id:
        return AuthenticationMethod.AUTH_PROVIDER

    # Check for pending OAuth
    if (
        hasattr(source_conn, "connection_init_session_id")
        and source_conn.connection_init_session_id
        and not source_conn.is_authenticated
    ):
        return AuthenticationMethod.OAUTH_BROWSER

    # Default to direct if authenticated
    if source_conn.is_authenticated:
        return AuthenticationMethod.DIRECT

    # Default to OAuth browser for unauthenticated
    return AuthenticationMethod.OAUTH_BROWSER


def compute_status(
    source_conn: Any,
    last_job_status: Optional[SyncJobStatus] = None,
) -> SourceConnectionStatus:
    """DEPRECATED: Use SourceConnectionListItem computed field instead.

    Compute connection status from current state.
    """
    if not source_conn.is_authenticated:
        return SourceConnectionStatus.PENDING_AUTH

    # Check if manually disabled
    if hasattr(source_conn, "is_active") and not source_conn.is_active:
        return SourceConnectionStatus.INACTIVE

    # Check last job status if provided
    if last_job_status:
        if last_job_status in (SyncJobStatus.RUNNING, SyncJobStatus.CANCELLING):
            return SourceConnectionStatus.SYNCING
        elif last_job_status == SyncJobStatus.FAILED:
            return SourceConnectionStatus.ERROR

    return SourceConnectionStatus.ACTIVE
