#!/usr/bin/env python3
# File: bandwidth.py
# Author: Hadi Cahyadi <cumulus13@gmail.com>
# Date: 2025-11-26
# Description: Bandwidth Monitor
# License: MIT

import sys
import os
import time
import psutil
import asciichartpy
import shutil
import signal
import argparse
from collections import deque
from make_colors import print as mprint, make_colors    
from make_colors.table import Table
from ctraceback import print_traceback as tprint

import fnmatch
import re

import threading
from prompt_toolkit.application import Application
from prompt_toolkit.layout import Layout, HSplit, Window
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.output.color_depth import ColorDepth

from collections import deque


try:
    from licface import CustomRichHelpFormatter
except:
    CustomRichHelpFormatter = argparse.RawTextHelpFormatter

INTERVAL = 1
HISTORY_POINTS = 120

# term = Terminal()

def list_interfaces():
    """List all interfaces with traffic stats."""
    data = psutil.net_io_counters(pernic=True)
    if not data:
        print("No interfaces detected.")
        return

    mprint("[bold magenta]Available Network Interfaces:[/]\n")

    for iface, stats in data.items():
        mprint(f"[cyan]{iface}[/]", end="")
        print("  ", end="")
        mprint(f"DL: [yellow]{stats.bytes_recv} bytes[/], UL: [green]{stats.bytes_sent} bytes[/]")

def list_interfaces_table():
    """List all interfaces using make_colors Table with rich markup."""

    data = psutil.net_io_counters(pernic=True)
    if not data:
        print("No interfaces detected.")
        return

    # Table dengan title seperti di dokumentasi
    table = Table(title="[bold cyan]Network Interfaces[/]")

    # Tambah kolom seperti contoh pada README
    table.add_column("[bold white]Interface[/]")
    table.add_column("[blue]Download (bytes)[/]")
    table.add_column("[yellow]Upload (bytes)[/]")
    

    # Isi row
    for iface, stats in data.items():
        table.add_row(
            iface,
            str(stats.bytes_recv),
            str(stats.bytes_sent)
        )

    status_colors = ["bold-cyan", "bold-blue", "bold-yellow"]
    table.set_cols_color(status_colors)
    # Jangan print(table), tapi print(table.draw()) sesuai dokumentasi
    print(table.draw())

def select_interface():
    """Pick the interface with the most traffic as default."""
    candidates = psutil.net_io_counters(pernic=True)
    if not candidates:
        raise RuntimeError("No network interfaces detected.")
    return max(
        candidates.items(),
        key=lambda x: (x[1].bytes_recv + x[1].bytes_sent)
    )[0]

def safe_diff(current, previous):
    """Handle counter wrap-around / overflow."""
    if current < previous:
        return current
    return current - previous

def clear_screen():
    print("\033[2J\033[H", end="")

