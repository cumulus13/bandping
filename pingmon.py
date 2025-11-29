#!/usr/bin/env python3
# File: ping_monitor.py
# Author: Hadi Cahyadi <cumulus13@gmail.com>
# Date: 2025-11-26
# Description: Real-time Ping Monitor with TTL & Latency
# License: MIT

import sys
import os
import time
import asciichartpy
import shutil
import signal
import argparse
from collections import deque
from make_colors import print as mprint, make_colors
from statistics import mean, stdev

CTRACEBACK_AVAILABLE = False
try:
    from ctraceback import print_traceback as tprint
    CTRACEBACK_AVAILABLE = True
except:
    tprint = traceback.print_exc

import threading
from prompt_toolkit.application import Application
from prompt_toolkit.layout import Layout, HSplit, Window
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.output.color_depth import ColorDepth

try:
    from pythonping import ping
    PING_AVAILABLE = True
except ImportError:
    PING_AVAILABLE = False
    print("⚠️  `pythonping` not installed. Install with: pip install pythonping")

try:
    from licface import CustomRichHelpFormatter
except:
    CustomRichHelpFormatter = argparse.RawTextHelpFormatter

INTERVAL = 1  # ping interval in seconds
HISTORY_POINTS = os.get_terminal_size()[0] - 14

def clear_screen():
    print("\033[2J\033[H", end="")

def do_ping(host, timeout=2):
    """
    Perform single ping and return (latency_ms, ttl, success)
    Returns (0, 0, False) on failure
    """
    try:
        response = ping(host, count=1, timeout=timeout, verbose=False)
        if response.success():
            # pythonping returns response in seconds, convert to ms
            latency_ms = response.rtt_avg_ms
            # TTL might not always be available, default to 0
            ttl = getattr(response, 'ttl', 0)
            return (latency_ms, ttl, True)
    except Exception as e:
        pass
    return (0, 0, False)

