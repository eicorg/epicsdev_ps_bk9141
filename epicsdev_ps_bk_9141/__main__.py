"""EPICS PVAccess server for BK Precision 9141 power supply."""
# pylint: disable=invalid-name,broad-exception-caught
__version__ = 'v0.1.0 2026-11-13'

import argparse
import csv
from dataclasses import dataclass
from functools import partial
import math
import threading
import time

import pyvisa

from epicsdev import epicsdev as edev

DEVICE = 'bk9141:'
CHANNELS = (1, 2, 3)
SETPOINTS = (
    ('Voltage', 'Programmed voltage', 'SOUR:VOLT', 'V'),
    ('Current', 'Programmed current limit', 'SOUR:CURR', 'A'),
    ('OVP', 'Overvoltage protection threshold', 'SOUR:VOLT:PROT', 'V'),
    ('OCP', 'Overcurrent protection threshold', 'SOUR:CURR:PROT', 'A'),
)
SWITCHES = (
    ('Enable', 'Output enabled', 'OUTP:STAT'),
    ('OCPEnable', 'Overcurrent protection enabled', 'SOUR:CURR:PROT:STAT'),
)

#````````````````````````````````````````````````````````````````````````````
# Definitions of PVs, their types, units, limits, and setter functions are
# defined in the myPVDefs() function below.
def myPVDefs():
    """Return PV definitions for the three front-panel channels."""
    # abbreviations for PV definition dictionary keys
    F, T, U, LL, LH = 'features', 'type', 'units', 'limitLow', 'limitHigh'
    SET = 'setter'

    pv_defs = [
['dateTime', 'Server local date/time', 'N/A'],
['Resource', 'Instrument VISA resource', C_.pargs.resource],
['Identification', 'Instrument identification', C_.initial['Identification']],
['Connected', 'Last polling cycle succeeded', 1, {T: 'u8'}],
['OutputPairing', 'OFF, PARA2/3, SERI2/3, or TRAC2/3',
    C_.initial['OutputPairing']],
['LastError', 'Last instrument or communication error', ''],
['AllEnable', 'Enable or disable all outputs', ['Off', 'On'],
    {F: 'WD', SET: partial(_set_switch, command='OUTP:ALL', channel=None)}],
['AllEnableRBV', 'All-output enable state', C_.initial['AllEnableRBV'],
    {T: 'u8'}],
['ClearStatus', 'Clear error queue and event registers (write 1)', 0,
    {F: 'W', T: 'u8', LL: 0, LH: 1,
     SET: partial(_set_action, command='*CLS', channel=None)}],
['instrCmdS', 'Execute one SCPI command or query', '*IDN?',
    {F: 'W', SET: _set_instrCmdS}],
['instrCmdR', 'Reply to the custom SCPI command', ''],
    ]
    for channel in CHANNELS:
        prefix = f'CH{channel}:'
        for name, description, command, units in SETPOINTS:
            initial = C_.initial[prefix + name + 'RBV']
            pv_defs.extend([
                [prefix + name, description, initial,
                 {F: 'W', T: 'f64', U: units,
                  SET: partial(_set_number, command=command, channel=channel)}],
                [prefix + name + 'RBV', description + ' readback', initial,
                 {T: 'f64', U: units}],
            ])
        for name, description, command in SWITCHES:
            pv_defs.extend([
                [prefix + name, description, ['Off', 'On'],
                 {F: 'WD', SET: partial(_set_switch, command=command,
                                       channel=channel)}],
                [prefix + name + 'RBV', description + ' readback',
                 C_.initial[prefix + name + 'RBV'], {T: 'u8'}],
            ])
        for name, units in (('MeasuredVoltage', 'V'), ('MeasuredCurrent', 'A'),
                            ('MeasuredPower', 'W')):
            pv_defs.append([prefix + name, name, C_.initial[prefix + name],
                            {T: 'f64', U: units}])
        for name in ('OVPTripped', 'OCPTripped', 'RegulationCondition'):
            pv_defs.append([prefix + name, name, C_.initial[prefix + name],
                            {T: 'u8'}])
        pv_defs.append([
            prefix + 'ClearProtection', 'Clear tripped protections (write 1)',
            0, {F: 'W', T: 'u8', LL: 0, LH: 1,
                SET: partial(_set_action, command='OUTP:PROT:CLE',
                             channel=channel)}])
    return pv_defs
#,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,

@dataclass(slots=True)
class C_:
    """Container for module state variables."""
    pargs = None #
    manager = None
    instrument = None
    lock = threading.RLock()
    initial = {}

def _disconnect():
    """Close a connection whose response stream may be out of sync."""
    with C_.lock:
        if C_.instrument is not None:
            try:
                C_.instrument.close()
            except pyvisa.errors.VisaIOError:
                pass
            C_.instrument = None

