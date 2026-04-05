"""Custom exceptions for L.I.R.A."""


class LiraError(Exception):
    """Base exception for all L.I.R.A. errors."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class DatabaseError(LiraError):
    """Database-related errors."""


class ModelError(LiraError):
    """Data model validation errors."""


class AgentError(LiraError):
    """Agent execution errors."""


class ToolError(LiraError):
    """Tool execution errors."""


class MCPError(LiraError):
    """MCP server errors."""


class ValidationError(LiraError):
    """Input validation errors."""


class ConfigurationError(LiraError):
    """Configuration errors."""


class AuthenticationError(LiraError):
    """Authentication errors."""


class PermissionError(LiraError):
    """Permission/authorization errors."""


class NotFoundError(LiraError):
    """Resource not found errors."""