# Drop-in replacement function:
def monitor_bandwidth(interface, chart_height, chart_width):
    history_dl = deque(maxlen=HISTORY_POINTS)
    history_ul = deque(maxlen=HISTORY_POINTS)

    prev = psutil.net_io_counters(pernic=True)[interface]
    running = {"val": True}  # mutable flag for thread

    # Create formatted text control (accepts ANSI)
    control = FormattedTextControl(text=ANSI(""))  # initial empty
    # a small header separator window + the control window
    header_win = Window(height=1, char="-", style="class:line")
    content_win = Window(content=control, wrap_lines=False, always_hide_cursor=True)
    root_container = HSplit([header_win, content_win])

    kb = KeyBindings()

    @kb.add("q")
    @kb.add("c-c")
    def _(event):
        running["val"] = False
        event.app.exit()

    app = Application(
        layout=Layout(root_container),
        full_screen=True,
        key_bindings=kb,
        color_depth=ColorDepth.TRUE_COLOR,  # ensure ANSI/colors on Windows
    )

    def _final_width():
        try:
            w = app.output.get_size().columns
        except Exception:
            w = shutil.get_terminal_size((80, 20)).columns
        return max(10, min((chart_width or (w - 4)), w - 4))

    def poll_loop():
        nonlocal prev
        try:
            while running["val"]:
                time.sleep(INTERVAL)
                counters = psutil.net_io_counters(pernic=True)
                if interface not in counters:
                    # stop and show message
                    running["val"] = False
                    # set a message then invalidate UI so user sees it
                    control.text = ANSI("\x1b[31mInterface removed. Exiting...\x1b[0m")
                    app.invalidate()
                    break
                cur = counters[interface]

                dl = safe_diff(cur.bytes_recv, prev.bytes_recv) / INTERVAL
                ul = safe_diff(cur.bytes_sent, prev.bytes_sent) / INTERVAL
                prev = cur

                history_dl.append(dl)
                history_ul.append(ul)

                width = _final_width()
                try:
                    chart = asciichartpy.plot(
                        [list(history_dl), list(history_ul)],
                        {
                            "height": chart_height, 
                            "width": width,
                            "colors": [asciichartpy.blue, asciichartpy.yellow],
                        },
                    )
                except Exception as e:
                    chart = f"[Chart Error] {e}"

                # Build colored strings using make_colors (which emits ANSI escapes)
                try:
                    from make_colors import make_colors
                    header = make_colors(f"=== Realtime Bandwidth Monitor ({interface}) ===", "bright_cyan")
                    speeds = (
                        make_colors("Download:", "bright_blue") +
                        f" {dl/1024:.2f} KB/s | " +
                        make_colors("Upload:", "bright_yellow") +
                        f" {ul/1024:.2f} KB/s\n\n"
                    )
                    # color the ascii chart lightly (white) — asciichart already draws chars
                    chart_colored = make_colors(chart, "white")

                    combined = header + "\n" + speeds + chart_colored

                except Exception:
                    # fallback if make_colors missing
                    combined = f"=== Realtime Bandwidth Monitor ({interface}) ===\n"
                    combined += f"Download: {dl/1024:.2f} KB/s | Upload: {ul/1024:.2f} KB/s\n\n"
                    combined += chart

                # IMPORTANT: assign ANSI(...) to control.text
                control.text = ANSI(combined)
                app.invalidate()

        except Exception as exc:
            # ensure UI stops on unexpected error
            control.text = ANSI(f"\x1b[31mUnexpected error: {exc}\x1b[0m")
            app.invalidate()
            running["val"] = False

    # run poll thread, then run app (blocking, handles keys)
    thread = threading.Thread(target=poll_loop, daemon=True)
    thread.start()
    app.run()
    # after exit
    print("\nStopped cleanly.")