def monitor_ping_basic(host, chart_height, chart_width):
    """Basic monitoring with screen refresh"""
    history_latency = deque(maxlen=HISTORY_POINTS)
    history_ttl = deque(maxlen=HISTORY_POINTS)
    
    stats = {
        'sent': 0,
        'received': 0,
        'lost': 0,
        'min': float('inf'),
        'max': 0,
        'avg': 0
    }
    
    running = True

    def stop(sign, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    latencies = []  # for calculating statistics

    while running:
        latency, ttl, success = do_ping(host)
        stats['sent'] += 1
        
        if success:
            stats['received'] += 1
            stats['min'] = min(stats['min'], latency)
            stats['max'] = max(stats['max'], latency)
            latencies.append(latency)
            stats['avg'] = mean(latencies) if latencies else 0
            
            history_latency.append(latency)
            history_ttl.append(ttl if ttl > 0 else 64)  # default TTL
        else:
            stats['lost'] += 1
            # Add timeout value for visualization
            history_latency.append(0)
            history_ttl.append(0)

        try:
            clear_screen()
        except:
            pass

        term_width = shutil.get_terminal_size((80, 20)).columns
        final_width = chart_width if chart_width > 0 else term_width - 4

        # Header
        mprint(f"=== Real-time Ping Monitor: {host} ===", 'lw', 'm')
        
        # Current stats
        packet_loss = (stats['lost'] / stats['sent'] * 100) if stats['sent'] > 0 else 0
        
        mprint(f"[bold cyan]Latency:[/] [white on blue]{latency:.2f} ms[/]", end='')
        print(" | ", end="")
        mprint(f"[bold green]TTL:[/] [black on green]{ttl}[/]", end='')
        print(" | ", end="")
        
        if success:
            mprint(f"[bold green]Status:[/] [white on green]CONNECTED[/]")
        else:
            mprint(f"[bold red]Status:[/] [white on red]TIMEOUT[/]")
        
        # Statistics
        print()
        mprint(f"[bold yellow]Statistics:[/]")
        mprint(f"  Sent: [cyan]{stats['sent']}[/] | Received: [green]{stats['received']}[/] | Lost: [red]{stats['lost']}[/] ({packet_loss:.1f}%)")
        
        if stats['received'] > 0:
            std = stdev(latencies) if len(latencies) > 1 else 0
            mprint(f"  Min: [green]{stats['min']:.2f}ms[/] | Avg: [yellow]{stats['avg']:.2f}ms[/] | Max: [red]{stats['max']:.2f}ms[/] | StdDev: [cyan]{std:.2f}ms[/]")
        
        print()

        # Chart - Latency
        try:
            if len(history_latency) > 1:
                chart = asciichartpy.plot(
                    [list(history_latency)],
                    {
                        "height": chart_height,
                        "width": final_width,
                        "colors": [asciichartpy.yellow],
                    }
                )
                mprint("[bold cyan]Latency History (ms):[/]")
                print(chart)
        except Exception as e:
            print("[Chart Error]", e)

        time.sleep(INTERVAL)

    print("\n✓ Stopped cleanly.")
    print(f"\nFinal Statistics:")
    print(f"  Packets: Sent = {stats['sent']}, Received = {stats['received']}, Lost = {stats['lost']} ({packet_loss:.1f}%)")
    if stats['received'] > 0:
        print(f"  Latency: Min = {stats['min']:.2f}ms, Avg = {stats['avg']:.2f}ms, Max = {stats['max']:.2f}ms")

def monitor_ping_advanced(host, chart_height, chart_width):
    """Advanced monitoring with prompt_toolkit"""
    history_latency = deque(maxlen=HISTORY_POINTS)
    
    stats = {
        'sent': 0,
        'received': 0,
        'lost': 0,
        'min': float('inf'),
        'max': 0,
        'latencies': []
    }
    
    running = {"val": True}

    control = FormattedTextControl(text=ANSI(""))
    header_win = Window(height=1, char="─", style="class:line")
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
        color_depth=ColorDepth.TRUE_COLOR,
    )

    def _final_width():
        try:
            w = app.output.get_size().columns
        except Exception:
            w = shutil.get_terminal_size((80, 20)).columns
        return max(10, min((chart_width or (w - 4)), w - 4))

    def poll_loop():
        while running["val"]:
            latency, ttl, success = do_ping(host)
            stats['sent'] += 1
            
            if success:
                stats['received'] += 1
                stats['min'] = min(stats['min'], latency)
                stats['max'] = max(stats['max'], latency)
                stats['latencies'].append(latency)
                history_latency.append(latency)
            else:
                stats['lost'] += 1
                history_latency.append(0)

            width = _final_width()
            
            # Build display
            try:
                avg = mean(stats['latencies']) if stats['latencies'] else 0
                packet_loss = (stats['lost'] / stats['sent'] * 100) if stats['sent'] > 0 else 0
                std = stdev(stats['latencies']) if len(stats['latencies']) > 1 else 0
                
                header = make_colors(f"=== Real-time Ping Monitor: {host} ===", "bright_cyan")
                
                status_color = "bright_green" if success else "bright_red"
                status_text = "CONNECTED" if success else "TIMEOUT"
                
                current = (
                    make_colors("Latency:", "bright_cyan") + f" {latency:.2f} ms | " +
                    make_colors("TTL:", "bright_green") + f" {ttl} | " +
                    make_colors("Status:", status_color) + f" {status_text}\n\n"
                )
                
                # Statistics
                stat_info = make_colors("Statistics:", "bright_yellow") + "\n"
                stat_info += f"  Sent: {stats['sent']} | Received: {stats['received']} | Lost: {stats['lost']} ({packet_loss:.1f}%)\n"
                
                if stats['received'] > 0:
                    stat_info += f"  Min: {stats['min']:.2f}ms | Avg: {avg:.2f}ms | Max: {stats['max']:.2f}ms | StdDev: {std:.2f}ms\n\n"
                else:
                    stat_info += "\n"
                
                # Chart
                try:
                    if len(history_latency) > 1:
                        chart = asciichartpy.plot(
                            [list(history_latency)],
                            {
                                "height": chart_height,
                                "width": width,
                                "colors": [asciichartpy.green],
                            }
                        )
                        chart_colored = make_colors(chart, "green")
                    else:
                        chart_colored = "Collecting data..."
                except Exception as e:
                    chart_colored = f"[Chart Error] {e}"
                    if str(os.getenv('TRACEBACK', '0')).lower() in ['1', 'yes', 'ok', 'true']:
                        if CTRACEBACK_AVAILABLE:
                            tprint(*sys.exc_info(), None, False, True)
                        else:
                            print(f"\n❌ Error: {e}")
                            traceback.print_exc()
                
                combined = header + "\n" + current + stat_info + chart_colored
                
            except Exception as exc:
                combined = f"Error: {exc}"
            
            control.text = ANSI(combined)
            app.invalidate()
            
            time.sleep(INTERVAL)

    thread = threading.Thread(target=poll_loop, daemon=True)
    thread.start()
    app.run()
    
    print("\n✓ Stopped cleanly.")
    packet_loss = (stats['lost'] / stats['sent'] * 100) if stats['sent'] > 0 else 0
    print(f"\nFinal Statistics:")
    print(f"  Packets: Sent = {stats['sent']}, Received = {stats['received']}, Lost = {stats['lost']} ({packet_loss:.1f}%)")
    if stats['received'] > 0:
        avg = mean(stats['latencies'])
        print(f"  Latency: Min = {stats['min']:.2f}ms, Avg = {avg:.2f}ms, Max = {stats['max']:.2f}ms")

