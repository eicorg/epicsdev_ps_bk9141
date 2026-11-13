"""SCPI routing and PVAccess integration tests without physical hardware."""
# pylint: disable=protected-access,broad-exception-caught

from importlib import import_module
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import pyvisa
from p4p.client.thread import Context
from p4p.server import Server

driver = import_module('epicsdev_ps_bk_9141.__main__')


class Instrument:
    def __init__(self):
        self.channel = 0
        self.commands = []
        self.closed = False
        self.timeout = 0
        self.error = '0,"No error"'
        self.identification = 'B&K Precision,9141,12345,1.06'
        self.measurements = '5,0.5,2.5'
        self.settings = [
            {'SOUR:VOLT': 5, 'SOUR:CURR': 0.5, 'SOUR:VOLT:PROT': 60,
             'SOUR:CURR:PROT': 4, 'OUTP:STAT': 0,
             'SOUR:CURR:PROT:STAT': 1} for channel in driver.CHANNELS
        ]

    def write(self, command):
        self.commands.append(command)
        if command.startswith('INST:SEL '):
            self.channel = int(command.split()[1])
        elif command == 'OUTP:ALL 0' or command == 'OUTP:ALL 1':
            for settings in self.settings:
                settings['OUTP:STAT'] = int(command[-1])
        elif ' ' in command:
            name, value = command.split(' ', 1)
            self.settings[self.channel][name] = float(value)

    def query(self, command):
        self.commands.append(command)
        if command == '*IDN?':
            return self.identification
        if command == '*OPC?':
            return '+1'
        if command == 'SYST:ERR?':
            reply, self.error = self.error, '0,"No error"'
            return reply
        if command == 'OUTP:PAIR?':
            return 'OFF'
        if command == 'OUTP:ALL?':
            return str(int(all(settings['OUTP:STAT'] for settings in self.settings)))
        if command == 'MEAS:ALL?':
            return self.measurements
        if command.endswith('TRIP?'):
            return '0'
        if command == 'STAT:QUES:ISUM:COND?':
            return '2'
        if command[:-1] in ('OUTP:STAT', 'SOUR:CURR:PROT:STAT'):
            return str(int(self.settings[self.channel][command[:-1]]))
        return str(self.settings[self.channel][command[:-1]])

    def close(self):
        self.closed = True