def _exchange(command: str, channel=None) -> str:
    """Select a channel and exchange one SCPI command atomically."""
    if not command or any(character in command for character in '\r\n\x00;'):
        raise ValueError('Command must be a single nonempty ASCII line')
    command.encode('ascii')
    if channel is not None and channel not in (1, 2, 3):
        raise ValueError('Channel must be 1, 2, or 3')
    with C_.lock:
        try:
            if C_.instrument is None:
                if C_.manager is None:
                    C_.manager = pyvisa.ResourceManager(C_.pargs.visa_backend)
                C_.instrument = C_.manager.open_resource(C_.pargs.resource)
                C_.instrument.timeout = max(1, int(C_.pargs.timeout * 1000))
                C_.instrument.write_termination = '\n'
                C_.instrument.read_termination = '\n'
            if channel is not None:
                C_.instrument.write(f'INST:SEL {channel - 1}')
            edev.printvv(f'SCPI channel {channel}: {command}')
            if '?' in command:
                return C_.instrument.query(command).strip()
            C_.instrument.write(command)
            return ''
        except (pyvisa.errors.VisaIOError, OSError):
            _disconnect()
            raise

def _number(value) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('Value must be finite')
    return number

def _query_number(command: str, channel=None) -> float:
    return _number(_exchange(command, channel))

def _query_bool(command: str, channel=None) -> int:
    reply = _exchange(command, channel).upper()
    if reply in ('0', 'OFF'):
        return 0
    if reply in ('1', 'ON'):
        return 1
    raise ValueError(f'{command}: unexpected boolean reply {reply!r}')

def _write_checked(command: str, channel=None):
    """Wait for completion and report errors without retrying the write."""
    with C_.lock:
        _exchange(command, channel)
        if _exchange('*OPC?') not in ('1', '+1'):
            raise RuntimeError('Instrument did not confirm operation completion')
        reply = _exchange('SYST:ERR?')
        fields = next(csv.reader([reply], skipinitialspace=True))
        if len(fields) != 2:
            raise ValueError(f'SYST:ERR?: unexpected reply {reply!r}')
        if int(fields[0]) != 0:
            edev.publish('LastError', reply)
            raise RuntimeError(f'{command}: {reply}')

def _switch(value) -> int:
    text = str(value).upper()
    if text in ('OFF', '0'):
        return 0
    if text in ('ON', '1'):
        return 1
    raise ValueError('Expected Off/On or 0/1')

def _set_number(value, *_, command: str, channel: int):
    number = _number(value)
    if number < 0:
        raise ValueError('Setpoints and protection thresholds must be nonnegative')
    _write_checked(f'{command} {number:.12g}', channel)

def _set_switch(value, *_, command: str, channel):
    _write_checked(f'{command} {_switch(value)}', channel)

def _set_action(value, *_, command: str, channel):
    if _switch(value):
        _write_checked(command, channel)

def _set_instrCmdS(value, *_):
    command = str(value).strip()
    if '?' in command:
        reply = _exchange(command)
    else:
        _write_checked(command)
        reply = 'OK'
    edev.publish('instrCmdR', reply)

def _read_snapshot() -> dict:
    """Read channel settings and telemetry without clearing event registers."""
    values = {}
    with C_.lock:
        values['OutputPairing'] = _exchange('OUTP:PAIR?')
        values['AllEnableRBV'] = _query_bool('OUTP:ALL?')
        for channel in CHANNELS:
            prefix = f'CH{channel}:'
            fields = _exchange('MEAS:ALL?', channel).split(',')
            if len(fields) != 3:
                raise ValueError(f'CH{channel}: expected voltage,current,power')
            for name, value in zip(
                    ('MeasuredVoltage', 'MeasuredCurrent', 'MeasuredPower'),
                    fields):
                values[prefix + name] = _number(value)
            for name, _description, command, _units in SETPOINTS:
                values[prefix + name + 'RBV'] = _query_number(command + '?', channel)
            for name, _description, command in SWITCHES:
                values[prefix + name + 'RBV'] = _query_bool(command + '?', channel)
            values[prefix + 'OVPTripped'] = _query_bool('SOUR:VOLT:PROT:TRIP?', channel)
            values[prefix + 'OCPTripped'] = _query_bool('SOUR:CURR:PROT:TRIP?', channel)
            condition = _query_number('STAT:QUES:ISUM:COND?', channel)
            if condition not in (0, 1, 2):
                raise ValueError(f'CH{channel}: unexpected regulation condition {condition}')
            values[prefix + 'RegulationCondition'] = int(condition)
    return values

def _read_initial():
    identification = _exchange('*IDN?')
    fields = identification.split(',')
    if len(fields) < 2 or fields[1].strip().upper() != '9141':
        raise ValueError(f'Expected BK Precision 9141, received {identification!r}')
    C_.initial = _read_snapshot()
    C_.initial['Identification'] = identification

