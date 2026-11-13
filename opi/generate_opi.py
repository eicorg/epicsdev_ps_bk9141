"""Operator interface generator for BK Precision 9141"""
__version__ = 'v0.1.0 2026-11-13'
# pylint: disable=invalid-name,broad-exception-caught

import argparse
from pathlib import Path

import phoebusgen.screen
import phoebusgen.widget

DEVICE = "bk9141"
INSTANCE = "0"
TITLE = 'BK Precision 9141'
OUTPUT = f'{DEVICE}{INSTANCE}.bob'
PREFIX = f'pva://{DEVICE}:{INSTANCE}:'

def _parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        epilog=__version__,
    )
    parser.add_argument("-t", "--title", default=TITLE, help="Screen title")
    parser.add_argument("prefix", nargs="?", default=PREFIX,
        help=(
            "PV prefix used for all widget PV names. "
        ),
    )
    return parser.parse_args(argv)

def _add_items(widget, values: str) -> None:
    for item in values.split(", "):
        widget.item(item)

def _indicator(name, pv_name, x, y, fault=False):
    indicator = phoebusgen.widget.LED(name, pv_name, x, y, 22, 22)
    indicator.labels_from_pv(False)
    indicator.off_label('')
    indicator.on_label('')
    indicator.off_color(*( (46, 139, 87) if fault else (155, 163, 170) ))
    indicator.on_color(*( (196, 45, 45) if fault else (46, 139, 87) ))
    return indicator

def _clear_button(name, pv_name, text, x, y, width):
    button = phoebusgen.widget.ActionButton(name, text, pv_name, x, y, width, 28)
    button.action_write_pv(pv_name, 1, text)
    return button