def monitor_bandwidth_original(interface, chart_height, chart_width):
    history_dl = deque(maxlen=HISTORY_POINTS)
    history_ul = deque(maxlen=HISTORY_POINTS)

    prev = psutil.net_io_counters(pernic=True)[interface]

    running = True

    def stop(sign, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    while running:
        time.sleep(INTERVAL)

        try:
            counters = psutil.net_io_counters(pernic=True)
            if interface not in counters:
                print(f"Interface '{interface}' not found. Exiting.")
                break
            cur = counters[interface]
        except Exception as e:
            print("Error reading counters:", e)
            continue

        dl = safe_diff(cur.bytes_recv, prev.bytes_recv) / INTERVAL
        ul = safe_diff(cur.bytes_sent, prev.bytes_sent) / INTERVAL
        prev = cur

        history_dl.append(dl)
        history_ul.append(ul)

        try:
            clear_screen()
        except:
            pass

        term_width = shutil.get_terminal_size((80, 20)).columns
        final_width = chart_width if chart_width > 0 else term_width - 4

        mprint(f"=== Realtime Bandwidth Monitor ({interface}) ===", 'lw', 'm')
        mprint(f"[bold cyan]Download:[/] [white on blue]{dl/1024:.2f} KB/s[/]", end='')
        print(" | ", end="")
        mprint(f"[bold yellow]Upload:[/] [black on yellow]{ul/1024:.2f} KB/s[/]\n")

        try:
            chart = asciichartpy.plot(
                [list(history_dl), list(history_ul)],
                {
                    "height": chart_height,
                    "width": final_width,
                    "colors": [asciichartpy.blue, asciichartpy.yellow],
                }
            )
            print(chart)
        except Exception as e:
            print("[Chart Error]", e)

    print("\nStopped cleanly.")

def colorize_chart_rich(chart_raw, dl_color="cyan", ul_color="yellow"):
    """
    Mewarnai chart asciichartpy (2-line chart) menggunakan analisis karakter.
    - '*' dari dataset[0] → DL → warna dl_color
    - '*' dari dataset[1] → UL → warna ul_color
    """

    from rich.text import Text

    out = Text(no_wrap=True)

    # Asciichart multi-series menggambar dua garis dengan karakter berbeda:
    # biasanya DL menggunakan "─" & "┤" & "╶" & "╴"
    # UL menggunakan "┄" "┆" dsb
    # Tapi untuk 2 seri, asciichartpy memakai:
    #   Series 1 → "┤"
    #   Series 2 → "┼"
    #
    # Namun: karakter tepat bisa beda per layout.
    # Maka kita gunakan pendekatan berdasarkan ORIGIN:
    # DL = dataset[0] → karakter garis pertama
    # UL = dataset[1] → karakter garis kedua
    #
    # Cara paling aman → bedakan dengan warna ASCII tinggi:
    dl_chars = set("┤│┘┐┬┴─")
    ul_chars = set("┼┘┐┬┴─")

    # NOTE:
    # DL dan UL sering overlap. Maka prioritas:
    #   1) UL (lebih tinggi)
    #   2) DL
    #   3) Normal

    for ch in chart_raw:
        if ch in ul_chars:
            out.append(ch, style=ul_color)
        elif ch in dl_chars:
            out.append(ch, style=dl_color)
        else:
            out.append(ch)

    return out

# def monitor_bandwidth_rich(interface, chart_height, chart_width):
#     from rich.live import Live
#     from rich.console import Console
#     from rich.panel import Panel
#     from rich.text import Text

#     console = Console()

#     history_dl = deque(maxlen=HISTORY_POINTS)
#     history_ul = deque(maxlen=HISTORY_POINTS)

#     prev = psutil.net_io_counters(pernic=True)[interface]
#     running = True

#     def stop(sign, frame):
#         nonlocal running
#         running = False

#     signal.signal(signal.SIGINT, stop)
#     signal.signal(signal.SIGTERM, stop)

#     def _final_width():
#         try:
#             return max(10, min((chart_width or (console.width - 4)), console.width - 4))
#         except Exception:
#             return max(10, chart_width or 76)

#     with Live(refresh_per_second=10, console=console, screen=True) as live:
#         while running:
#             time.sleep(INTERVAL)

#             counters = psutil.net_io_counters(pernic=True)
#             if interface not in counters:
#                 console.print(f"[red]Interface '{interface}' not found. Exiting.[/red]")
#                 break

#             cur = counters[interface]
#             dl = safe_diff(cur.bytes_recv, prev.bytes_recv) / INTERVAL
#             ul = safe_diff(cur.bytes_sent, prev.bytes_sent) / INTERVAL
#             prev = cur

#             history_dl.append(dl)
#             history_ul.append(ul)

#             width = _final_width()

#             # ⛔ NO ANSI COLORS HERE – Rich will break!
#             try:
#                 chart_raw = asciichartpy.plot(
#                     [list(history_dl), list(history_ul)],
#                     {
#                         "height": chart_height,
#                         "width": width,

#                         # ⛔ REMOVE COLORS → needed!
#                         # "colors": [asciichartpy.blue, asciichartpy.yellow],
#                     }
#                 )
#             except Exception as e:
#                 chart_raw = f"[Chart Error] {e}"

#             # Wrap chart as plain text, apply style to entire block
#             chart_text = Text(chart_raw, style="bright_white", no_wrap=True)

#             header = Text.assemble(
#                 ("Realtime Bandwidth Monitor ", "bold magenta"),
#                 (f"({interface})", "bold cyan")
#             )

#             speeds = Text(
#                 f" DL {dl/1024:.2f} KB/s  |  UL {ul/1024:.2f} KB/s",
#                 style="bright_green"
#             )

#             panel = Panel(
#                 chart_text,
#                 title=header,
#                 subtitle=speeds,
#                 border_style="bold blue"
#             )

#             live.update(panel)

#     console.print("\nStopped cleanly.")

def monitor_bandwidth_rich(interface, height=10, width=80, use_panel=False):
    from rich.live import Live
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text

    INTERVAL = 1
    HISTORY = os.get_terminal_size()[0] - 14

    console = Console()
    history_dl = deque(maxlen=HISTORY)
    history_ul = deque(maxlen=HISTORY)

    prev = psutil.net_io_counters(pernic=True)[interface]
    running = True

    def stop(sig, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    with Live(refresh_per_second=20, console=console, screen=True) as live:
        while running:
            time.sleep(INTERVAL)

            if os.get_terminal_size()[0] - 14 != HISTORY:
                history_dl = deque(maxlen=HISTORY)
                history_ul = deque(maxlen=HISTORY)

            cur = psutil.net_io_counters(pernic=True)[interface]
            dl = (cur.bytes_recv - prev.bytes_recv) / INTERVAL
            ul = (cur.bytes_sent - prev.bytes_sent) / INTERVAL
            prev = cur

            history_dl.append(dl)
            history_ul.append(ul)

            # Render DL
            graph_dl = asciichartpy.plot(
                list(history_dl),
                {"height": height, "width": width}
            )
            text_dl = Text(graph_dl, style="cyan")

            # Render UL
            graph_ul = asciichartpy.plot(
                list(history_ul),
                {"height": height, "width": width}
            )
            text_ul = Text(graph_ul, style="yellow")

            if use_panel:
                # Combine consistently WITHOUT inner ANSI
                combined = Text()
                combined.append("DOWNLOAD", style="bold #00FFFF")
                combined.append("\n")
                combined.append(text_dl)
                if not height < 6:
                    combined.append("\n\n")
                    combined.append("UPLOAD", style="bold #FFFF00")
                    combined.append("\n")
                    combined.append(text_ul)

                panel = Panel(
                    combined,
                    title=f"[bold magenta]Realtime Bandwidth Monitor[/bold magenta] ([cyan]{interface}[/cyan]) W: {width} H: {height}",
                    subtitle=f"[bold #00FFFF]DL: {dl/1024:6.2f} KB/s[/] | [bold #FFFF00]UL: {ul/1024:6.2f} KB/s[/]"
                )

                live.update(panel)
            else:
                # Combine consistently WITHOUT inner ANSI
                combined = Text()
                combined.append(f"DOWNLOAD {dl/1024:6.2f} KB/s | W: {width} H: {height}", style="bold #00FFFF")
                combined.append("\n")
                combined.append(text_dl)
                if not height < 6:
                    combined.append("\n\n")
                    combined.append(f"UPLOAD {ul/1024:6.2f} KB/s", style="bold #FFFF00")
                    combined.append("\n")
                    combined.append(text_ul)

                live.update(combined)

    console.print("\nStopped cleanly.")

def render_chart_precise(series, width, height):
    if not series:
        return ""

    # normalize in width
    data = list(series)
    n = len(data)

    if n == 1:
        data = [data[0], data[0]]
        n = 2

    # compress bins → exactly width columns
    if n > width:
        step = n / width if width else 1
        mapped = []
        for i in range(width):
            start = int(i * step)
            end = int((i + 1) * step)
            chunk = data[start:end]
            mapped.append(sum(chunk) / len(chunk))
        data = mapped
    elif n < width:
        # pad if too short
        pad = [data[-1]] * (width - n)
        data = data + pad

    # normalize to height
    if data:
        lo = min(data)
        hi = max(data)
        span = hi - lo or 1
    else:
        span = 1

    # build graph
    rows = [[" " for _ in range(width)] for _ in range(height)]

    for x, val in enumerate(data):
        # invert Y-axis to match asciichart style
        y = int((val - lo) / span * (height - 1))
        y = height - 1 - y
        rows[y][x] = "█"  # full block, stable & pretty

    # convert to string
    return "\n".join("".join(r) for r in rows)

def render_fixed_width(series, height, width, color=None):
    if not series:
        return Text(" " * width)

    widht = int(width)
    height = int(height)

    # ambil window terakhir pas
    print(f"series: {series}")
    data = series[-width:]
    # print(f"series: {data}")

    lo = min(data)
    hi = max(data)
    span = hi - lo if hi != lo else 1

    # scale data to [0, height-1]
    scaled = [int((v - lo) / span * (height - 1)) for v in data]

    # build rows top→bottom
    rows = []
    for row in range(height - 1, -1, -1):
        line = []
        for val in scaled:
            char = "█" if val == row else " "
            line.append(char)
        rows.append("".join(line))

    txt = Text()
    for r in rows:
        txt.append(r + "\n", style=color)
    return txt

# def monitor_bandwidth_rich(interface, height=10, width=80):
#     from rich.live import Live
#     from rich.console import Console
#     from rich.panel import Panel
#     from rich.text import Text

#     INTERVAL = 1
#     HISTORY = 1000   # besar, tapi dipotong manual

#     console = Console()
#     history_dl = deque(maxlen=HISTORY)
#     history_ul = deque(maxlen=HISTORY)

#     def crop(series, width):
#         extra = 5
#         limit = width + extra
#         if len(series) > limit:
#             return list(series)[-limit:]
#         return list(series)

#     prev = psutil.net_io_counters(pernic=True)[interface]
#     running = True

#     def stop(sig, frame):
#         nonlocal running
#         running = False

#     signal.signal(signal.SIGINT, stop)
#     signal.signal(signal.SIGTERM, stop)

#     with Live(refresh_per_second=20, console=console, screen=True) as live:
#         while running:
#             time.sleep(INTERVAL)

#             cur = psutil.net_io_counters(pernic=True)[interface]
#             dl = (cur.bytes_recv - prev.bytes_recv) / INTERVAL
#             ul = (cur.bytes_sent - prev.bytes_sent) / INTERVAL
#             prev = cur

#             history_dl.append(dl)
#             history_ul.append(ul)

#             # crop BEFORE render to avoid asciichart bug
#             dl_data = crop(history_dl, width)
#             ul_data = crop(history_ul, width)

#             graph_dl = asciichartpy.plot(dl_data, {"height": height, "width": width})
#             graph_ul = asciichartpy.plot(ul_data, {"height": height, "width": width})

#             # graph_dl = render_chart_precise(history_dl, width, height)
#             # graph_ul = render_chart_precise(history_ul, width, height)

#             text_dl = Text(graph_dl, style="cyan")
#             text_ul = Text(graph_ul, style="yellow")

#             # text_dl = render_fixed_width(history_dl, height, width, "cyan")
#             # text_ul = render_fixed_width(history_ul, height, width, "yellow")


#             combined = Text()
#             combined.append("DOWNLOAD\n", style="bold cyan")
#             combined.append(text_dl)
#             combined.append("\n\nUPLOAD\n", style="bold yellow")
#             combined.append(text_ul)

#             panel = Panel(
#                 combined,
#                 title=f"[bold magenta]Realtime Bandwidth Monitor[/bold magenta] ([cyan]{interface}[/cyan])",
#                 subtitle=f"[bold cyan]DL: {dl/1024:.2f} KB/s[/] | [bold yellow]UL: {ul/1024:.2f} KB/s[/]"
#             )

#             live.update(panel)

#     console.print("\nStopped cleanly.")

def parse_args():
    parser = argparse.ArgumentParser(
        description="Realtime bandwidth monitor using psutil + asciichartpy",
        prog='bandwidth',
        formatter_class=CustomRichHelpFormatter
    )

    parser.add_argument(
        "-i", "--iface",
        help="Specify network interface (default: auto-select best)",
        type=str,
        default=None
    )

    parser.add_argument(
        "-H", "--height",
        help="Chart height (default: 15)",
        type=int,
        default=15
    )

    parser.add_argument(
        "-W", "--width",
        help="Chart width (default: auto terminal width)",
        type=int,
        default=0
    )

    parser.add_argument(
        "-l", "--list",
        help="List available network interfaces and exit",
        action="store_true"
    )

    parser.add_argument(
        "-t", "--table",
        help="Show output in table mode",
        action="store_true"
    )

    parser.add_argument(
        "-ns", "--no-smooth",
        help="Show without smooth",
        action="store_true"
    )

    parser.add_argument(
        "-r", "--rich",
        help="Rich mode",
        action="store_true"
    )

    parser.add_argument(
        "-p", "--panel",
        help="Panel mode for rich mode",
        action="store_true"
    )

    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(1)

    return parser.parse_args()

def resolve_interface(pattern):
    """Resolve -i pattern with fnmatch + optional regex match."""
    interfaces = list(psutil.net_io_counters(pernic=True).keys())

    # 1) Exact match first
    if pattern in interfaces:
        return pattern

    # 2) Wildcard / glob via fnmatch
    matches = [i for i in interfaces if fnmatch.fnmatch(i, pattern)]
    if matches:
        if len(matches) == 1:
            return matches[0]

        mprint("[yellow]Multiple interfaces matched your pattern:[/]")
        for idx, name in enumerate(matches, 1):
            mprint(f"  [cyan]{idx}[/] → [magenta]{name}[/]")

        choice = input("Choose index: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(matches):
            return matches[int(choice) - 1]
        else:
            mprint("[red]Invalid choice.[/]")
            sys.exit(1)

    # 3) Try regex
    try:
        r = re.compile(pattern)
        regex_matches = [i for i in interfaces if r.search(i)]
        if regex_matches:
            if len(regex_matches) == 1:
                return regex_matches[0]

            mprint("[yellow]Multiple regex matches:[/]")
            for idx, name in enumerate(regex_matches, 1):
                mprint(f"  [cyan]{idx}[/] → [magenta]{name}[/]")

            choice = input("Choose index: ").strip()
            if choice.isdigit() and 1 <= int(choice) <= len(regex_matches):
                return regex_matches[int(choice) - 1]
            else:
                mprint("[red]Invalid choice.[/]")
                sys.exit(1)
    except re.error:
        pass

    # 4) No match → show interface list
    mprint(f"[red]No interface matches pattern:[/] [yellow]{pattern}[/]\n")
    mprint("[bold cyan]Available interfaces:[/]")
    for x in interfaces:
        mprint(f" - [green]{x}[/]")
    sys.exit(1)

if __name__ == "__main__":
    args = parse_args()

    # If user requests list interfaces
    if args.list:
        if args.table:
            list_interfaces_table()    
            exit(0)
        list_interfaces()
        exit(0)

    if args.iface:
        iface = resolve_interface(args.iface)
    else:
        iface = select_interface()


    print("Using interface:", iface)
    if args.no_smooth:
        monitor_bandwidth_original(iface, args.height, args.width)    
    elif args.rich:
        monitor_bandwidth_rich(iface, args.height, args.width, args.panel)    
    else:
        monitor_bandwidth(iface, args.height, args.width)
