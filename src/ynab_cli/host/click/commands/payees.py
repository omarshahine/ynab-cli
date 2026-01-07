import anyio
import click
from lagom import Container

from ynab_cli.domain.settings import Settings
from ynab_cli.domain.use_cases import payees as use_cases
from ynab_cli.host.click.commands.rich.progress_table import ProgressTable
from ynab_cli.host.click.container import containerize
from ynab_cli.host.constants import CONTEXT_KEY_SETTINGS, ENV_PREFIX


class NormalizeNamesCommand:
    def __init__(self, use_case: use_cases.NormalizeNames, progress_table: ProgressTable) -> None:
        self._use_case = use_case
        self._progress_table = progress_table

        self._progress_table.table.title = "Normalized Payees"
        self._progress_table.table.add_column("Payee Id")
        self._progress_table.table.add_column("Payee Name")
        self._progress_table.table.add_column("Normalized Name")

    async def __call__(self, settings: Settings, dry_run: bool) -> None:
        params: use_cases.NormalizeNamesParams = {
            "dry_run": dry_run,
        }

        console = None
        with self._progress_table:
            console = self._progress_table.console

            async for payee, normalized_name in self._use_case(settings, params):
                self._progress_table.table.add_row(
                    str(payee.id),
                    payee.name,
                    normalized_name,
                )

        if console:
            console.print(self._progress_table.table)


class ListDuplicatesCommand:
    def __init__(self, use_case: use_cases.ListDuplicates, progress_table: ProgressTable) -> None:
        self._use_case = use_case
        self._progress_table = progress_table

        self._progress_table.table.title = "Duplicate Payees"
        self._progress_table.table.add_column("Payee Id")
        self._progress_table.table.add_column("Payee Name")
        self._progress_table.table.add_column("Duplicate Payee Id")
        self._progress_table.table.add_column("Duplicate Payee Name")

    async def __call__(self, settings: Settings) -> None:
        params: use_cases.ListDuplicatesParams = {}

        console = None
        with self._progress_table:
            console = self._progress_table.console

            async for payee, duplicate_payee in self._use_case(settings, params):
                self._progress_table.table.add_row(
                    str(payee.id),
                    payee.name,
                    str(duplicate_payee.id),
                    duplicate_payee.name,
                )

        if console:
            console.print(self._progress_table.table)


class ListUnusedCommand:
    def __init__(self, use_case: use_cases.ListUnused, progress_table: ProgressTable) -> None:
        self._use_case = use_case
        self._progress_table = progress_table

        self._progress_table.table.title = "Unused Payees"
        self._progress_table.table.add_column("Payee Id")
        self._progress_table.table.add_column("Payee Name")

    async def __call__(
        self,
        settings: Settings,
        dry_run: bool,
        prefix_unused: bool,
        start_from: str | None,
        auto_resume: bool,
        auto_wait: bool,
    ) -> None:
        params: use_cases.ListUnusedParams = {
            "dry_run": dry_run,
            "prefix_unused": prefix_unused,
            "start_from": start_from,
            "auto_resume": auto_resume,
            "auto_wait": auto_wait,
        }

        console = None
        with self._progress_table:
            console = self._progress_table.console

            async for payee in self._use_case(settings, params):
                self._progress_table.table.add_row(
                    str(payee.id),
                    payee.name,
                )

        if console:
            console.print(self._progress_table.table)


class ListAllCommand:
    def __init__(self, use_case: use_cases.ListAll, progress_table: ProgressTable) -> None:
        self._use_case = use_case
        self._progress_table = progress_table

        self._progress_table.table.title = "All Payees"
        self._progress_table.table.add_column("Payee Id")
        self._progress_table.table.add_column("Payee Name")

    async def __call__(self, settings: Settings) -> None:
        params: use_cases.ListAllParams = {}

        console = None
        with self._progress_table:
            console = self._progress_table.console

            async for payee in self._use_case(settings, params):
                self._progress_table.table.add_row(
                    str(payee.id),
                    payee.name,
                )

        if console:
            console.print(self._progress_table.table)


@containerize
async def _normalize_names(container: Container, dry_run: bool) -> None:
    await container[NormalizeNamesCommand](container[Settings], dry_run)


