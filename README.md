# BK Precision 9141 PVAccess Server

An EPICS PVAccess server for the three-output BK Precision 9141 power supply.

## Running

```bash
uv sync
uv run epicsdev-ps-bk-9141 -r 'TCPIP::192.168.0.100::INSTR'
```

From this directory, `uv run python -m epicsdev_ps_bk_9141` is equivalent.
Use `--help` for options, including `--timeout` (seconds) and `--visa-backend`.
The default backend is PyVISA-py (`@py`); a vendor VISA installation can be
selected with `--visa-backend @ivi`. Other VISA resources require the
corresponding backend support and drivers.

The default PV prefix is `bk9141:0:`. Startup verifies the model and reads its
current configuration without resetting the instrument or changing outputs.
Cached PV values are not applied to hardware; initial readbacks replace them.
Stopping or exiting the server does not turn off the power-supply outputs.

## PVs

Channels use `CH1:`, `CH2:`, and `CH3:` suffixes. For example:

```bash
pvget bk9141:0:CH1:MeasuredVoltage
pvput bk9141:0:CH1:Voltage 5
pvput bk9141:0:CH1:Current 0.5
pvput bk9141:0:CH1:Enable On
```

| Channel PV | Meaning |
| --- | --- |
| `Voltage`, `Current` | Writable voltage setpoint and current limit |
| `OVP`, `OCP` | Writable protection thresholds |
| `Enable`, `OCPEnable` | Writable Off/On controls |
| `VoltageRBV`, `CurrentRBV`, `OVPRBV`, `OCPRBV` | Programmed settings read back from hardware |
| `EnableRBV`, `OCPEnableRBV` | Hardware enable readbacks |
| `MeasuredVoltage`, `MeasuredCurrent`, `MeasuredPower` | Measured V, A, and W |
| `OVPTripped`, `OCPTripped` | Protection trip indicators |
| `RegulationCondition` | Raw non-clearing regulation-condition response |
| `ClearProtection` | Write 1 to clear tripped protections |

Global PVs include `Identification`, `Resource`, `Connected`, `LastError`,
`OutputPairing` (read-only), `AllEnable`, `AllEnableRBV`, and `ClearStatus`.
Write 1 to `ClearStatus` to clear the instrument's error queue and event registers.
`instrCmdS` executes one SCPI command or query; `instrCmdR` contains its reply.
Compound commands are not accepted. Custom commands can change hardware state.

Setpoints must be finite and nonnegative. The instrument enforces its limits,
including those dependent on output pairing. In series, parallel, or tracking
mode, the selected channel's settings may affect other channels as described
in the manual. Use `OutputPairing` to check the current mode.

Polling does not clear event registers. The manual gives inconsistent CV/CC
encodings in section 15.5 and table 15.1, so `RegulationCondition` is not decoded.
Failed polling retains the last complete channel snapshot and sets `Connected`
to 0. The next poll attempts to reconnect; failed writes are never replayed.
Writes query the error queue after completion and report nonzero errors,
including any errors already pending in that queue.

## Tests

```bash
uv run python -m unittest discover -s tests -v
```

Tests use a simulated SCPI instrument and an isolated real p4p server. Physical
hardware is not required.
