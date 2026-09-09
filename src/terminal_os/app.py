"""Terminal OS — a small settings TUI."""

from __future__ import annotations

import asyncio

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    OptionList,
    Static,
    TabbedContent,
    TabPane,
)
from textual.widgets.option_list import Option

from terminal_os.backends import battery, bluetooth, power, session, temperature, vpn, wifi

TAB_ORDER = ("overview", "power", "wifi", "vpn", "bluetooth")


def _btn(label: str, **kwargs) -> Button:
    """Mouse-friendly button that is skipped in the focus chain."""
    button = Button(label, **kwargs)
    button.can_focus = False
    return button


class VimDataTable(DataTable):
    """DataTable with jk / gG / ctrl+d/u navigation (h/l switch tabs at app level)."""

    BINDINGS = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("g", "scroll_top", "Top", show=False),
        Binding("G", "scroll_bottom", "Bottom", show=False),
        Binding("ctrl+d", "page_down", "Page down", show=False),
        Binding("ctrl+u", "page_up", "Page up", show=False),
    ]


class VimOptionList(OptionList):
    """OptionList with jk / gG navigation."""

    BINDINGS = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("g", "first", "Top", show=False),
        Binding("G", "last", "Bottom", show=False),
        Binding("ctrl+d", "page_down", "Page down", show=False),
        Binding("ctrl+u", "page_up", "Page up", show=False),
    ]