def _publish_snapshot(values):
    for name, value in values.items():
        edev.publish(name, value, ifChanged=True)
        if name.endswith('RBV'):
            edev.publish(name[:-3], value, ifChanged=True)

def poll():
    """Retain the last complete snapshot on communication or parsing failure."""
    try:
        with C_.lock:
            _publish_snapshot(_read_snapshot())
            edev.publish('Connected', 1, ifChanged=True)
    except (pyvisa.errors.VisaIOError, OSError, ValueError, RuntimeError) as exc:
        _disconnect()
        edev.publish('Connected', 0, ifChanged=True)
        edev.publish('LastError', str(exc), ifChanged=True)
        edev.printe(f'BK 9141 polling: {exc}')

def periodic_update():
    """Update server time, including while hardware polling is stopped."""
    edev.publish('dateTime', time.strftime('%Y-%m-%d %H:%M:%S'), ifChanged=True)

def serverStateChanged(newState: str):
    """Callback for server state transitions."""
    if newState == 'Start':
        edev.printi('Start requested')
    elif newState == 'Stop':
        edev.printi('Stop requested')
    elif newState == 'Exit':
        edev.printi('Exit requested')

def _positive(value: str) -> float:
    try:
        number = _number(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError('Value must be finite and positive') from exc
    if number <= 0:
        raise argparse.ArgumentTypeError('Value must be finite and positive')
    return number

def main(argv=None):
    """Connect to the instrument and run its PVAccess server."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        epilog=f'{__version__}, epicsdev:{edev.__version__}',
    )
    # commonly used options
    parser.add_argument('-a', '--autosave', nargs='?', default='', help=
'Autosave control. If omitted, autosave is enabled with default directory.')
    parser.add_argument('-c', '--recall', action='store_false', help=
'If given: do not restore initial PV values from autosave cache.')
    parser.add_argument('-i', '--instance', default='0', help=
'Device instance.')
    parser.add_argument('-p', '--putlogPV', nargs='?', default='', help=
'PV name for logging put operations. Empty means default putlog:dump.')
    parser.add_argument('-r', '--resource', default='TCPIP::192.168.0.100::INSTR', help=
'VISA resource string for the instrument.')
    parser.add_argument('-v', '--verbose', action='count', default=0, help=
'Increase verbosity (-vv for more).')
    parser.add_argument('device', nargs='?', default=DEVICE, help=
'Device name, the prefix for all generated PVs <prefix><instance>:')

    parser.add_argument('--timeout', type=_positive, default=2.0, help=
'VISA transaction timeout in seconds.')
    parser.add_argument('--visa-backend', default='@py', help=
'VISA backend; @py uses PyVISA-py, @ivi uses a vendor VISA library.')

    # Parse command-line arguments and store them in the module state container.
    C_.pargs = parser.parse_args(argv)
    if C_.pargs.putlogPV == '':
        C_.pargs.putlogPV = 'putlog:dump'
    C_.pargs.prefix = f'{C_.pargs.device}{C_.pargs.instance}:'

    try:
        _read_initial()
    except (pyvisa.errors.VisaIOError, OSError, ValueError, RuntimeError) as exc:
        _disconnect()
        if C_.manager is not None:
            C_.manager.close()
        parser.exit(1, f'Cannot initialize BK Precision 9141: {exc}\n')

    # Initialize PV definitions.
    C_.PvDefs = myPVDefs()

    # Initialize the EPICS PVAccess server with the defined PVs.
    PVs = edev.init_epicsdev(
        C_.pargs.prefix,
        C_.PvDefs,
        C_.pargs.verbose,
        serverStateChanged,
        None,# to write list of PVs to /tmp/pvlist/
        C_.pargs.autosave,
        C_.pargs.recall,
        C_.pargs.putlogPV,
    )
    print(f'Using PV prefix: {C_.pargs.prefix}')
    _publish_snapshot(C_.initial)
    periodic_update()

    # Start the server and print initial status.
    edev.publish('VERSION', __version__)
    edev.set_server('Start')
    server = edev.Server(providers=[PVs])
    edev.printi((f'Server for {C_.pargs.prefix} started. Sleeping per cycle: '
                 f'{repr(edev.pvv("sleep"))} S.'))

    # Main server loop. Polls for updates and handles server state transitions.
    try:
        while True:
            state = edev.serverState()
            if state.startswith('Exit'):
                break
            if not state.startswith('Stop'):
                poll()
            if not edev.sleep():
                periodic_update()
    except KeyboardInterrupt:
        edev.printi('Keyboard interrupt received, exiting main loop...')
        edev.set_server('Exit')
    except OSError:
        pass
    finally:
        server.stop()
        _disconnect()
        if C_.manager is not None:
            C_.manager.close()

    edev.printi('Server is exited')

if __name__ == '__main__':
    main()
