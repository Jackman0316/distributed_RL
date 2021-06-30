#!/bin/bash
cd ~/nrp/src/Worker
PYTHONPATH="/home/bbpnrsoa/nrp/src/retina/build/lib:/home/bbpnrsoa/nrp/src/GazeboRosPackages/devel/lib/python2.7/dist-packages:/opt/ros/melodic/lib/python2.7/dist-packages:/home/bbpnrsoa/.local/lib/python2.7/site-packages:/home/bbpnrsoa/.local/lib/x86_64-linux-gnu/python2.7/site-packages:/home/bbpnrsoa/nrp/src/GazeboRosPackages/devel/lib/python2.7/dist-packages:/home/bbpnrsoa/nrp/src/CLE/hbp_nrp_cle:/home/bbpnrsoa/nrp/src/ExperimentControl/hbp_nrp_excontrol:/home/bbpnrsoa/nrp/src/ExperimentControl/hbp_nrp_scxml:/home/bbpnrsoa/nrp/src/ExDBackend/hbp_nrp_backend:/home/bbpnrsoa/nrp/src/ExDBackend/hbp_nrp_cleserver:/home/bbpnrsoa/nrp/src/ExDBackend/hbp_nrp_commons:/home/bbpnrsoa/nrp/src/ExDBackend/hbp_nrp_watchdog:/home/bbpnrsoa/nrp/src/ExDBackend/hbp-flask-restful-swagger-master:/home/bbpnrsoa/nrp/src/VirtualCoach/hbp_nrp_virtual_coach:/home/bbpnrsoa/nrp/src/BrainSimulation/hbp_nrp_distributed_nest"
export PYTHONPATH
. $HBP/user-scripts/nrp_variables
. $HBP/user-scripts/nrp_aliases
cle-virtual-coach start_experiment.py
sleep 5
key="$1"
case $key in
    --fast_test)
        echo "Executing Fast Test!"
        python worker.py --fast_test=True
    ;;
    *)
        python worker.py
    ;;
esac