"""Northstar desktop system and file manager."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import gi
import psutil

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk, Pango

from northstar.system import format_bytes, format_uptime, snapshot


APP_ID = "io.github.northstar.SystemDesk"
DOWNLOAD_SUFFIXES = {".rpm", ".flatpakref", ".flatpak", ".appimage", ".deb", ".run"}


def label(text: str, style: str | None = None) -> Gtk.Label:
    widget = Gtk.Label(label=text, xalign=0)
    if style:
        widget.add_css_class(style)
    return widget


def icon_button(icon_name: str, tooltip: str) -> Gtk.Button:
    button = Gtk.Button.new_from_icon_name(icon_name)
    button.set_tooltip_text(tooltip)
    button.add_css_class("flat")
    return button


class NorthstarWindow(Adw.ApplicationWindow):
    def __init__(self, application: Adw.Application) -> None:
        super().__init__(application=application, title="Northstar")
        self.set_default_size(1240, 820)
        self.set_size_request(860, 620)
        self.set_icon_name("io.github.northstar.SystemDesk")
        self.metrics: dict[str, object] = {}
        self.cpu_history: list[float] = [0.0] * 48
        self.selected_page = "Overview"
        self.current_directory = Path.home()
        self.power_profile_names: list[str] = []
        self.power_profile_last_check = 0.0
        self.updating_power_profile = False
        self._install_css()

        shell = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.toast_overlay = Adw.ToastOverlay()
        self.toast_overlay.set_child(shell)
        self.set_content(self.toast_overlay)
        shell.append(self._build_sidebar())

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        content.add_css_class("main-content")
        shell.append(content)
        content.append(self._build_header())

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(180)
        self.stack.set_hexpand(True)
        self.stack.set_vexpand(True)
        content.append(self.stack)

        self.stack.add_named(self._build_overview(), "Overview")
        self.stack.add_named(self._build_files(), "Files")
        self.stack.add_named(self._build_applications(), "Applications")
        self.stack.add_named(self._build_processes(), "Processes")
        self.show_page("Overview")
        self.refresh_metrics()
        self.refresh_files()
        self.refresh_applications()
        self.refresh_processes()
        GLib.timeout_add_seconds(2, self._tick_metrics)
        GLib.timeout_add_seconds(5, self._tick_processes)

    def _install_css(self) -> None:
        css = b"""
        window { background: #f3f6f4; color: #182724; }
        .sidebar { background: #e9efec; border-right: 1px solid #d9e2dd; min-width: 218px; }
        .brand { padding: 24px 20px 22px; }
        .brand-mark { color: #0b7768; font-size: 21px; font-weight: 800; }
        .brand-subtitle { color: #74827d; font-size: 11px; }
        .nav-group { padding: 8px 12px 4px; color: #83908a; font-size: 10px; font-weight: 700; }
        .nav-button { min-height: 42px; margin: 2px 8px; padding: 0 12px; border-radius: 9px; color: #50605a; }
        .nav-button.active { background: #d5e7df; color: #145d50; font-weight: 700; }
        .nav-button:hover { background: #dce7e2; }
        .main-content { background: #f3f6f4; }
        .topbar { min-height: 74px; padding: 0 28px; border-bottom: 1px solid #e1e8e4; background: #f8faf8; }
        .page-title { font-size: 21px; font-weight: 750; color: #182724; }
        .page-hint { color: #7a8982; font-size: 12px; }
        .content-page { padding: 25px 30px 30px; }
        .section-heading { font-size: 15px; font-weight: 700; color: #23342f; }
        .section-note { color: #83908a; font-size: 11px; }
        .stat-card { background: #ffffff; border: 1px solid #e4ebe7; border-radius: 13px; padding: 17px 18px; }
        .stat-caption { color: #718079; font-size: 12px; font-weight: 600; }
        .stat-value { color: #1c2d28; font-size: 27px; font-weight: 750; }
        .stat-detail { color: #819088; font-size: 11px; }
        .metric-icon { color: #087967; background: #e7f3ed; padding: 8px; border-radius: 9px; }
        .accent-orange { color: #c46a32; background: #fff0e5; }
        .accent-blue { color: #457294; background: #eaf2f8; }
        .accent-lime { color: #6e7e2b; background: #f1f4df; }
        .panel { background: #ffffff; border: 1px solid #e4ebe7; border-radius: 13px; padding: 18px; }
        .row-title { color: #263a33; font-weight: 650; }
        .row-subtitle { color: #7c8b83; font-size: 11px; }
        .file-row { padding: 7px 8px; border-bottom: 1px solid #edf1ee; }
        .file-row:last-child { border-bottom: none; }
        .path-entry { border-radius: 8px; }
        .status-pill { background: #e4f1eb; color: #24705d; border-radius: 99px; padding: 5px 9px; font-size: 10px; font-weight: 700; }
        .empty-state { color: #88958f; padding: 36px 12px; }
        progressbar trough { min-height: 6px; border-radius: 99px; background: #e9efeb; }
        progressbar progress { min-height: 6px; border-radius: 99px; background: #168675; }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_display(
            self.get_display(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def _build_sidebar(self) -> Gtk.Widget:
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        sidebar.add_css_class("sidebar")
        brand = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        brand.add_css_class("brand")
        brand.append(label("NORTHSTAR", "brand-mark"))
        brand.append(label("SYSTEM DESK", "brand-subtitle"))
        sidebar.append(brand)
        sidebar.append(label("WORKSPACE", "nav-group"))
        self.nav_buttons: dict[str, Gtk.Button] = {}
        for title, icon in (
            ("Overview", "view-grid-symbolic"),
            ("Files", "folder-symbolic"),
            ("Applications", "application-x-executable-symbolic"),
            ("Processes", "utilities-system-monitor-symbolic"),
        ):
            button = Gtk.Button()
            button.set_child(self._nav_content(icon, title))
            button.add_css_class("nav-button")
            button.set_halign(Gtk.Align.FILL)
            button.connect("clicked", lambda _button, page=title: self.show_page(page))
            sidebar.append(button)
            self.nav_buttons[title] = button

        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        sidebar.append(spacer)
        self.sidebar_status = label("●  Monitoring active", "section-note")
        self.sidebar_status.set_margin_start(20)
        self.sidebar_status.set_margin_bottom(18)
        sidebar.append(self.sidebar_status)
        return sidebar

    @staticmethod
    def _nav_content(icon: str, title: str) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=11)
        row.append(Gtk.Image.new_from_icon_name(icon))
        row.append(label(title))
        return row

    def _build_header(self) -> Gtk.Widget:
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        bar.add_css_class("topbar")
        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        titles.set_hexpand(True)
        self.title_label = label("Overview", "page-title")
        self.subtitle_label = label("A clear view of your machine", "page-hint")
        titles.append(self.title_label)
        titles.append(self.subtitle_label)
        bar.append(titles)
        self.clock_label = label("")
        self.clock_label.add_css_class("section-note")
        bar.append(self.clock_label)
        refresh = icon_button("view-refresh-symbolic", "Refresh current view")
        refresh.connect("clicked", self._refresh_current)
        bar.append(refresh)
        return bar

    def _page(self, spacing: int = 18) -> Gtk.Box:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
        page.add_css_class("content-page")
        page.set_vexpand(True)
        return page

    @staticmethod
    def _heading(title: str, note: str | None = None) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box.set_hexpand(True)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        text.set_hexpand(True)
        text.append(label(title, "section-heading"))
        if note:
            text.append(label(note, "section-note"))
        box.append(text)
        return box

    def _metric_card(self, title: str, icon_name: str, accent: str) -> tuple[Gtk.Widget, Gtk.Label, Gtk.Label, Gtk.ProgressBar]:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=11)
        card.add_css_class("stat-card")
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        top.set_hexpand(True)
        image = Gtk.Image.new_from_icon_name(icon_name)
        image.add_css_class("metric-icon")
        if accent:
            image.add_css_class(accent)
        top.append(image)
        top.append(label(title, "stat-caption"))
        card.append(top)
        value = label("--", "stat-value")
        detail = label("Collecting readings", "stat-detail")
        progress = Gtk.ProgressBar()
        progress.set_fraction(0)
        card.append(value)
        card.append(detail)
        card.append(progress)
        return card, value, detail, progress

    def _build_overview(self) -> Gtk.Widget:
        page = self._page(19)
        page.append(self._heading("Your system, at a glance", "Live readings from this machine"))
        grid = Gtk.Grid(column_spacing=12, row_spacing=12)
        self.metric_widgets: dict[str, tuple[Gtk.Label, Gtk.Label, Gtk.ProgressBar]] = {}
        definitions = (
            ("cpu", "Processor", "processor-symbolic", "", ""),
            ("memory", "Memory", "memory-symbolic", "accent-blue", ""),
            ("battery", "Battery", "battery-symbolic", "accent-lime", ""),
            ("power", "Power draw", "weather-clear-symbolic", "accent-orange", ""),
        )
        for index, (key, title, icon, accent, _) in enumerate(definitions):
            card, value, detail, progress = self._metric_card(title, icon, accent)
            grid.attach(card, index % 2, index // 2, 1, 1)
            self.metric_widgets[key] = (value, detail, progress)
        page.append(grid)

        lower = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        chart_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=13)
        chart_panel.add_css_class("panel")
        chart_panel.set_hexpand(True)
        chart_panel.set_vexpand(True)
        chart_panel.append(self._heading("Activity", "Processor utilization · last 90 seconds"))
        self.chart = Gtk.DrawingArea()
        self.chart.set_content_height(150)
        self.chart.set_hexpand(True)
        self.chart.set_draw_func(self._draw_chart)
        chart_panel.append(self.chart)
        lower.append(chart_panel)

        details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        details.add_css_class("panel")
        details.set_size_request(265, -1)
        details.append(self._heading("Machine health"))
        self.health_labels: dict[str, Gtk.Label] = {}
        for key, title in (("temperature", "Peak temperature"), ("storage", "Home storage"),
                           ("processes", "Running processes"), ("uptime", "Uptime")):
            line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            line.append(label(title, "stat-detail"))
            value = label("--", "row-title")
            value.set_hexpand(True)
            value.set_xalign(1)
            line.append(value)
            details.append(line)
            self.health_labels[key] = value
        profile_line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        profile_line.append(label("Power profile", "stat-detail"))
        self.power_profile_dropdown = Gtk.DropDown.new(Gtk.StringList.new(["Unavailable"]))
        self.power_profile_dropdown.set_hexpand(True)
        self.power_profile_dropdown.set_sensitive(False)
        self.power_profile_dropdown.set_tooltip_text("Requires the power-profiles-daemon service")
        self.power_profile_dropdown.connect("notify::selected", self._power_profile_selected)
        profile_line.append(self.power_profile_dropdown)
        details.append(profile_line)
        lower.append(details)
        lower.set_vexpand(True)
        page.append(lower)
        return page

    def _draw_chart(self, _area: Gtk.DrawingArea, context: object, width: int, height: int) -> None:
        context.set_line_width(1)
        context.set_source_rgb(0.91, 0.94, 0.92)
        for fraction in (0.25, 0.5, 0.75):
            y = height * fraction
            context.move_to(0, y)
            context.line_to(width, y)
        context.stroke()
        if len(self.cpu_history) < 2:
            return
        context.set_line_width(2.5)
        context.set_source_rgb(0.05, 0.52, 0.43)
        for index, reading in enumerate(self.cpu_history):
            x = width * index / (len(self.cpu_history) - 1)
            y = height - 8 - (height - 16) * reading / 100
            if index == 0:
                context.move_to(x, y)
            else:
                context.line_to(x, y)
        context.stroke()

    def _build_files(self) -> Gtk.Widget:
        page = self._page(14)
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        back = icon_button("go-up-symbolic", "Go to parent folder")
        back.connect("clicked", lambda _button: self.navigate(self.current_directory.parent))
        toolbar.append(back)
        self.path_entry = Gtk.Entry()
        self.path_entry.add_css_class("path-entry")
        self.path_entry.set_hexpand(True)
        self.path_entry.set_placeholder_text("Enter a folder path")
        self.path_entry.connect("activate", self._path_activated)
        toolbar.append(self.path_entry)
        home = icon_button("user-home-symbolic", "Go to home folder")
        home.connect("clicked", lambda _button: self.navigate(Path.home()))
        toolbar.append(home)
        new_folder = icon_button("folder-new-symbolic", "Create a folder")
        new_folder.connect("clicked", self._create_folder)
        toolbar.append(new_folder)
        page.append(toolbar)

        self.files_heading = label("", "section-heading")
        page.append(self.files_heading)
        self.file_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.file_list.add_css_class("boxed-list")
        self.file_list.set_vexpand(True)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(self.file_list)
        page.append(scroller)
        return page

    def _build_applications(self) -> Gtk.Widget:
        page = self._page(16)
        page.append(self._heading("Applications", "Installed apps and application files in Downloads"))
        self.apps_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.apps_list.add_css_class("boxed-list")
        self.apps_list.set_vexpand(True)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(self.apps_list)
        page.append(scroller)
        return page

    def _build_processes(self) -> Gtk.Widget:
        page = self._page(16)
        title_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        title_row.set_hexpand(True)
        title_row.append(self._heading("Processes", "User-owned tasks · stopping a process asks for confirmation"))
        refresh = icon_button("view-refresh-symbolic", "Refresh processes")
        refresh.connect("clicked", lambda _button: self.refresh_processes())
        title_row.append(refresh)
        page.append(title_row)
        self.process_count = label("", "section-note")
        page.append(self.process_count)
        self.process_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.process_list.add_css_class("boxed-list")
        self.process_list.set_vexpand(True)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(self.process_list)
        page.append(scroller)
        return page

    def show_page(self, title: str) -> None:
        self.selected_page = title
        self.stack.set_visible_child_name(title)
        self.title_label.set_text(title)
        subtitles = {
            "Overview": "A clear view of your machine",
            "Files": "Browse and organize files on this device",
            "Applications": "Launch installed apps and downloaded installers",
            "Processes": "Inspect active tasks and stop unresponsive apps",
        }
        self.subtitle_label.set_text(subtitles[title])
        for name, button in self.nav_buttons.items():
            if name == title:
                button.add_css_class("active")
            else:
                button.remove_css_class("active")

    def _refresh_current(self, _button: Gtk.Button) -> None:
        if self.selected_page == "Files":
            self.refresh_files()
        elif self.selected_page == "Applications":
            self.refresh_applications()
        elif self.selected_page == "Processes":
            self.refresh_processes()
        else:
            self.refresh_metrics()

    def refresh_metrics(self) -> None:
        self.metrics = snapshot()
        self._refresh_power_profile()
        cpu = float(self.metrics["cpu"])
        self.cpu_history.append(cpu)
        self.cpu_history = self.cpu_history[-48:]
        self.clock_label.set_text(GLib.DateTime.new_now_local().format("%H:%M:%S"))

        memory_percent = float(self.metrics["memory"])
        battery = self.metrics["battery"]
        power = self.metrics["power"]
        values = {
            "cpu": (f"{cpu:.0f}%", "Processor load right now", cpu),
            "memory": (f"{memory_percent:.0f}%", f"{format_bytes(int(self.metrics['memory_used']))} of {format_bytes(int(self.metrics['memory_total']))}", memory_percent),
            "battery": (f"{battery:.0f}%" if battery is not None else "N/A", "Charging" if self.metrics["charging"] else "On battery or unavailable", float(battery or 0)),
            "power": (str(power or "N/A"), "Live system power telemetry" if power else "Hardware does not expose a power sensor", 0),
        }
        for key, (value, detail, fraction) in values.items():
            main_label, sub_label, progress = self.metric_widgets[key]
            main_label.set_text(value)
            sub_label.set_text(detail)
            progress.set_fraction(max(0, min(1, fraction / 100)))
            progress.set_visible(key != "power")

        temperature = self.metrics["temperature"]
        self.health_labels["temperature"].set_text(f"{temperature:.0f} °C" if temperature else "N/A")
        self.health_labels["storage"].set_text(f"{self.metrics['disk']:.0f}% used")
        self.health_labels["processes"].set_text(str(self.metrics["processes"]))
        self.health_labels["uptime"].set_text(format_uptime(int(self.metrics["uptime"])))
        self.chart.queue_draw()

    def _refresh_power_profile(self) -> None:
        if time.monotonic() - self.power_profile_last_check < 10:
            return
        self.power_profile_last_check = time.monotonic()
        executable = shutil.which("powerprofilesctl")
        if not executable:
            self.power_profile_names = []
            self.updating_power_profile = True
            self.power_profile_dropdown.set_model(Gtk.StringList.new(["Unavailable"]))
            self.power_profile_dropdown.set_selected(0)
            self.power_profile_dropdown.set_sensitive(False)
            self.updating_power_profile = False
            return
        try:
            listing = subprocess.run([executable, "list"], capture_output=True, text=True, check=True, timeout=2)
            current = subprocess.run([executable, "get"], capture_output=True, text=True, check=True, timeout=2).stdout.strip()
            profiles = sorted(set(re.findall(r"^\s*\*?\s*([a-z][a-z0-9-]*):", listing.stdout, re.MULTILINE)))
            if not profiles:
                raise ValueError("No power profiles were reported")
        except (OSError, subprocess.SubprocessError, ValueError):
            self.power_profile_names = []
            self.updating_power_profile = True
            self.power_profile_dropdown.set_model(Gtk.StringList.new(["Unavailable"]))
            self.power_profile_dropdown.set_selected(0)
            self.power_profile_dropdown.set_sensitive(False)
            self.updating_power_profile = False
            return

        self.power_profile_names = profiles
        self.updating_power_profile = True
        self.power_profile_dropdown.set_model(Gtk.StringList.new(profiles))
        self.power_profile_dropdown.set_selected(profiles.index(current) if current in profiles else 0)
        self.power_profile_dropdown.set_tooltip_text("Change the system power profile")
        self.power_profile_dropdown.set_sensitive(True)
        self.updating_power_profile = False

    def _power_profile_selected(self, dropdown: Gtk.DropDown, _parameter: object) -> None:
        if self.updating_power_profile or not self.power_profile_names:
            return
        selected = dropdown.get_selected()
        if selected >= len(self.power_profile_names):
            return
        profile = self.power_profile_names[selected]
        try:
            subprocess.run(["powerprofilesctl", "set", profile], check=True, timeout=3)
            self._toast(f"Power profile set to {profile}")
        except (OSError, subprocess.SubprocessError) as error:
            self._toast(f"Could not change power profile: {error}")
            self.power_profile_last_check = 0
            self._refresh_power_profile()

    def _tick_metrics(self) -> bool:
        self.refresh_metrics()
        return GLib.SOURCE_CONTINUE

    def navigate(self, path: Path) -> None:
        try:
            resolved = path.expanduser().resolve(strict=True)
            if not resolved.is_dir():
                self._toast("That location is not a folder")
                return
            self.current_directory = resolved
            self.refresh_files()
        except OSError as error:
            self._toast(f"Cannot open folder: {error.strerror or error}")

    def _path_activated(self, entry: Gtk.Entry) -> None:
        self.navigate(Path(entry.get_text()))

    def refresh_files(self) -> None:
        while child := self.file_list.get_first_child():
            self.file_list.remove(child)
        self.path_entry.set_text(str(self.current_directory))
        try:
            entries = sorted(self.current_directory.iterdir(), key=lambda item: (not item.is_dir(), item.name.casefold()))
        except OSError as error:
            self.file_list.append(label(f"Could not read this folder: {error.strerror or error}", "empty-state"))
            return
        self.files_heading.set_text(f"{len(entries)} items")
        if not entries:
            self.file_list.append(label("This folder is empty", "empty-state"))
            return
        for path in entries:
            row = Gtk.ListBoxRow()
            row.add_css_class("file-row")
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            image = Gtk.Image.new_from_icon_name("folder-symbolic" if path.is_dir() else "text-x-generic-symbolic")
            box.append(image)
            text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            name = label(path.name, "row-title")
            name.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            text.append(name)
            try:
                metadata = path.stat()
                subtitle = "Folder" if path.is_dir() else format_bytes(metadata.st_size)
            except OSError:
                subtitle = "Unavailable"
            text.append(label(subtitle, "row-subtitle"))
            text.set_hexpand(True)
            box.append(text)
            open_button = icon_button("document-open-symbolic", "Open")
            open_button.connect("clicked", lambda _button, item=path: self._open_path(item))
            box.append(open_button)
            trash_button = icon_button("user-trash-symbolic", "Move to Trash")
            trash_button.connect("clicked", lambda _button, item=path: self._confirm_trash(item))
            box.append(trash_button)
            row.set_child(box)
            if path.is_dir():
                row.set_activatable(True)
                row.connect("activate", lambda _row, item=path: self.navigate(item))
            self.file_list.append(row)

    def _open_path(self, path: Path) -> None:
        if path.is_dir():
            self.navigate(path)
            return
        try:
            Gio.AppInfo.launch_default_for_uri(path.as_uri(), None)
        except GLib.Error as error:
            self._toast(f"Could not open file: {error.message}")

    def _create_folder(self, _button: Gtk.Button) -> None:
        candidate = self.current_directory / "New Folder"
        suffix = 2
        while candidate.exists():
            candidate = self.current_directory / f"New Folder {suffix}"
            suffix += 1
        try:
            candidate.mkdir()
            self.refresh_files()
            self._toast(f"Created {candidate.name}")
        except OSError as error:
            self._toast(f"Could not create folder: {error.strerror or error}")

    def _confirm_trash(self, path: Path) -> None:
        dialog = Adw.MessageDialog.new(self, "Move to Trash?", f"{path.name} can be restored from Trash.")
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("trash", "Move to Trash")
        dialog.set_response_appearance("trash", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._trash_response, path)
        dialog.present()

    def _trash_response(self, dialog: Adw.MessageDialog, response: str, path: Path) -> None:
        dialog.close()
        if response != "trash":
            return
        try:
            Gio.File.new_for_path(str(path)).trash(None)
            self.refresh_files()
            self._toast("Moved to Trash")
        except GLib.Error as error:
            self._toast(f"Could not move to Trash: {error.message}")

    def refresh_applications(self) -> None:
        while child := self.apps_list.get_first_child():
            self.apps_list.remove(child)
        installed = []
        for app in Gio.AppInfo.get_all():
            if app.should_show() and app.get_name():
                installed.append(app)
        installed.sort(key=lambda app: app.get_name().casefold())
        self.apps_list.append(label(f"INSTALLED  ·  {len(installed)}", "nav-group"))
        for app in installed:
            self._append_app_row(app.get_name(), app.get_icon(), app.get_description() or "Installed application", lambda _button, item=app: self._launch_desktop_app(item))

        downloads = Path.home() / "Downloads"
        packages = []
        if downloads.is_dir():
            try:
                packages = sorted((p for p in downloads.iterdir() if p.is_file() and p.suffix.lower() in DOWNLOAD_SUFFIXES), key=lambda p: p.name.casefold())
            except OSError:
                pass
        self.apps_list.append(label(f"DOWNLOADS  ·  {len(packages)}", "nav-group"))
        for path in packages:
            detail = f"{path.suffix[1:].upper()} · {format_bytes(path.stat().st_size)}"
            if path.suffix.lower() == ".appimage":
                action = "Launch" if os.access(path, os.X_OK) else "Open"
                callback = lambda _button, item=path: self._launch_download(item)
            else:
                action = "Open"
                callback = lambda _button, item=path: self._open_path(item)
            self._append_app_row(path.name, Gio.ThemedIcon.new("application-x-executable-symbolic"), detail, callback, action)

    def _append_app_row(self, name: str, icon: Gio.Icon | None, detail: str, callback: object, action: str = "Launch") -> None:
        row = Gtk.ListBoxRow()
        row.add_css_class("file-row")
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        image = Gtk.Image.new_from_gicon(icon) if icon else Gtk.Image.new_from_icon_name("application-x-executable-symbolic")
        box.append(image)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title = label(name, "row-title")
        title.set_ellipsize(Pango.EllipsizeMode.END)
        text.append(title)
        subtitle = label(detail, "row-subtitle")
        subtitle.set_ellipsize(Pango.EllipsizeMode.END)
        text.append(subtitle)
        text.set_hexpand(True)
        box.append(text)
        button = Gtk.Button(label=action)
        button.add_css_class("suggested-action")
        button.connect("clicked", callback)
        box.append(button)
        row.set_child(box)
        self.apps_list.append(row)

    def _launch_desktop_app(self, app: Gio.AppInfo) -> None:
        try:
            app.launch([], None)
            self._toast(f"Launched {app.get_name()}")
        except GLib.Error as error:
            self._toast(f"Could not launch application: {error.message}")

    def _launch_download(self, path: Path) -> None:
        try:
            if path.suffix.lower() == ".appimage" and os.access(path, os.X_OK):
                subprocess.Popen([str(path)], start_new_session=True)
            else:
                Gio.AppInfo.launch_default_for_uri(path.as_uri(), None)
        except (OSError, GLib.Error) as error:
            self._toast(f"Could not open download: {error}")

    def refresh_processes(self) -> None:
        while child := self.process_list.get_first_child():
            self.process_list.remove(child)
        processes = []
        for process in psutil.process_iter(("pid", "name", "username", "memory_info", "cpu_percent")):
            try:
                if process.info["username"] == os.environ.get("USER"):
                    processes.append(process.info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        processes.sort(key=lambda process: (process.get("memory_info").rss if process.get("memory_info") else 0), reverse=True)
        self.process_count.set_text(f"{len(processes)} processes owned by {os.environ.get('USER', 'current user')} · sorted by memory")
        for process in processes[:100]:
            info = process.get("memory_info")
            row = Gtk.ListBoxRow()
            row.add_css_class("file-row")
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            box.append(Gtk.Image.new_from_icon_name("system-run-symbolic"))
            text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            text.append(label(process.get("name") or "Unknown process", "row-title"))
            memory = format_bytes(info.rss) if info else "Memory unavailable"
            text.append(label(f"PID {process['pid']} · {memory}", "row-subtitle"))
            text.set_hexpand(True)
            box.append(text)
            stop = icon_button("media-playback-stop-symbolic", "Stop process")
            stop.connect("clicked", lambda _button, pid=process["pid"], name=process.get("name"): self._confirm_stop(pid, name or "process"))
            box.append(stop)
            row.set_child(box)
            self.process_list.append(row)
        if not processes:
            self.process_list.append(label("No user processes found", "empty-state"))

    def _tick_processes(self) -> bool:
        if self.selected_page == "Processes":
            self.refresh_processes()
        return GLib.SOURCE_CONTINUE

    def _confirm_stop(self, pid: int, name: str) -> None:
        dialog = Adw.MessageDialog.new(self, f"Stop {name}?", f"The process (PID {pid}) will receive a normal termination signal. Unsaved work may be lost.")
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("stop", "Stop process")
        dialog.set_response_appearance("stop", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._stop_response, pid)
        dialog.present()

    def _stop_response(self, dialog: Adw.MessageDialog, response: str, pid: int) -> None:
        dialog.close()
        if response != "stop":
            return
        try:
            psutil.Process(pid).terminate()
            self._toast(f"Sent stop signal to PID {pid}")
            GLib.timeout_add(500, self._refresh_processes_later)
        except (psutil.NoSuchProcess, psutil.AccessDenied) as error:
            self._toast(f"Could not stop process: {error}")

    def _refresh_processes_later(self) -> bool:
        self.refresh_processes()
        return GLib.SOURCE_REMOVE

    def _toast(self, message: str) -> None:
        toast = Adw.Toast.new(message)
        self.toast_overlay.add_toast(toast)


class NorthstarApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.connect("activate", self._activate)

    def _activate(self, application: Adw.Application) -> None:
        window = application.get_active_window()
        if window is None:
            window = NorthstarWindow(application)
        window.present()


def main() -> int:
    Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
    return NorthstarApplication().run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())