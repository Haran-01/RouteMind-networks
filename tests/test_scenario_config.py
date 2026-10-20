import copy
import sys
from pathlib import Path
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'scripts'))
from scenario_config import DEFAULT, validate, write_network


class ScenarioConfigurationTests(unittest.TestCase):
    def custom(self):
        value=copy.deepcopy(DEFAULT)
        value['custom']=True
        return value

    def test_modified_network_and_traffic_are_preserved(self):
        value=self.custom()
        value['traffic']['udp_rate']=.512
        value['network']['links'][1]['capacity']=9
        result=validate(value)
        self.assertEqual(result['traffic']['udp_rate'],.512)
        self.assertEqual(result['network']['links'][1]['capacity'],9)

    def test_unconnected_router_is_rejected(self):
        value=self.custom()
        value['network']['nodes']=9
        with self.assertRaisesRegex(ValueError,'connected'):
            validate(value)

    def test_duplicate_link_is_rejected(self):
        value=self.custom()
        value['network']['links'].append(copy.deepcopy(value['network']['links'][0]))
        with self.assertRaisesRegex(ValueError,'duplicate'):
            validate(value)

    def test_host_roles_cannot_be_rewired(self):
        value=self.custom()
        value['network']['links'][0]['to']=3
        with self.assertRaisesRegex(ValueError,'Host attachments'):
            validate(value)

    def test_nonfinite_and_fractional_ids_are_rejected(self):
        for key,value in [('duration',float('nan')),('seed',1.5),('seed',True)]:
            config=copy.deepcopy(DEFAULT)
            config[key]=value
            with self.assertRaises(ValueError):
                validate(config)

    def test_failure_must_name_a_real_link_and_valid_schedule(self):
        value=self.custom()
        value['failure']['to']=6
        with self.assertRaisesRegex(ValueError,'must exist'):
            validate(value)
        value=self.custom()
        value['failure']['up']=value['failure']['down']
        with self.assertRaisesRegex(ValueError,'Restoration'):
            validate(value)

    def test_template_calibration_constraints(self):
        value=copy.deepcopy(DEFAULT)
        value['scenario']='calibration'
        with self.assertRaisesRegex(ValueError,'static'):
            validate(value)


if __name__=='__main__':
    unittest.main()