@click.command()
@click.option("--dry-run", is_flag=True, default=False, help="Run without making any changes.")
@click.pass_context
def normalize_names(ctx: click.Context, dry_run: bool) -> None:
    """Normalize payee names in the YNAB budget."""

    ctx.ensure_object(dict)
    settings: Settings = ctx.obj.get(CONTEXT_KEY_SETTINGS, Settings())
    ctx.obj[CONTEXT_KEY_SETTINGS] = settings

    anyio.run(
        _normalize_names,
        settings,
        dry_run,
        backend_options={"use_uvloop": True},
    )


@containerize
async def _list_duplicates(container: Container) -> None:
    await container[ListDuplicatesCommand](container[Settings])


@click.command()
@click.pass_context
def list_duplicates(ctx: click.Context) -> None:
    """List duplicate payees in the YNAB budget."""

    ctx.ensure_object(dict)
    settings: Settings = ctx.obj.get(CONTEXT_KEY_SETTINGS, Settings())
    ctx.obj[CONTEXT_KEY_SETTINGS] = settings

    anyio.run(
        _list_duplicates,
        settings,
        backend_options={"use_uvloop": True},
    )


@containerize
async def _list_unused(
    container: Container, dry_run: bool, prefix_unused: bool, start_from: str | None, auto_resume: bool, auto_wait: bool
) -> None:
    await container[ListUnusedCommand](container[Settings], dry_run, prefix_unused, start_from, auto_resume, auto_wait)


@click.command()
@click.option("--dry-run", is_flag=True, default=False, help="Run without making any changes.")
@click.option("--prefix-unused", is_flag=True, default=False, help="Add a prefix to the unused payee names.")
@click.option(
    "--start-from",
    default=None,
    help="Start from a letter (e.g., 'B') or payee name (e.g., 'Bo Concept'). Useful for resuming after rate limiting.",
)
@click.option(
    "--auto-resume",
    is_flag=True,
    default=False,
    help="Automatically resume from the last saved progress.",
)
@click.option(
    "--auto-wait",
    is_flag=True,
    default=False,
    help="Automatically wait when rate limited instead of stopping. Can take up to an hour.",
)
@click.pass_context
def list_unused(
    ctx: click.Context, dry_run: bool, prefix_unused: bool, start_from: str | None, auto_resume: bool, auto_wait: bool
) -> None:
    """List unused payees in the YNAB budget.

    This command checks each payee for transactions to identify unused ones.
    Due to YNAB's rate limit of 200 requests/hour, this can be a long-running operation.

    Use --start-from to begin from a specific letter or payee name, which is useful
    for resuming after being rate limited.

    Use --auto-resume to automatically continue from where you left off after
    a previous run was interrupted by rate limiting.

    Use --auto-wait to have the CLI automatically pause when rate limited and
    continue when the limit resets (can take up to an hour).
    """

    ctx.ensure_object(dict)
    settings: Settings = ctx.obj.get(CONTEXT_KEY_SETTINGS, Settings())
    ctx.obj[CONTEXT_KEY_SETTINGS] = settings

    anyio.run(
        _list_unused,
        settings,
        dry_run,
        prefix_unused,
        start_from,
        auto_resume,
        auto_wait,
        backend_options={"use_uvloop": True},
    )


@containerize
async def _list_all(container: Container) -> None:
    await container[ListAllCommand](container[Settings])


@click.command()
@click.pass_context
def list_all(ctx: click.Context) -> None:
    """List all payees in the YNAB budget."""

    ctx.ensure_object(dict)
    settings: Settings = ctx.obj.get(CONTEXT_KEY_SETTINGS, Settings())
    ctx.obj[CONTEXT_KEY_SETTINGS] = settings

    anyio.run(
        _list_all,
        settings,
        backend_options={"use_uvloop": True},
    )


@click.group()
@click.option("--budget-id", prompt=True, envvar=f"{ENV_PREFIX}_BUDGET_ID", show_envvar=True, help="YNAB budget ID.")
@click.pass_context
def payees(ctx: click.Context, budget_id: str) -> None:
    """Manage payees in the YNAB budget."""

    ctx.ensure_object(dict)
    settings: Settings = ctx.obj.get(CONTEXT_KEY_SETTINGS, Settings())
    settings.ynab.budget_id = budget_id
    ctx.obj[CONTEXT_KEY_SETTINGS] = settings


payees.add_command(list_all)
payees.add_command(list_duplicates)
payees.add_command(list_unused)
payees.add_command(normalize_names)
