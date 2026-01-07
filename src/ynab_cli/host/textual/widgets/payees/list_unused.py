from typing import TYPE_CHECKING, Any, cast

from textual.app import ComposeResult
from textual.widgets import Checkbox, DataTable, Input, Log, ProgressBar
from typing_extensions import override

from ynab_cli.adapters.textual.io import TextualIO
from ynab_cli.domain.use_cases import payees as use_cases
from ynab_cli.host.textual.widgets.common.command_widget import CommandWidget
from ynab_cli.host.textual.widgets.common.dialogs import CANCELLED, DialogForm, SaveCancelDialogScreen

if TYPE_CHECKING:
    from ynab_cli.host.textual.app import YnabCliApp


class ListUnusedParamsDialogForm(DialogForm[use_cases.ListUnusedParams]):
    def __init__(self, params: use_cases.ListUnusedParams, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._params: use_cases.ListUnusedParams = {**params}

    @override
    def compose(self) -> ComposeResult:
        yield Checkbox("Dry Run", self._params.get("dry_run", False), id="dry_run")
        yield Checkbox("Prefix Unused Payees", self._params.get("prefix_unused", False), id="prefix_unused")
        yield Input(
            placeholder="Start from letter or payee name (e.g., 'B' or 'Bo Concept')",
            value=self._params.get("start_from") or "",
            id="start_from",
        )
        yield Checkbox("Auto Resume from saved progress", self._params.get("auto_resume", False), id="auto_resume")
        yield Checkbox("Auto Wait when rate limited", self._params.get("auto_wait", False), id="auto_wait")

    @override
    async def get_result(self) -> use_cases.ListUnusedParams:
        start_from_value = self.query_one("#start_from", Input).value
        return {
            "dry_run": self.query_one("#dry_run", Checkbox).value,
            "prefix_unused": self.query_one("#prefix_unused", Checkbox).value,
            "start_from": start_from_value if start_from_value else None,
            "auto_resume": self.query_one("#auto_resume", Checkbox).value,
            "auto_wait": self.query_one("#auto_wait", Checkbox).value,
        }


class ListUnusedCommand(CommandWidget):
    def __init__(self) -> None:
        super().__init__()
        self._params: use_cases.ListUnusedParams = {
            "dry_run": False,
            "prefix_unused": False,
            "start_from": None,
            "auto_resume": False,
            "auto_wait": False,
        }

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns(
            "Payee Id",
            "Payee Name",
        )

    @override
    async def _get_command_params(self) -> None:
        result = await self.app.push_screen_wait(
            SaveCancelDialogScreen(ListUnusedParamsDialogForm(self._params), title="Payees: List Unused Parameters")
        )
        if result is not CANCELLED:
            self._params = result

    @override
    async def _run_command(self) -> None:
        progress_bar = self.query_one(ProgressBar)
        table = self.query_one(DataTable)
        log = self.query_one(Log)

        async for payee in use_cases.ListUnused(
            TextualIO(self.app, log, progress_bar), cast("YnabCliApp", self.app).client
        )(self.settings, self._params):
            table.add_row(
                payee.id,
                payee.name,
            )
