"""macOS Keychain utilities for loading secrets."""

import subprocess
import os


def get_keychain_secret(name: str) -> str | None:
    """
    Get a secret from macOS Keychain.

    Args:
        name: The secret name (will be prefixed with "env/")

    Returns:
        The secret value, or None if not found
    """
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-a", os.environ.get("USER", ""),
             "-s", f"env/{name}", "-w"],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None


def load_ynab_cli_credentials() -> None:
    """
    Load YNAB CLI credentials from Keychain into environment variables.
    Falls back to existing env vars if Keychain lookup fails.
    """
    credentials = [
        ("YNAB_CLI_ACCESS_TOKEN", "YNAB_CLI_ACCESS_TOKEN"),
        ("YNAB_CLI_BUDGET_ID", "YNAB_CLI_BUDGET_ID"),
    ]

    for env_var, keychain_key in credentials:
        # Only load from Keychain if env var is not already set
        if not os.environ.get(env_var):
            value = get_keychain_secret(keychain_key)
            if value:
                os.environ[env_var] = value