class DriverTests(unittest.TestCase):
    def setUp(self):
        self.instrument = Instrument()
        self.manager = Mock()
        self.manager.open_resource.return_value = self.instrument
        self.state = patch.multiple(
            driver.C_, instrument=self.instrument, manager=self.manager,
            initial={}, pargs=SimpleNamespace(resource='mock', timeout=2,
                                             visa_backend='@py'))
        self.state.start()
        self.addCleanup(self.state.stop)
        self.publish_patch = patch.object(driver.edev, 'publish')
        self.publish = self.publish_patch.start()
        self.addCleanup(patch.stopall)
        self.log = patch.object(driver.edev, 'printe').start()

    def definitions(self):
        driver._read_initial()
        return {definition[0]: definition for definition in driver.myPVDefs()}

    def test_initialization_is_read_only_and_pvs_are_unique(self):
        definitions = self.definitions()
        self.assertEqual(len(definitions), 68)
        self.assertEqual(len(driver.myPVDefs()), len(definitions))
        self.assertTrue(all('?' in command or command.startswith('INST:SEL ')
                            for command in self.instrument.commands))
        self.assertEqual(driver.C_.initial['CH3:MeasuredPower'], 2.5)

    def test_wrong_model_is_rejected(self):
        self.instrument.identification = 'B&K Precision,9140,12345,1.06'
        with self.assertRaisesRegex(ValueError, 'Expected BK Precision 9141'):
            driver._read_initial()

    def test_channel_setters_and_enum_values(self):
        definitions = self.definitions()
        for channel in driver.CHANNELS:
            self.instrument.commands.clear()
            definitions[f'CH{channel}:Voltage'][3]['setter'](7.5, None)
            self.assertEqual(self.instrument.commands, [
                f'INST:SEL {channel - 1}', 'SOUR:VOLT 7.5', '*OPC?', 'SYST:ERR?'])
        definitions['CH2:Enable'][3]['setter']('On', None)
        self.assertEqual(self.instrument.settings[1]['OUTP:STAT'], 1)
        definitions['AllEnable'][3]['setter']('0', None)
        self.assertTrue(all(settings['OUTP:STAT'] == 0
                            for settings in self.instrument.settings))

    def test_invalid_inputs_never_reach_the_instrument(self):
        for value in (-1, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                driver._set_number(value, command='SOUR:VOLT', channel=1)
        for command in ('', 'OUTP 1\n', 'OUTP 1;*IDN?'):
            with self.assertRaises(ValueError):
                driver._exchange(command, 1)
        with self.assertRaises(ValueError):
            driver._exchange('MEAS:ALL?', 0)
        with self.assertRaises(ValueError):
            driver._switch('invalid')
        self.assertEqual(self.instrument.commands, [])

    def test_error_queue_rejects_a_write(self):
        self.instrument.error = '-222,"Data out of range, limit exceeded"'
        with self.assertRaisesRegex(RuntimeError, 'Data out of range'):
            driver._set_number(100, command='SOUR:VOLT', channel=1)
        self.publish.assert_called_with('LastError',
                                         '-222,"Data out of range, limit exceeded"')

    def test_malformed_poll_preserves_channel_values(self):
        driver.poll()
        self.publish.assert_any_call('Connected', 1, ifChanged=True)
        self.publish.reset_mock()
        self.instrument.measurements = '5,0.5'
        driver.poll()
        self.publish.assert_any_call('Connected', 0, ifChanged=True)
        self.assertFalse(any(call.args[0].startswith('CH')
                             for call in self.publish.call_args_list))
        self.assertTrue(self.instrument.closed)

    def test_timeout_disconnects_and_next_query_reconnects(self):
        original_query = self.instrument.query
        self.instrument.query = Mock(side_effect=pyvisa.errors.VisaIOError(
            pyvisa.constants.StatusCode.error_timeout))
        with self.assertRaises(pyvisa.errors.VisaIOError):
            driver._exchange('MEAS:ALL?', 3)
        self.assertIsNone(driver.C_.instrument)
        self.assertTrue(self.instrument.closed)
        self.instrument.query = original_query
        self.assertEqual(driver._exchange('MEAS:ALL?', 3), '5,0.5,2.5')
        self.manager.open_resource.assert_called_once_with('mock')
        self.assertEqual(self.instrument.timeout, 2000)

    def test_channel_transactions_do_not_interleave(self):
        barrier = threading.Barrier(2)
        failures = []

        def write_channel(channel):
            try:
                barrier.wait(timeout=3)
                for iteration in range(20):
                    driver._set_number(iteration, command='SOUR:VOLT', channel=channel)
            except Exception as exc:
                failures.append(exc)

        workers = [threading.Thread(target=write_channel, args=(channel,))
                   for channel in (1, 3)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
        self.assertEqual(failures, [])
        for offset in range(0, len(self.instrument.commands), 4):
            transaction = self.instrument.commands[offset:offset + 4]
            self.assertIn(transaction[0], ('INST:SEL 0', 'INST:SEL 2'))
            self.assertTrue(transaction[1].startswith('SOUR:VOLT '))
            self.assertEqual(transaction[2:], ['*OPC?', 'SYST:ERR?'])

    def test_real_pvaccess_reads_and_writes(self):
        self.definitions()
        self.publish_patch.stop()
        driver.edev.C_.prefix = 'bk9141:test:'
        providers = driver.edev.create_pvDefs(driver.myPVDefs())
        driver._publish_snapshot(driver.C_.initial)
        with Server(providers=[providers], isolate=True) as server:
            with Context('pva', conf=server.conf(), useenv=False) as client:
                self.assertEqual(float(client.get('bk9141:test:CH3:VoltageRBV')), 5)
                client.put('bk9141:test:CH3:Voltage', 12.5, timeout=3)
                self.assertEqual(self.instrument.settings[2]['SOUR:VOLT'], 12.5)
                client.put('bk9141:test:CH2:Enable', 'On', timeout=3)
                self.assertEqual(self.instrument.settings[1]['OUTP:STAT'], 1)
                driver.poll()
                self.assertEqual(float(client.get('bk9141:test:CH3:VoltageRBV')), 12.5)
                self.instrument.error = '-222,"Data out of range"'
                with self.assertRaisesRegex(Exception, 'Data out of range'):
                    client.put('bk9141:test:CH3:Voltage', 100, timeout=3)


if __name__ == '__main__':
    unittest.main()