class PasswordModal(ModalScreen[str | None]):
    """Ask for a Wi-Fi password."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+[", "cancel", "Cancel", show=False),
    ]

    def __init__(self, ssid: str, *, hint: str = "") -> None:
        super().__init__()
        self.ssid = ssid
        self.hint = hint

    def compose(self) -> ComposeResult:
        with Vertical(id="password-dialog"):
            yield Label(f"Password for {self.ssid}")
            if self.hint:
                yield Static(self.hint)
            yield Input(password=True, placeholder="Wi-Fi password", id="wifi-password")
            with Horizontal(id="password-actions"):
                yield Button("Connect", variant="primary", id="pw-connect")
                yield Button("Cancel", id="pw-cancel")

    def on_mount(self) -> None:
        self.query_one("#wifi-password", Input).focus()

    @on(Button.Pressed, "#pw-connect")
    @on(Input.Submitted, "#wifi-password")
    def submit(self) -> None:
        value = self.query_one("#wifi-password", Input).value
        self.dismiss(value)

    @on(Button.Pressed, "#pw-cancel")
    def cancel_btn(self) -> None:
        self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ConfirmModal(ModalScreen[bool]):
    """Confirm a destructive power action."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+[", "cancel", "Cancel", show=False),
        Binding("n", "cancel", "No", show=False),
        Binding("y", "confirm", "Yes", show=False),
    ]

    def __init__(self, title: str, detail: str) -> None:
        super().__init__()
        self.title_text = title
        self.detail = detail

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Label(self.title_text)
            yield Static(self.detail, id="confirm-detail")
            yield Static("y confirm | n/esc cancel")
            with Horizontal(id="confirm-actions"):
                yield Button("Confirm", variant="error", id="confirm-yes")
                yield Button("Cancel", id="confirm-no")

    @on(Button.Pressed, "#confirm-yes")
    def yes(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#confirm-no")
    def no(self) -> None:
        self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_confirm(self) -> None:
        self.dismiss(True)


class ImportVpnModal(ModalScreen[str | None]):
    """Ask for a VPN config path (.ovpn or WireGuard .conf)."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+[", "cancel", "Cancel", show=False),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="import-vpn-dialog"):
            yield Label("Import VPN config")
            yield Static("OpenVPN (.ovpn) or WireGuard (.conf) — same as GNOME Settings")
            yield Input(placeholder="/path/to/config.ovpn", id="vpn-import-path")
            with Horizontal(id="import-vpn-actions"):
                yield Button("Import", variant="primary", id="vpn-import-ok")
                yield Button("Cancel", id="vpn-import-cancel")

    def on_mount(self) -> None:
        self.query_one("#vpn-import-path", Input).focus()

    @on(Button.Pressed, "#vpn-import-ok")
    @on(Input.Submitted, "#vpn-import-path")
    def submit(self) -> None:
        value = self.query_one("#vpn-import-path", Input).value.strip()
        self.dismiss(value or None)

    @on(Button.Pressed, "#vpn-import-cancel")
    def cancel_btn(self) -> None:
        self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class OverviewPane(VerticalScroll):
    def compose(self) -> ComposeResult:
        yield Static("Overview", classes="pane-title")
        yield Static(id="overview-body", classes="status-block")
        yield Label("Power profile  (j/k, enter)", classes="section-label")
        yield VimOptionList(id="overview-profiles")
        yield Static("1-5 or h/l switch tabs | q quit | r refresh", id="overview-keys")

    def refresh_status(self) -> None:
        bat = battery.get_battery()
        pow_ = power.get_power_status()
        wifi_s = wifi.get_wifi_status()
        vpn_s = vpn.get_vpn_status()
        bt = bluetooth.get_bluetooth_status()
        temp = temperature.get_temperature()

        lines = [
            f"Battery     {bat.summary}",
            f"Power mode  {pow_.active or pow_.error or 'n/a'}",
            f"CPU temp    {temp.summary}",
            f"Wi-Fi       "
            + (
                f"{'on' if wifi_s.radio_on else 'off'}"
                + (f" | {wifi_s.connected_ssid}" if wifi_s.connected_ssid else "")
                if wifi_s.available
                else wifi_s.error
            ),
            f"VPN         {vpn_s.summary}",
            f"Bluetooth   "
            + (
                f"{'on' if bt.powered else 'off'}"
                + (f" | {bt.adapter_name}" if bt.adapter_name else "")
                if bt.available
                else bt.error
            ),
        ]
        if bat.available and bat.charge_threshold_supported:
            lines.insert(1, f"Charging    {bat.charging_mode_label}")
        if bat.available:
            extras = []
            if bat.time_to_empty:
                extras.append(f"empty in {bat.time_to_empty}")
            if bat.time_to_full:
                extras.append(f"full in {bat.time_to_full}")
            if bat.energy_rate_w is not None:
                extras.append(f"{bat.energy_rate_w:.1f} W")
            if extras:
                lines.append(" | ".join(extras))

        self.query_one("#overview-body", Static).update("\n".join(lines))

        options = self.query_one("#overview-profiles", VimOptionList)
        options.clear_options()
        if pow_.available:
            for name in pow_.profiles:
                marker = " *" if name == pow_.active else ""
                options.add_option(Option(f"{name}{marker}", id=name))


class PowerPane(VerticalScroll):
    def compose(self) -> ComposeResult:
        yield Static("Power & battery", classes="pane-title")
        yield Static(id="power-status", classes="status-block")
        yield Label("Actions  (j/k, enter)", classes="section-label")
        yield VimOptionList(id="power-menu")
        yield Static(id="power-hint")

    def refresh_status(self) -> None:
        bat = battery.get_battery()
        pow_ = power.get_power_status()

        if bat.available:
            bat_lines = [
                f"Battery  {bat.percentage}% | {bat.state}",
                f"Model    {bat.model or '-'}",
                f"Tech     {bat.technology or '-'}",
            ]
            if bat.energy_wh is not None and bat.energy_full_wh is not None:
                bat_lines.append(
                    f"Energy   {bat.energy_wh:.1f} / {bat.energy_full_wh:.1f} Wh"
                )
            if bat.energy_rate_w is not None:
                bat_lines.append(f"Rate     {bat.energy_rate_w:.2f} W")
            if bat.time_to_empty:
                bat_lines.append(f"Left     {bat.time_to_empty}")
            if bat.time_to_full:
                bat_lines.append(f"Full     {bat.time_to_full}")
            if bat.charge_threshold_supported:
                bat_lines.append(f"Charge   {bat.charging_mode_label}")
        else:
            bat_lines = [f"Battery  {bat.error}"]

        pow_line = (
            f"Profile  {pow_.active}"
            if pow_.available
            else f"Profile  {pow_.error}"
        )
        self.query_one("#power-status", Static).update(
            "\n".join([*bat_lines, "", pow_line])
        )

        menu = self.query_one("#power-menu", VimOptionList)
        highlighted = menu.highlighted
        menu.clear_options()

        if bat.available and bat.charge_threshold_supported:
            menu.add_option(Option("-- battery charging --", disabled=True))
            maximize_mark = " *" if not bat.charge_threshold_enabled else ""
            preserve_mark = " *" if bat.charge_threshold_enabled else ""
            menu.add_option(Option(f"Maximize charge{maximize_mark}", id="charge:maximize"))
            menu.add_option(
                Option(f"Preserve battery health{preserve_mark}", id="charge:preserve")
            )
            start = bat.charge_start_threshold
            end = bat.charge_end_threshold
            if start is not None and end is not None:
                hint = f"Preserve health: {start}%-{end}% | 1-5/h/l tabs | q quit"
            else:
                hint = "Preserve health limits charge | 1-5/h/l tabs | q quit"
        else:
            hint = "Charge limit unavailable | 1-5/h/l tabs | q quit"
        self.query_one("#power-hint", Static).update(hint)

        if pow_.available:
            menu.add_option(Option("-- power profile --", disabled=True))
            for name in pow_.profiles:
                marker = " *" if name == pow_.active else ""
                menu.add_option(Option(f"{name}{marker}", id=f"profile:{name}"))

        menu.add_option(Option("-- session --", disabled=True))
        menu.add_option(Option("Sleep", id="session:suspend"))
        menu.add_option(Option("Hibernate", id="session:hibernate"))
        menu.add_option(Option("Lock", id="session:lock"))
        menu.add_option(Option("Reboot", id="session:reboot"))
        menu.add_option(Option("Shut down", id="session:poweroff"))

        if highlighted is not None and highlighted < menu.option_count:
            menu.highlighted = highlighted


class WifiPane(VerticalScroll):
    def compose(self) -> ComposeResult:
        yield Static("Wi-Fi", classes="pane-title")
        yield Static(id="wifi-status", classes="status-block")
        yield Static(
            "j/k move | enter/c connect | s scan | d disconnect | t radio | h/l tabs",
            id="wifi-hint",
        )
        yield VimDataTable(id="wifi-table", cursor_type="row")
        with Horizontal(classes="button-row"):
            yield _btn("Toggle radio", id="wifi-toggle")
            yield _btn("Scan", id="wifi-scan", variant="primary")
            yield _btn("Disconnect", id="wifi-disconnect")
            yield _btn("Connect", id="wifi-connect", variant="success")

    def on_mount(self) -> None:
        table = self.query_one("#wifi-table", VimDataTable)
        table.add_columns("SSID", "Signal", "Security", "Status")

    def refresh_status(self) -> None:
        status = wifi.get_wifi_status()
        if not status.available:
            text = status.error
        else:
            radio = "on" if status.radio_on else "off"
            conn = status.connected_ssid or "not connected"
            text = f"Radio {radio} | {conn}"
            if status.device:
                text += f"  ({status.device})"
        self.query_one("#wifi-status", Static).update(text)

    def fill_networks(self, networks: list[wifi.WifiNetwork]) -> None:
        table = self.query_one("#wifi-table", VimDataTable)
        table.clear()
        saved = wifi.list_saved_wifi_ssids()
        for net in networks:
            status = []
            if net.in_use:
                status.append("connected")
            if net.ssid in saved:
                status.append("saved")
            table.add_row(
                net.ssid,
                f"{net.signal}%",
                net.security or "Open",
                ", ".join(status),
                key=net.ssid,
            )


class VpnPane(VerticalScroll):
    def compose(self) -> ComposeResult:
        yield Static("VPN", classes="pane-title")
        yield Static(id="vpn-status", classes="status-block")
        yield Static(
            "j/k move | enter/c connect | d disconnect | i import | r refresh | h/l tabs",
            id="vpn-hint",
        )
        yield VimDataTable(id="vpn-table", cursor_type="row")
        with Horizontal(classes="button-row"):
            yield _btn("Refresh", id="vpn-refresh", variant="primary")
            yield _btn("Import", id="vpn-import")
            yield _btn("Connect", id="vpn-connect", variant="success")
            yield _btn("Disconnect", id="vpn-disconnect")

    def on_mount(self) -> None:
        table = self.query_one("#vpn-table", VimDataTable)
        table.add_columns("Name", "Type", "Status")

    def refresh_status(self) -> None:
        status = vpn.get_vpn_status()
        if not status.available:
            text = status.error
        elif status.active_names:
            text = f"Connected | {', '.join(status.active_names)}"
        else:
            text = "Not connected"
        self.query_one("#vpn-status", Static).update(text)

    def fill_connections(self, connections: list[vpn.VpnConnection]) -> None:
        table = self.query_one("#vpn-table", VimDataTable)
        table.clear()
        for conn in connections:
            table.add_row(
                conn.name,
                conn.type_label,
                "connected" if conn.active else "-",
                key=conn.name,
            )


class BluetoothPane(VerticalScroll):
    def compose(self) -> ComposeResult:
        yield Static("Bluetooth", classes="pane-title")
        yield Static(id="bt-status", classes="status-block")
        yield Static(
            "j/k move | enter/c connect | s scan | d disconnect | t power | p pair | v discoverable",
            id="bt-hint",
        )
        yield VimDataTable(id="bt-table", cursor_type="row")
        with Horizontal(classes="button-row"):
            yield _btn("Toggle power", id="bt-toggle")
            yield _btn("Scan", id="bt-scan", variant="primary")
            yield _btn("Discoverable", id="bt-discoverable")
            yield _btn("Connect", id="bt-connect", variant="success")
            yield _btn("Disconnect", id="bt-disconnect")
            yield _btn("Pair + connect", id="bt-pair")

    def on_mount(self) -> None:
        table = self.query_one("#bt-table", VimDataTable)
        table.add_columns("Name", "Address", "Status")

    def refresh_status(self) -> None:
        status = bluetooth.get_bluetooth_status()
        if not status.available:
            text = status.error
        else:
            power_s = "on" if status.powered else "off"
            flags = []
            if status.discoverable:
                flags.append("discoverable")
            if status.pairable:
                flags.append("pairable")
            extra = f" | {', '.join(flags)}" if flags else ""
            name = status.adapter_name or "adapter"
            text = f"{name} | power {power_s}{extra}"
        self.query_one("#bt-status", Static).update(text)

    def fill_devices(self, devices: list[bluetooth.BtDevice]) -> None:
        table = self.query_one("#bt-table", VimDataTable)
        table.clear()
        for dev in devices:
            bits = []
            if dev.connected:
                bits.append("connected")
            if dev.paired:
                bits.append("paired")
            table.add_row(
                dev.name,
                dev.address,
                ", ".join(bits) or "-",
                key=dev.address,
            )


class TerminalOS(App[None]):
    """Settings-style TUI for common laptop controls."""

    TITLE = "Terminal OS"
    SUB_TITLE = "tty settings"
    # Plain console look — Linux VTs handle custom hex / box-drawing poorly.
    CSS = """
    TabPane {
        padding: 0 1;
    }

    .pane-title {
        text-style: bold;
        margin-bottom: 0;
    }

    PasswordModal, ConfirmModal, ImportVpnModal {
        align: center middle;
    }

    .section-label {
        margin-top: 1;
        margin-bottom: 0;
        text-style: bold;
    }

    .status-block {
        height: auto;
        margin-bottom: 1;
    }

    .button-row {
        height: auto;
        margin-bottom: 1;
    }

    .button-row Button {
        margin-right: 1;
    }

    DataTable {
        height: 1fr;
        min-height: 8;
        border: ascii;
    }

    OptionList {
        height: auto;
        max-height: 20;
        border: ascii;
    }

    #password-dialog, #confirm-dialog, #import-vpn-dialog {
        width: 60;
        height: auto;
        padding: 1 1;
        border: ascii;
        margin: 2 4;
    }

    #password-actions, #confirm-actions, #import-vpn-actions {
        height: auto;
        margin-top: 1;
    }

    #password-actions Button, #confirm-actions Button, #import-vpn-actions Button {
        margin-right: 1;
    }

    #confirm-detail {
        margin-top: 1;
    }

    #wifi-hint, #bt-hint, #vpn-hint, #power-hint, #overview-keys {
        height: auto;
        margin-bottom: 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("h", "prev_tab", "Tab-"),
        Binding("l", "next_tab", "Tab+"),
        Binding("H", "prev_tab", "Tab-", show=False),
        Binding("L", "next_tab", "Tab+", show=False),
        Binding("1", "show_tab('overview')", "Overview", show=False),
        Binding("2", "show_tab('power')", "Power", show=False),
        Binding("3", "show_tab('wifi')", "Wi-Fi", show=False),
        Binding("4", "show_tab('vpn')", "VPN", show=False),
        Binding("5", "show_tab('bluetooth')", "Bluetooth", show=False),
        Binding("s", "ctx_scan", "Scan", show=False),
        Binding("c", "ctx_connect", "Connect", show=False),
        Binding("d", "ctx_disconnect", "Disconnect", show=False),
        Binding("t", "ctx_toggle", "Toggle", show=False),
        Binding("i", "ctx_import", "Import", show=False),
        Binding("p", "ctx_pair", "Pair", show=False),
        Binding("v", "ctx_discoverable", "Discoverable", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with TabbedContent(id="main-tabs"):
            with TabPane("Overview", id="overview"):
                yield OverviewPane(id="overview-pane")
            with TabPane("Power", id="power"):
                yield PowerPane(id="power-pane")
            with TabPane("Wi-Fi", id="wifi"):
                yield WifiPane(id="wifi-pane")
            with TabPane("VPN", id="vpn"):
                yield VpnPane(id="vpn-pane")
            with TabPane("Bluetooth", id="bluetooth"):
                yield BluetoothPane(id="bluetooth-pane")
        yield Footer()

    def on_mount(self) -> None:
        self.action_refresh()
        # Cached lists only — no Wi-Fi/Bluetooth RF scans on startup.
        self.load_wifi(rescan=False)
        self.load_vpn()
        self.load_bluetooth()
        # Lightweight status poll; never triggers RF scans.
        self.set_interval(60, self.action_refresh)
        self.call_after_refresh(self._focus_tab_content)

    def action_show_tab(self, tab_id: str) -> None:
        tabs = self.query_one("#main-tabs", TabbedContent)
        tabs.active = tab_id
        self.call_after_refresh(self._focus_tab_content)

    def action_next_tab(self) -> None:
        tabs = self.query_one("#main-tabs", TabbedContent)
        try:
            idx = TAB_ORDER.index(str(tabs.active))
        except ValueError:
            idx = 0
        tabs.active = TAB_ORDER[(idx + 1) % len(TAB_ORDER)]
        self.call_after_refresh(self._focus_tab_content)

    def action_prev_tab(self) -> None:
        tabs = self.query_one("#main-tabs", TabbedContent)
        try:
            idx = TAB_ORDER.index(str(tabs.active))
        except ValueError:
            idx = 0
        tabs.active = TAB_ORDER[(idx - 1) % len(TAB_ORDER)]
        self.call_after_refresh(self._focus_tab_content)

    def _active_tab(self) -> str:
        return str(self.query_one("#main-tabs", TabbedContent).active)

    def _focus_tab_content(self) -> None:
        """Land focus on the main interactive widget for the active tab."""
        active = self._active_tab()
        try:
            if active == "wifi":
                self.query_one("#wifi-table", VimDataTable).focus()
            elif active == "vpn":
                self.query_one("#vpn-table", VimDataTable).focus()
            elif active == "bluetooth":
                self.query_one("#bt-table", VimDataTable).focus()
            elif active == "power":
                self.query_one("#power-menu", VimOptionList).focus()
            elif active == "overview":
                self.query_one("#overview-profiles", VimOptionList).focus()
        except Exception:
            pass

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        # Let the password field receive letters/numbers instead of app shortcuts.
        if isinstance(self.focused, Input) and action in {
            "next_tab",
            "prev_tab",
            "quit",
            "refresh",
            "show_tab",
            "ctx_scan",
            "ctx_connect",
            "ctx_disconnect",
            "ctx_toggle",
            "ctx_import",
            "ctx_pair",
            "ctx_discoverable",
        }:
            return False
        if action.startswith("ctx_"):
            if len(self.screen_stack) > 1:
                return False
            tab = self._active_tab()
            if action in {"ctx_scan", "ctx_toggle"}:
                return tab in {"wifi", "bluetooth"}
            if action in {"ctx_connect", "ctx_disconnect"}:
                return tab in {"wifi", "vpn", "bluetooth"}
            if action == "ctx_import":
                return tab == "vpn"
            if action in {"ctx_pair", "ctx_discoverable"}:
                return tab == "bluetooth"
        return True

    def action_refresh(self) -> None:
        """Refresh status text only (battery, radios, connection) - no RF scans."""
        self.query_one("#overview-pane", OverviewPane).refresh_status()
        self.query_one("#power-pane", PowerPane).refresh_status()
        self.query_one("#wifi-pane", WifiPane).refresh_status()
        self.query_one("#vpn-pane", VpnPane).refresh_status()
        self.query_one("#bluetooth-pane", BluetoothPane).refresh_status()
        # VPN has no RF scan — reloading the profile list on `r` is cheap and useful.
        if self._active_tab() == "vpn":
            self.load_vpn()

    def notify_result(self, ok: bool, message: str) -> None:
        self.notify(message, severity="information" if ok else "error")

    def _refresh_after_change(self) -> None:
        """Status + cached network/device lists, still without RF scanning."""
        self.action_refresh()
        self.load_wifi(rescan=False)
        self.load_vpn()
        self.load_bluetooth()

    def action_ctx_scan(self) -> None:
        if self._active_tab() == "wifi":
            self.wifi_scan()
        elif self._active_tab() == "bluetooth":
            self.bt_scan()

    def action_ctx_connect(self) -> None:
        if self._active_tab() == "wifi":
            self.wifi_connect()
        elif self._active_tab() == "vpn":
            self.vpn_connect()
        elif self._active_tab() == "bluetooth":
            self.bt_connect()

    def action_ctx_disconnect(self) -> None:
        if self._active_tab() == "wifi":
            self.wifi_disconnect()
        elif self._active_tab() == "vpn":
            self.vpn_disconnect()
        elif self._active_tab() == "bluetooth":
            self.bt_disconnect()

    def action_ctx_toggle(self) -> None:
        if self._active_tab() == "wifi":
            self.wifi_toggle()
        elif self._active_tab() == "bluetooth":
            self.bt_toggle()

    def action_ctx_import(self) -> None:
        if self._active_tab() == "vpn":
            self.vpn_import()

    def action_ctx_pair(self) -> None:
        if self._active_tab() == "bluetooth":
            self.bt_pair()

    def action_ctx_discoverable(self) -> None:
        if self._active_tab() == "bluetooth":
            self.bt_discoverable()

    # --- Overview / power menu ---

    @on(OptionList.OptionSelected, "#overview-profiles")
    def overview_profile_selected(self, event: OptionList.OptionSelected) -> None:
        option_id = event.option_id
        if option_id:
            self._set_profile(str(option_id))

    def _set_profile(self, name: str) -> None:
        result = power.set_power_profile(name)
        self.notify_result(result.ok, result.text or f"Set profile: {name}")
        self.action_refresh()

    @on(OptionList.OptionSelected, "#power-menu")
    def power_menu_selected(self, event: OptionList.OptionSelected) -> None:
        option_id = event.option_id
        if not option_id:
            return
        key = str(option_id)
        if key.startswith("charge:"):
            preserve = key.endswith("preserve")
            result = battery.set_charge_threshold_enabled(preserve)
            label = "Preserve battery health" if preserve else "Maximize charge"
            self.notify_result(result.ok, result.text or f"Battery charging: {label}")
            self.action_refresh()
        elif key.startswith("profile:"):
            self._set_profile(key.split(":", 1)[1])
        elif key == "session:suspend":
            self.act_suspend()
        elif key == "session:hibernate":
            self.act_hibernate()
        elif key == "session:lock":
            self.act_lock()
        elif key == "session:reboot":
            self.act_reboot()
        elif key == "session:poweroff":
            self.act_poweroff()

    # --- Session actions ---

    def act_suspend(self) -> None:
        self._confirm_power("Sleep", "Suspend this computer now?", session.suspend)

    def act_hibernate(self) -> None:
        self._confirm_power(
            "Hibernate",
            "Hibernate this computer now? (needs swap / resume support)",
            session.hibernate,
        )

    def act_lock(self) -> None:
        result = session.lock_session()
        self.notify_result(result.ok, result.text or "Lock requested")

    def act_reboot(self) -> None:
        self._confirm_power("Reboot", "Reboot this computer now?", session.reboot)

    def act_poweroff(self) -> None:
        self._confirm_power("Shut down", "Power off this computer now?", session.poweroff)

    def _confirm_power(self, title: str, detail: str, action) -> None:
        def done(confirmed: bool | None) -> None:
            if not confirmed:
                return
            result = action()
            self.notify_result(result.ok, result.text or title)

        self.push_screen(ConfirmModal(title, detail), done)

    # --- Wi-Fi ---

    @work(exclusive=True, group="wifi")
    async def load_wifi(self, *, rescan: bool = False) -> None:
        networks, error = await asyncio.to_thread(wifi.list_wifi, rescan=rescan)
        pane = self.query_one("#wifi-pane", WifiPane)
        pane.refresh_status()
        if error and not networks:
            self.notify(error, severity="warning")
        pane.fill_networks(networks)

    @on(Button.Pressed, "#wifi-scan")
    def wifi_scan(self) -> None:
        self.notify("Scanning Wi-Fi...")
        self.load_wifi(rescan=True)

    @on(Button.Pressed, "#wifi-toggle")
    def wifi_toggle(self) -> None:
        status = wifi.get_wifi_status()
        result = wifi.set_wifi_radio(not status.radio_on)
        self.notify_result(result.ok, result.text or "Wi-Fi radio toggled")
        self._refresh_after_change()

    @on(Button.Pressed, "#wifi-disconnect")
    def wifi_disconnect(self) -> None:
        result = wifi.disconnect_wifi()
        self.notify_result(result.ok, result.text or "Disconnected")
        self._refresh_after_change()

    @on(DataTable.RowSelected, "#wifi-table")
    @on(Button.Pressed, "#wifi-connect")
    def wifi_connect(self, _event: object = None) -> None:
        table = self.query_one("#wifi-table", VimDataTable)
        if table.row_count == 0:
            self.notify("No networks listed - press s to scan", severity="warning")
            return
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        ssid = str(row_key.value)
        row = table.get_row(row_key)
        security = str(row[2]) if len(row) > 2 else ""
        is_open = security.strip().upper() in {"", "--", "-", "OPEN"}
        is_saved = wifi.find_saved_wifi(ssid) is not None

        # Saved profiles already have secrets — just activate them.
        if is_saved or is_open:
            self._do_wifi_connect(ssid, None)
            return

        def after_pw(password: str | None) -> None:
            if password is None:
                return
            if not password:
                self.notify("Password required for new networks", severity="warning")
                return
            self._do_wifi_connect(ssid, password)

        self.push_screen(
            PasswordModal(ssid, hint="New network - enter Wi-Fi password"),
            after_pw,
        )

    @work(exclusive=True, group="wifi-connect")
    async def _do_wifi_connect(self, ssid: str, password: str | None) -> None:
        self.notify(f"Connecting to {ssid}...")
        result = await asyncio.to_thread(wifi.connect_wifi, ssid, password)
        self.notify_result(result.ok, result.text or f"Connected to {ssid}")
        self._refresh_after_change()

    # --- VPN ---

    @work(exclusive=True, group="vpn")
    async def load_vpn(self) -> None:
        connections, error = await asyncio.to_thread(vpn.list_vpn)
        pane = self.query_one("#vpn-pane", VpnPane)
        pane.refresh_status()
        if error and not connections:
            self.notify(error, severity="warning")
        pane.fill_connections(connections)

    @on(Button.Pressed, "#vpn-refresh")
    def vpn_refresh(self) -> None:
        self.load_vpn()

    def _selected_vpn_name(self) -> str | None:
        table = self.query_one("#vpn-table", VimDataTable)
        if table.row_count == 0:
            return None
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        return str(row_key.value)

    @on(DataTable.RowSelected, "#vpn-table")
    @on(Button.Pressed, "#vpn-connect")
    def vpn_connect(self, _event: object = None) -> None:
        name = self._selected_vpn_name()
        if not name:
            self.notify("No VPN profiles — press i to import", severity="warning")
            return
        self._do_vpn_connect(name)

    @on(Button.Pressed, "#vpn-disconnect")
    def vpn_disconnect(self) -> None:
        name = self._selected_vpn_name()
        if name:
            self._do_vpn_disconnect(name)
            return
        status = vpn.get_vpn_status()
        if status.active_names:
            self._do_vpn_disconnect(status.active_names[0])
            return
        self.notify("No VPN connected", severity="warning")

    @on(Button.Pressed, "#vpn-import")
    def vpn_import(self) -> None:
        def after_path(path: str | None) -> None:
            if not path:
                return
            self._do_vpn_import(path)

        self.push_screen(ImportVpnModal(), after_path)

    @work(exclusive=True, group="vpn-connect")
    async def _do_vpn_connect(self, name: str) -> None:
        self.notify(f"Connecting {name}...")
        result = await asyncio.to_thread(vpn.connect_vpn, name)
        self.notify_result(result.ok, result.text or f"Connected {name}")
        self._refresh_after_change()

    @work(exclusive=True, group="vpn-disconnect")
    async def _do_vpn_disconnect(self, name: str) -> None:
        self.notify(f"Disconnecting {name}...")
        result = await asyncio.to_thread(vpn.disconnect_vpn, name)
        self.notify_result(result.ok, result.text or f"Disconnected {name}")
        self._refresh_after_change()

    @work(exclusive=True, group="vpn-import")
    async def _do_vpn_import(self, path: str) -> None:
        self.notify(f"Importing {path}...")
        result = await asyncio.to_thread(vpn.import_vpn, path)
        self.notify_result(result.ok, result.text or f"Imported {path}")
        self._refresh_after_change()

    # --- Bluetooth ---

    @work(exclusive=True, group="bt")
    async def load_bluetooth(self) -> None:
        devices, error = await asyncio.to_thread(bluetooth.list_devices)
        pane = self.query_one("#bluetooth-pane", BluetoothPane)
        pane.refresh_status()
        if error:
            self.notify(error, severity="warning")
        pane.fill_devices(devices)

    @on(Button.Pressed, "#bt-toggle")
    def bt_toggle(self) -> None:
        status = bluetooth.get_bluetooth_status()
        result = bluetooth.set_bluetooth_powered(not status.powered)
        self.notify_result(result.ok, result.text or "Bluetooth toggled")
        self._refresh_after_change()

    @on(Button.Pressed, "#bt-discoverable")
    def bt_discoverable(self) -> None:
        status = bluetooth.get_bluetooth_status()
        result = bluetooth.set_discoverable(not status.discoverable)
        self.notify_result(result.ok, result.text or "Discoverable toggled")
        self.query_one("#bluetooth-pane", BluetoothPane).refresh_status()

    @on(Button.Pressed, "#bt-scan")
    def bt_scan(self) -> None:
        self.notify("Scanning Bluetooth (~8s)...")
        self._bt_scan_work()

    @work(exclusive=True, group="bt-scan")
    async def _bt_scan_work(self) -> None:
        await asyncio.to_thread(bluetooth.scan_devices, 8.0)
        devices, _ = await asyncio.to_thread(bluetooth.list_devices)
        self.query_one("#bluetooth-pane", BluetoothPane).fill_devices(devices)
        self.query_one("#bluetooth-pane", BluetoothPane).refresh_status()
        self.notify("Bluetooth scan finished")

    def _selected_bt_address(self) -> str | None:
        table = self.query_one("#bt-table", VimDataTable)
        if table.row_count == 0:
            return None
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        return str(row_key.value)

    @on(DataTable.RowSelected, "#bt-table")
    @on(Button.Pressed, "#bt-connect")
    def bt_connect(self, _event: object = None) -> None:
        address = self._selected_bt_address()
        if not address:
            self.notify("Select a device", severity="warning")
            return
        self._bt_action("connect", address)

    @on(Button.Pressed, "#bt-disconnect")
    def bt_disconnect(self) -> None:
        address = self._selected_bt_address()
        if not address:
            self.notify("Select a device", severity="warning")
            return
        self._bt_action("disconnect", address)

    @on(Button.Pressed, "#bt-pair")
    def bt_pair(self) -> None:
        address = self._selected_bt_address()
        if not address:
            self.notify("Select a device", severity="warning")
            return
        self._bt_action("pair", address)

    @work(exclusive=True, group="bt-action")
    async def _bt_action(self, kind: str, address: str) -> None:
        if kind == "connect":
            result = await asyncio.to_thread(bluetooth.connect_device, address)
        elif kind == "disconnect":
            result = await asyncio.to_thread(bluetooth.disconnect_device, address)
        else:
            result = await asyncio.to_thread(bluetooth.trust_and_pair, address)
        self.notify_result(result.ok, result.text or f"{kind} {address}")
        self.load_bluetooth()


def run() -> None:
    TerminalOS().run()
