#!/usr/bin/python
from hbp_nrp_virtual_coach.virtual_coach import VirtualCoach
vc = VirtualCoach(environment='local', storage_username='nrpuser', storage_password='password')

import sys
from StringIO import StringIO
old_stdout = sys.stdout
result = StringIO()
sys.stdout = result
vc.print_cloned_experiments()
sys.stdout = old_stdout
result_string = result.getvalue()
if not("ser_rl_ss20_0" in result_string):
    vc.import_experiment('/home/bbpnrsoa/nrp/src/Worker/ser_rl_ss20.zip')
else: print("Experiment already imported")

sim = vc.launch_experiment('ser_rl_ss20_0')
sim.start()
exit()