def main(argv=None) -> Path:
    pargs = _parse_args(argv)
    prefix = pargs.prefix

    screen = phoebusgen.screen.Screen(pargs.title, OUTPUT)
    screen.width(1140)
    screen.height(850)

    w = phoebusgen.widget
    widgets = {
        "title": w.Label("title", pargs.title, 20, 10, 330, 30),
        "Identification": w.TextUpdate("Identification", f"{prefix}Identification", 370, 14, 510, 24),
        "dateTime": w.TextUpdate("dateTime", f"{prefix}dateTime", 900, 14, 220, 24),
        "Resource_lbl": w.Label("Resource_lbl", "Resource:", 20, 50, 80, 24),
        "Resource": w.TextUpdate("Resource", f"{prefix}Resource", 105, 50, 550, 24),
        "Connected_lbl": w.Label("Connected_lbl", "Connected:", 715, 50, 90, 24),
        "Connected": _indicator("Connected", f"{prefix}Connected", 810, 50),
        "OutputPairing_lbl": w.Label("OutputPairing_lbl", "Pairing:", 860, 50, 65, 24),
        "OutputPairing": w.TextUpdate("OutputPairing", f"{prefix}OutputPairing", 930, 50, 190, 24),
    }
    y = 82
    widgets.update({
        "srvStatus_lbl": w.Label("srvStatus_lbl", "Server:", 20, y, 70, 24),
        "srvStatus": w.TextUpdate("srvStatus", f"{prefix}status", 95, y, 1025, 24),
    })
    y = 116
    widgets.update({
        "state_lbl": w.Label("state_lbl", "Run/Stop:", 20, y, 65, 20),
        "server": w.ComboBox("server", f"{prefix}server", 90, y, 110, 20),
        "sleep_lbl": w.Label("sleep_lbl", "Sleep:", 410, y, 40, 20),
        "sleep": w.TextEntry("sleep", f"{prefix}sleep", 450, y, 50, 20),
        "cycleTime_lbl": w.Label("cycleTime_lbl", "Period:", 510, y, 50, 20),
        "cycleTime": w.TextUpdate("cycleTime", f"{prefix}cycleTime", 560, y, 60, 20),
        "hb_lbl": w.Label("hb_lbl", "HB:", 640, y, 30, 20),
        "HEARTBEAT": w.TextUpdate("HEARTBEAT", f"{prefix}HEARTBEAT", 670, y, 70, 20),
        "VERSION": w.TextUpdate("VERSION", f"{prefix}VERSION", 770, y, 350, 20),
    })

    widgets.update({
        "LastError_lbl": w.Label("LastError_lbl", "Last error:", 20, 148, 80, 24),
        "LastError": w.TextUpdate("LastError", f"{prefix}LastError", 105, 148, 1015, 24),
        "AllEnable_lbl": w.Label("AllEnable_lbl", "All outputs:", 20, 182, 110, 24),
        "AllEnable": w.ComboBox("AllEnable", f"{prefix}AllEnable", 135, 182, 85, 24),
        "AllEnableRBV_lbl": w.Label("AllEnableRBV_lbl", "Readback:", 245, 182, 95, 24),
        "AllEnableRBV": _indicator("AllEnableRBV", f"{prefix}AllEnableRBV", 345, 182),
        "ClearStatus": _clear_button("ClearStatus", f"{prefix}ClearStatus",
                                     "Clear error queue / status", 850, 180, 270),
    })
    _add_items(widgets["server"], "Start, Stop, Clear, Exit, Started, Stopped, Exited")
    _add_items(widgets["AllEnable"], "Off, On")

    for channel in (1, 2, 3):
        x = 20 + (channel - 1) * 370
        channel_prefix = f"CH{channel}:"
        widgets[channel_prefix + "title"] = w.Label(
            channel_prefix + "title", f"Channel {channel}", x, 232, 340, 28)

        for row, (name, label) in enumerate((
                ("MeasuredVoltage", "Voltage (V):"),
                ("MeasuredCurrent", "Current (A):"),
                ("MeasuredPower", "Power (W):"))):
            y = 270 + row * 30
            pv_name = channel_prefix + name
            widgets[pv_name + "_lbl"] = w.Label(pv_name + "_lbl", label, x, y, 150, 24)
            widgets[pv_name] = w.TextUpdate(pv_name, prefix + pv_name, x + 165, y, 165, 24)
            widgets[pv_name].format("Decimal")
            widgets[pv_name].precision(3)

        widgets[channel_prefix + "set_lbl"] = w.Label(
            channel_prefix + "set_lbl", "Setpoint", x + 145, 375, 85, 24)
        widgets[channel_prefix + "rbv_lbl"] = w.Label(
            channel_prefix + "rbv_lbl", "Readback", x + 245, 375, 85, 24)
        for row, (name, label) in enumerate((
                ("Voltage", "Voltage (V):"), ("Current", "Current limit (A):"),
                ("OVP", "OVP (V):"), ("OCP", "OCP (A):"))):
            y = 407 + row * 32
            pv_name = channel_prefix + name
            widgets[pv_name + "_lbl"] = w.Label(pv_name + "_lbl", label, x, y, 140, 24)
            widgets[pv_name] = w.TextEntry(pv_name, prefix + pv_name, x + 145, y, 85, 24)
            readback = pv_name + "RBV"
            widgets[readback] = w.TextUpdate(readback, prefix + readback, x + 245, y, 85, 24)
            for item in (pv_name, readback):
                widgets[item].format("Decimal")
                widgets[item].precision(3)

        for row, (name, label) in enumerate((
                ("Enable", "Output:"), ("OCPEnable", "OCP enabled:"))):
            y = 548 + row * 32
            pv_name = channel_prefix + name
            widgets[pv_name + "_lbl"] = w.Label(pv_name + "_lbl", label, x, y, 125, 24)
            widgets[pv_name] = w.ComboBox(pv_name, prefix + pv_name, x + 130, y, 100, 24)
            _add_items(widgets[pv_name], "Off, On")
            readback = pv_name + "RBV"
            widgets[readback] = _indicator(readback, prefix + readback, x + 280, y)

        for row, (name, label) in enumerate((
                ("OVPTripped", "OVP tripped:"), ("OCPTripped", "OCP tripped:"))):
            y = 618 + row * 28
            pv_name = channel_prefix + name
            widgets[pv_name + "_lbl"] = w.Label(pv_name + "_lbl", label, x, y, 210, 24)
            widgets[pv_name] = _indicator(pv_name, prefix + pv_name, x + 280, y, fault=True)

        pv_name = channel_prefix + "RegulationCondition"
        widgets[pv_name + "_lbl"] = w.Label(pv_name + "_lbl", "Regulation (raw):", x, 678, 210, 24)
        widgets[pv_name] = w.TextUpdate(pv_name, prefix + pv_name, x + 245, 678, 85, 24)
        widgets[pv_name].format("Decimal")
        widgets[pv_name].precision(0)
        pv_name = channel_prefix + "ClearProtection"
        widgets[pv_name] = _clear_button(pv_name, prefix + pv_name,
                                          "Clear protection", x, 710, 340)

    widgets.update({
        "instrCmdS_lbl": w.Label("instrCmdS_lbl", "SCPI:", 20, 770, 80, 24),
        "instrCmdS": w.TextEntry("instrCmdS", f"{prefix}instrCmdS", 105, 770, 1015, 24),
        "instrCmdR_lbl": w.Label("instrCmdR_lbl", "Reply:", 20, 808, 80, 24),
        "instrCmdR": w.TextUpdate("instrCmdR", f"{prefix}instrCmdR", 105, 808, 1015, 24),
    })
    for name in ("sleep", "cycleTime"):
        widgets[name].format("Decimal")
        widgets[name].precision(3)
    widgets["HEARTBEAT"].format("Decimal")
    widgets["HEARTBEAT"].precision(0)

    screen.add_widget(list(widgets.values()))

    out = Path(__file__).with_name(OUTPUT)
    screen.write_screen(str(out))
    return out

if __name__ == "__main__":
    main()
