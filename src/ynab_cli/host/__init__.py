import os

from dotenv import load_dotenv
from ynab_cli.host.keychain import load_ynab_cli_credentials

cwd = os.getcwd()
dot_env_path = os.path.join(cwd, ".env")


def setup_env() -> None:
    # First try to load from macOS Keychain
    load_ynab_cli_credentials()

    # Fall back to .env file for any missing vars
    if os.path.exists(dot_env_path):
        load_dotenv(dot_env_path)


setup_env()