def monitor_ping_rich(host, height=10, width=80, use_panel=False):
    """Rich-based monitoring"""
    from rich.live import Live
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text

    console = Console()
    HISTORY = os.get_terminal_size()[0] - 14
    
    # use HISTORY_POINTS or a larger width
    # max_history = max(width, 120)
    # history_latency = deque(maxlen=max_history)
    
    history_latency = deque(maxlen=HISTORY)
    
    stats = {
        'sent': 0,
        'received': 0,
        'lost': 0,
        'min': float('inf'),
        'max': 0,
        'latencies': []
    }
    
    running = True

    def stop(sig, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    with Live(refresh_per_second=10, console=console, screen=True) as live:
        while running:
            latency, ttl, success = do_ping(host)
            stats['sent'] += 1
            
            if success:
                stats['received'] += 1
                stats['min'] = min(stats['min'], latency)
                stats['max'] = max(stats['max'], latency)
                stats['latencies'].append(latency)
                history_latency.append(latency)
            else:
                stats['lost'] += 1
                history_latency.append(0)

            # Render chart: check minimum data
            text_graph = Text()
            if len(history_latency) >= 2:
                try:
                    graph = asciichartpy.plot(
                        list(history_latency),
                        {"height": height, "width": width}
                    )
                    text_graph = Text(graph, style="bold #AA55FF")
                except Exception as e:
                    text_graph = Text(f"[Chart Error: {e}]", style="red")
            else:
                # Show placeholders when there is not enough data
                text_graph = Text(f"Collecting data... ({len(history_latency)}/2)", style="dim yellow")

            # Calculate stats
            avg = mean(stats['latencies']) if stats['latencies'] else 0
            packet_loss = (stats['lost'] / stats['sent'] * 100) if stats['sent'] > 0 else 0
            std = stdev(stats['latencies']) if len(stats['latencies']) > 1 else 0
            
            status_style = "red on #FFFF00" if success else "white on red blink"
            status_text = "● CONNECTED" if success else "● TIMEOUT"

            if use_panel:
                combined = Text()
                combined.append(f"Latency: {latency:.2f} ms | TTL: {ttl} | ", style="bold #00FFFF")
                combined.append(status_text, style=status_style)
                combined.append("\n")
                combined.append(text_graph)
                combined.append("\n")
                combined.append(f"Tx: {stats['sent']} | Rx: {stats['received']} | Ls: {stats['lost']} ({packet_loss:.1f}%)\n", style="bold #FFAA00")
                if stats['received'] > 0:
                    combined.append(f"Min: {stats['min']:.2f}ms | Avg: {avg:.2f}ms | Max: {stats['max']:.2f}ms | Std: {std:.2f}ms", style="#00FFFF")

                panel = Panel(
                    combined,
                    title=f"[bold #FFAAFF]Real-time Ping Monitor[/bold] ([cyan]{host}[/cyan])",
                    subtitle=f"[dim]Press Ctrl+C to exit[/dim]"
                )
                live.update(panel)
            else:
                combined = Text()
                # combined.append(f"Ping: {host}\n", style="bold magenta")
                combined.append(f"{host} Latency: {latency:.2f} ms | TTL: {ttl} | ", style="bold #00FFFF")
                combined.append(status_text + "\n", style=status_style)
                combined.append(text_graph)
                combined.append("\n")
                combined.append(f"Tx: {stats['sent']} | Rx: {stats['received']} | Ls: {stats['lost']} ({packet_loss:.1f}%)\n", style="bold #FFAA00")
                if stats['received'] > 0:
                    combined.append(f"Min: {stats['min']:.2f}ms | Avg: {avg:.2f}ms | Max: {stats['max']:.2f}ms | Std: {std:.2f}ms", style="#00FFFF")
                
                live.update(combined)

            time.sleep(INTERVAL)

    console.print("\n✓ Stopped cleanly.")

def parse_args():
    parser = argparse.ArgumentParser(
        description="Real-time ping monitor with latency & TTL tracking",
        prog='ping_monitor',
        formatter_class=CustomRichHelpFormatter
    )

    parser.add_argument(
        "host",
        help="Target host to ping (IP or domain)",
        type=str,
        nargs='?',
        default="8.8.8.8"
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
        "-i", "--interval",
        help="Ping interval in seconds (default: 1)",
        type=float,
        default=1.0
    )

    parser.add_argument(
        "-b", "--basic",
        help="Use basic mode (with screen refresh)",
        action="store_true"
    )

    parser.add_argument(
        "-r", "--rich",
        help="Use Rich mode for better visualization",
        action="store_true"
    )

    parser.add_argument(
        "-p", "--panel",
        help="Use panel in Rich mode",
        action="store_true"
    )

    return parser.parse_args()

if __name__ == "__main__":
    if not PING_AVAILABLE:
        print("\n❌ pythonping is required!")
        print("Install it with: pip install pythonping")
        sys.exit(1)

    args = parse_args()
    
    # global INTERVAL
    INTERVAL = args.interval

    print(f"🔍 Pinging {args.host} every {INTERVAL}s...")
    print("Press Ctrl+C or 'q' to stop\n")

    try:
        if args.basic:
            monitor_ping_basic(args.host, args.height, args.width)
        elif args.rich:
            monitor_ping_rich(args.host, args.height, args.width, args.panel)
        else:
            monitor_ping_advanced(args.host, args.height, args.width)
    except KeyboardInterrupt:
        print("\n\n✓ Stopped by user.")
    except Exception as e:
        if CTRACEBACK_AVAILABLE:
            tprint(*sys.exc_info(), None, False, True)
        else:
            print(f"\n❌ Error: {e}")
            traceback.print_exc()
