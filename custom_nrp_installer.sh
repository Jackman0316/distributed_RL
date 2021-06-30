#!/bin/bash

# NRP DEVELOPER, VERY IMPORTANT: increment the VERSION on every commit, since it will force an update on users' side

VERSION=1.16

restart() {
  container=$1
  echo -e "${BLUE}Restarting $container${NC}"
  $DOCKER_CMD restart $container && $DOCKER_CMD exec $container bash -c "sudo /etc/init.d/supervisor start"
  echo -e "${GREEN}$container container has now been restarted.${NC}"
}

stop() {
  container=$1
  echo -e "${BLUE}Stopping $container${NC}"
  $DOCKER_CMD stop $container
  echo -e "${GREEN}$container container has now been stopped.${NC}"
}

delete() {
  container=$1
  while true; do
    echo -e "${YELLOW}$container container will be deleted. You will lose any data you may have changed inside it (but not your experiments and models). Can we proceed? [y/n] ${NC}"
    read yn
    case $yn in
      [Yy]* )
              echo -e "${BLUE}Deleting $container container${NC}"
              $DOCKER_CMD rm $container
              echo -e "${GREEN}Successfully deleted old $container container.${NC}"
              return 0;;
      [Nn]* ) return 1;;
      * ) echo "Please answer yes or no.";;
    esac
  done
}

restore() {
  container=$1
  set +e
  stop $1
  delete $1 && start $1 || restart $1
  set -e
}

start(){
  container=$1
  
  if [ "${container}" == "frontend" ] 
  then
  	eval "image=\${frontend_image}"
  	eval "port=\${${container}_port}"
  	ipvar=$container"_ip"
  	iparg=`eval $is_mac || echo --ip=${!ipvar}`
  else
    	eval "port=\${nrp_port}"
  	eval "image=\${nrp_image}"
  	backend_no=$(echo $container | cut -c 4-)
  	curr_ip=${nrp_ips[$backend_no]}
  	echo "NRP Container #$backend_no on IP $curr_ip:"
  	iparg="--ip=$curr_ip"
  fi
  #check_port $port
  
  echo -e "${BLUE}Starting $container container on port $port using image $image${NC}"
  
  $DOCKER_CMD run -itd \
    -P \
    --net=nrpnet \
    $iparg \
    -v "$container"_user_data:/home/bbpnrsoa/.opt/nrpStorage \
    -v "$container"_models:/home/bbpnrsoa/nrp/src/Models \
    -v "$container"_experiments:/home/bbpnrsoa/nrp/src/Experiments \
    --name $container $image
  if [ "${container}" == "frontend" ] 
    then
  	eval setup_frontend
    else
  	eval setup_nrp $container
  fi
  echo -e "${GREEN}$container container is now up and running.${NC}"
}

pull_images(){
  echo "Start IP: "$nrp_ip
  echo -e "${BLUE}Pulling frontend image, this may take a while..${NC}"
  $DOCKER_CMD pull hbpneurorobotics/nrp_frontend:dev
  echo -e "${GREEN}Successfully downloaded frontend image.${NC}"
  echo -e "${BLUE}Pulling nrp image, this may take even longer..${NC}"
  $DOCKER_CMD pull hbpneurorobotics/nrp:dev
  echo -e "${GREEN}Successfully downloaded nrp image.${NC}"
  set +e
  $DOCKER_CMD network create -d bridge --subnet $subnet.0.0/16 --gateway $subnet.0.1 nrpnet
  set -e
  for ((i=0; i<num_backends; i++))
  do
	curr_nrp=${nrp_backends[$i]}
  	$DOCKER_CMD volume create $curr_nrp"_models"
  	$DOCKER_CMD volume create $curr_nrp"_experiments"
  	$DOCKER_CMD volume create $curr_nrp"_user_data"
  	if [[ $($DOCKER_CMD ps -a | grep -w $curr_nrp$) ]]
  	then
      		echo -e "A $curr_nrp container is already running."
      		restore $curr_nrp
  	else
      		start $curr_nrp
  	fi
  done
  if [[ $($DOCKER_CMD ps -a | grep -w frontend$) ]]
    then
      echo -e "A frontend container is already running."
      restore frontend
    else
      start frontend
  fi
  echo -e "${BLUE}Removing old unused images${NC}"
  $DOCKER_CMD system prune
  echo ""
  #create config.json object for multiple backends
  json='"servers": {'
  for ((i=0; i<num_backends-1; i++))
  do
	curr_ip=${nrp_ips[$i]}
	curr_backend=${nrp_backends[$i]}
	echo $curr_backend : $curr_ip
	json+='
    "'$curr_ip'": {
      "gzweb": {
        "assets": "http://'$curr_ip':8080/assets",
        "nrp-services": "http://'$curr_ip':8080",
        "videoStreaming": "http://'$curr_ip':8080/webstream/",
        "websocket": "ws://'$curr_ip':8080/gzbridge"
      },
      "rosbridge": {
        "websocket": "ws://'$curr_ip':8080/rosbridge"
      },
      "serverJobLocation": "local"
    },'
	#echo $nrp_backends[$i] $nrp_ips[$i]	
  done
  curr_ip=${nrp_ips[$(($num_backends-1))]}
	curr_backend=${nrp_backends[$(($num_backends-1))]}
	echo $curr_backend : $curr_ip
	json+='
    "'$curr_ip'": {
      "gzweb": {
        "assets": "http://'$curr_ip':8080/assets",
        "nrp-services": "http://'$curr_ip':8080",
        "videoStreaming": "http://'$curr_ip':8080/webstream/",
        "websocket": "ws://'$curr_ip':8080/gzbridge"
      },
      "rosbridge": {
        "websocket": "ws://'$curr_ip':8080/rosbridge"
      },
      "serverJobLocation": "local"
    }'
  json+='}'
  echo -e "${RED}Important: ${NC}
Please edit the ${PURPLE}server ${NC}object of the config.json file located in ${PURPLE}nrp/src/nrpBackendProxy/config.json ${NC}to match the object generated in the file named ${PURPLE}custom_nrp_config.json ${NC}
Then restart the frontend!
To do this, attach to the running frontend-container with the command ${PURPLE}connect_frontend ${NC}and edit the file.
Then use ${PURPLE}restart_frontend ${NC}to restart the frontend container and apply the changes you made."
  echo $json > custom_nrp_config.json
  echo -e "${GREEN}
Congratulations! The NRP platform is now installed on your computer.

${NC}
You can check everything works by going to ${PURPLE}http://localhost:9000/#/esv-private ${NC}or if you used the --ip option: ${PURPLE}http://$external_frontend_ip:9000/#/esv-private ${NC}by using your browser and signing in with the following credentials:

username : nrpuser
password : password

If you need any help please use our forum: ${PURPLE}https://forum.humanbrainproject.eu/c/neurorobotics${NC}"




}

setup_nrp(){
  curr_nrp=$1
  echo -e "${BLUE}Setting up $curr_nrp container${NC}"
  $DOCKER_CMD exec $curr_nrp bash -c 'echo "127.0.0.1 $(uname -n)" | sudo tee --append /etc/hosts'
  set +e
  echo -e "${BLUE}Cloning template models, this may take a while${NC}"
  #Caching files for faster install
  if [ ! -d "./Models" ] 
  then git clone --progress --branch=master18 https://bitbucket.org/hbpneurorobotics/Models.git ./Models
  fi
  $DOCKER_CMD cp ./Models $curr_nrp:/home/bbpnrsoa/nrp/src/
  $DOCKER_CMD exec $curr_nrp bash -c '{ cd /home/bbpnrsoa/nrp/src/Models && git config remote.origin.fetch "+refs/heads/master*:refs/remotes/origin/master*" && sudo git checkout master18 && sudo git pull; }'
  echo -e "${BLUE}Cloning template experiments, this may take a while${NC}"
  if [ ! -d "./Experiments" ] 
  then git clone --progress --branch=master18 https://bitbucket.org/hbpneurorobotics/Experiments.git ./Experiments
  fi
  $DOCKER_CMD cp ./Experiments $curr_nrp:/home/bbpnrsoa/nrp/src/
  $DOCKER_CMD exec $curr_nrp bash -c '{ cd /home/bbpnrsoa/nrp/src/Experiments && git config remote.origin.fetch "+refs/heads/master*:refs/remotes/origin/master*" && sudo git checkout master18 && sudo git pull; }'
  $DOCKER_CMD exec $curr_nrp bash -c 'sudo chown -R bbpnrsoa:bbp-ext /home/bbpnrsoa/nrp/src/Experiments && sudo chown -R bbpnrsoa:bbp-ext /home/bbpnrsoa/nrp/src/Models'
  set -e
  echo -e "${BLUE}Setting rendering mode to CPU${NC}"
  $DOCKER_CMD exec $curr_nrp bash -c '/home/bbpnrsoa/nrp/src/user-scripts/rendering_mode cpu'
  echo -e "${BLUE}Generating low resolution textures${NC}"
  $DOCKER_CMD exec $curr_nrp bash -c 'python /home/bbpnrsoa/nrp/src/user-scripts/generatelowrespbr.py'
  $DOCKER_CMD exec $curr_nrp bash -c 'export NRP_MODELS_DIRECTORY=$HBP/Models && /home/bbpnrsoa/nrp/src/Models/create-symlinks.sh' 2>&1 | grep -v "HBP-NRP"
  $DOCKER_CMD exec $curr_nrp bash -c "/bin/sed -e 's/localhost:9000/"$external_frontend_ip":9000/' -i /home/bbpnrsoa/nrp/src/ExDBackend/hbp_nrp_commons/hbp_nrp_commons/workspace/Settings.py"
  $DOCKER_CMD exec $curr_nrp bash -c "/bin/sed -e 's/localhost:9000/"$external_frontend_ip":9000/' -i /home/bbpnrsoa/nrp/src/VirtualCoach/hbp_nrp_virtual_coach/hbp_nrp_virtual_coach/config.json"
  $DOCKER_CMD exec $curr_nrp bash -c 'cd $HOME/nrp/src && source $HOME/.opt/platform_venv/bin/activate && pyxbgen -u Experiments/bibi_configuration.xsd -m bibi_api_gen && pyxbgen -u Experiments/ExDConfFile.xsd -m exp_conf_api_gen && pyxbgen -u Models/environment_model_configuration.xsd -m environment_conf_api_gen && pyxbgen -u Models/robot_model_configuration.xsd -m robot_conf_api_gen && deactivate' 2>&1 | grep -v "WARNING"
  $DOCKER_CMD exec $curr_nrp bash -c 'gen_file_path=$HBP/ExDBackend/hbp_nrp_commons/hbp_nrp_commons/generated && filepaths=$HOME/nrp/src && sudo cp $filepaths/bibi_api_gen.py $gen_file_path &&  sudo cp $filepaths/exp_conf_api_gen.py $gen_file_path && sudo cp $filepaths/_sc.py $gen_file_path && sudo cp $filepaths/robot_conf_api_gen.py $gen_file_path && sudo cp $filepaths/environment_conf_api_gen.py $gen_file_path'
  $DOCKER_CMD exec $curr_nrp bash -c "sudo /etc/init.d/supervisor start"
  echo -e "${GREEN}Finished setting up $curr_nrp container.${NC}"
}

setup_frontend() {
  $DOCKER_CMD exec frontend bash -c "/bin/sed -e 's/localhost/"$external_frontend_ip"/' -i /home/bbpnrsoa/nrp/src/ExDFrontend/dist/config.json"
  for ((i=0; i<num_backends; i++))
  do
	curr_ip=${nrp_ips[$i]}
  	$DOCKER_CMD exec frontend bash -c "/bin/sed -e \"s=localhost="$curr_ip"=\" -i /home/bbpnrsoa/nrp/src/nrpBackendProxy/config.json"
  done
  # Remove exit on fail, as if the user exists already we dont care.
  set +e
  $DOCKER_CMD exec frontend bash -c "source /home/bbpnrsoa/nrp/src/user-scripts/nrp_variables 2> /dev/null && /home/bbpnrsoa/nrp/src/user-scripts/add_new_database_storage_user -u nrpuser -p password -s > /dev/null 2>&1"
  set -e
  $DOCKER_CMD exec frontend bash -c "sudo /etc/init.d/supervisor start"
  echo -e "${GREEN}Finished setting up frontend container.${NC}"
}

uninstall(){
  while true; do
    echo -e "${YELLOW}Are you sure you would like to remove the NRP docker images? [y/n] ${NC}"
    read yn
    case $yn in
      [Yy]* ) break;;
      [Nn]* ) exit;;
      * ) echo "Please answer yes or no.";;
    esac
  done
  # Dont fail on errors
  set +e
  echo -e "${BLUE}Removing NRP docker images. This may take a while.${NC}"
  for ((i=0; i<num_backends; i++))
  do
	curr_nrp=${nrp_backends[$i]}
  	$DOCKER_CMD stop $curr_nrp
  	$DOCKER_CMD rm $curr_nrp
  	$DOCKER_CMD rmi $($DOCKER_CMD images | grep -w hbpneurorobotics/nrp | awk '{print $3}')
  	$DOCKER_CMD volume rm $curr_nrp"_models"
  	$DOCKER_CMD volume rm $curr_nrp"_experiments"
  done
  $DOCKER_CMD stop frontend
  $DOCKER_CMD rm frontend
  $DOCKER_CMD volume rm "frontend_models"
  $DOCKER_CMD volume rm "frontend_experiments"
  $DOCKER_CMD network rm nrpnet
  $DOCKER_CMD rmi $($DOCKER_CMD images | grep -w hbpneurorobotics/nrp_frontend | awk '{print $3}')
  echo -e "${GREEN}NRP Docker images have been successfully removed.${NC}"
  set -e
  while true; do
    echo -e "${YELLOW}Would you also like to remove your personal experiments and models? [y/n] ${NC}"
    read yn
    case $yn in
      [Yy]* ) break;;
      [Nn]* ) exit;;
      * ) echo "Please answer yes or no.";;
    esac
  done
  for ((i=0; i<num_backends; i++))
  do
	curr_nrp=${nrp_backends[$i]}
  	$DOCKER_CMD volume rm $curr_nrp"_user_data"
  	echo -e "${BLUE}Removing NRP user data${NC}"
  done
  $DOCKER_CMD volume rm "frontend_user_data"
  echo -e "${GREEN}All traces of the NRP images and user data have been sucessfully removed from your system.${NC}"
}

connect(){
  container=$1
  echo -e "${BLUE}Opening new terminal into $container container${NC}"
  thecmd="bash -c \"echo -e \\\"${RED}You are inside the $container container. Advanced users only.\nCTRL+D to exit.\nIf you mess up everything, you can restore this container\nwith the reset command of the install script.\n${NC}\\\"; $DOCKER_CMD exec -it $container bash\""
  if [ -z ""`which gnome-terminal` ]
  then
    echo -e "${GREEN}No gnome-terminal installed. Defaulting to bash.${NC}"
    bash -c "$thecmd"
  else
    gnome-terminal -e "$thecmd" &
  fi
}

check_port(){
  port=$1
  echo -e "${BLUE}Checking ports${NC}"
  set +e
  is_port=`netstat -tuplen 2>/dev/null | grep $port`
  if [ -n "$is_port" ]
  then
    echo -e "${RED}[ERROR] The port $port is in currently in use. If you would like to install the NRP please find the process using this port and stop it:${NC}"
    echo -e "$is_port"
    exit
  fi
  echo -e "${GREEN}Port $port is available.${NC}"
  set -e

}

version_check() {

   [ -z "$1" -o -z "$2" ] && return 9
   [ "$1" == "$2" ] && return 10

   ver1front=`echo $1 | cut -d "." -f -1`
   ver1back=`echo $1 | cut -d "." -f 2-`

   ver2front=`echo $2 | cut -d "." -f -1`
   ver2back=`echo $2 | cut -d "." -f 2-`

   if [ "$ver1front" != "$1" ] || [ "$ver2front" != "$2" ]; then
       [ "$ver1front" -gt "$ver2front" ] && return 11
       [ "$ver1front" -lt "$ver2front" ] && return 9

       [ "$ver1front" == "$1" ] || [ -z "$ver1back" ] && ver1back=0
       [ "$ver2front" == "$2" ] || [ -z "$ver2back" ] && ver2back=0
       version_check "$ver1back" "$ver2back"
       return $?
   else
           [ "$1" -gt "$2" ] && return 11 || return 9
   fi
}

start_experiments() {
  fast_test=$1
  
  echo -e "${BLUE}Starting Local Learner${NC}"
  if [ ! -e "./Learner/learner.py" ] 
  then
 	echo -e "${RED}[ERROR]learner.py does not exist!${NC}"
 	exit
  fi
  learn_dir=$(readlink -f Learner/learner.py)
  thecmd="bash -c \"echo -e \\\"${BLUE}You are now in a new terminal responsible for the central learner\n${NC}\\\"; python2 $learn_dir\""
  #echo $thecmd
  if [ -z ""`which gnome-terminal` ]
  then
    echo -e "${GREEN}No gnome-terminal installed. Defaulting to bash.${NC}"
    bash -c "$thecmd"
  else
    gnome-terminal -e "$thecmd" &
  fi
  for ((i=0; i<num_backends; i++))
  do
	curr_backend=${nrp_backends[$i]}
	echo $curr_backend
  if [ $fast_test = true ]
  then
    thecmd="bash -c \"echo -e \\\"${BLUE}You are now in a new terminal responsible for the worker $curr_backend\n${NC}\\\"; docker exec -it $curr_backend bash /home/bbpnrsoa/nrp/src/Worker/start.sh --fast_test; read line;\""
  else
    thecmd="bash -c \"echo -e \\\"${BLUE}You are now in a new terminal responsible for the worker $curr_backend\n${NC}\\\"; docker exec -it $curr_backend bash /home/bbpnrsoa/nrp/src/Worker/start.sh; read line;\""
	
  fi
	if [ -z ""`which gnome-terminal` ]
  	then
	    echo -e "${GREEN}No gnome-terminal installed. Defaulting to bash.${NC}"
	    bash -c "$thecmd"
	else
	    gnome-terminal -e "$thecmd" &
	fi
	sleep 4
  done
}


setup_experiments() {
  
  if [ ! -d "./Worker" ] 
  then
  	echo -e "${BLUE}Distributed reinforcement learning experiment files not available!${NC}"
  	exit
  	#git clone --progress https://github.com/koblibri/Worker.git ./Worker
  fi
  echo -e "${BLUE}Copying distributed reinforcment learning experiment files to containers${NC}"
  for ((i=0; i<num_backends; i++))
  do
	curr_backend=${nrp_backends[$i]}
	echo $curr_backend
	$DOCKER_CMD cp ./Worker $curr_backend:/home/bbpnrsoa/nrp/src 
  #Assuming if pytorch is installed in the container, then all the other packages are also there. (Reinstallation)
  $DOCKER_CMD exec $curr_backend bash -c 'python -c "import torch"' || $DOCKER_CMD exec $curr_backend bash -c 'pip install -r /home/bbpnrsoa/nrp/src/Worker/requirements.txt --no-cache-dir'
  #if [[ "$?" -eq 1 ]]
  #then
  #  echo "Installing python packages"
	#  $DOCKER_CMD exec $curr_backend bash -c 'pip install -r /home/bbpnrsoa/nrp/src/Worker/requirements.txt --no-cache-dir'
	#fi
  echo -e "${BLUE}DRL files installed on container $curr_backend ${NC}"
  done
  
  echo -e "${BLUE}Installing local python requirements${NC}"
  pip2 install -r ./Learner/requirements.txt --no-cache-dir
}

#Colours
RED="\033[01;31m"
GREEN="\033[01;32m"
PURPLE="\033[01;35m"
BLUE="\033[01;34m"
YELLOW="\033[01;33m"
NC="\033[00m"
#Fail on errors
set -e

is_mac=false
if grep -qE "(Microsoft|WSL)" /proc/version; then exe=".exe"; 
elif uname -a | grep -q "Darwin"
then
   is_mac=true;
fi
nrp_port="8080"
nrp_image="hbpneurorobotics/nrp:dev"
frontend_port="9000"
frontend_image="hbpneurorobotics/nrp_frontend:dev"
subnet="172.19"
frontend_ip="172.19.0.2"


nrp="nrp"
nrp_name=nrp
nrp_ip="172.19.0."
nrp_base_ip=3

declare -A nrp_backends nrp_ips




##EDIT this line to set the number of parallel nrp-backends/robots
num_backends=0;

if [ $num_backends -lt 1 ]
then
	echo -e "${RED}[ERROR] At least one container has to be installed. Please edit the num_backends in line 435 of this script to a number greater than zero!${NC}"
	exit
fi
nrp_backends[0]="nrp0"
nrp_ips[0]="172.19.0.3"
for ((i=1; i<num_backends; i++))
do
	nrp_backends[$i]=$nrp$i
	#echo "$nrp_backends"
	ip=$((nrp_base_ip+i))
	nrp_ips[$i]=$nrp_ip$ip
done

#nrp_ip="172.19.0.3"
#nrp1_ip="172.19.0.4"
#nrp2_ip="172.19.0.5"
#nrp3_ip="172.19.0.6"
#nrp4_ip="172.19.0.7"
#etc...

#EDIT the IP below to whichever IP you want in your subnet!
nrp_ip="172.19.0.3"

external_frontend_ip=$frontend_ip
external_nrp_ip=$nrp_ip
DOCKER_CMD="docker"$exe
CMD=""
nrp_proxy_ip="http://148.187.97.48"

usage="
Usage: $(basename "$0") COMMAND

A script to install and start the Neurorobotics Platform using docker images.

Options:
    -h                   Show this help text
    -s/--sudo            Use docker with sudo"
if ! $is_mac
then
usage="$usage
    -i/--ip <ip_address> The IP address of the machine the images are installed on.
                         Use this option when you would like to access the NRP outside the machine its installed on."
fi
usage="$usage
Commands:
    restart_backend   Restart the backend container
    restart_frontend  Restart the frontend container
    restart           Restart backend and frontend containers
    update            Update the NRP
    install           Install the NRP
    uninstall         Uninstall the NRP
    stop              Stops the nrp containers
    start             Starts nrp containers which have previously been stopped
    reset_backend     Restores the backend container
    reset_frontend    Restores the frontend container
    reset             Restores the backend and frontend containers
    connect_frontend  Connect to the frontend container (Opens in a new terminal)
    connect_backend   Connect to the backend container (Opens in a new terminal)
    install_drl       Installs all the necessary files for the Distributed Reinforcement Learning Experiment. Can also be used to copy files inside the Worker folder to all containers.
    start_experiment  Starts all experiments
    start_fast_test   Starts all experiments in the fast test variant
    

${BLUE}Please note:${NC}
This script requires that the package 'docker' is already installed
At least 15GB of disk space will be needed in order to install the NRP images${NC}
"

POSITIONAL=()
while [[ $# -gt 0 ]]
do
key="$1"
case $key in
    -h|--help)
      echo -e "$usage"
      exit
    ;;
    -s|--sudo)
      DOCKER_CMD="sudo docker"
      shift
    ;;
    -i|--ip)
      external_frontend_ip="$2"
      external_nrp_ip=$external_frontend_ip
      shift
      shift
    ;;

    restart_backend)
       for ((i=0; i<((num_backends-1));i++))
       do
       	curr_backend=${nrp_backends[$i]}
       	CMD+="restart $curr_backend &&"
       done
       CMD+="restart ${nrp_backends[$(($num_backends-1))]}"
       shift
     ;;
    restart_frontend)
       CMD="restart frontend"
       shift
     ;;
    restart)
       for ((i=0; i<num_backends;i++))
       do
       	curr_backend=${nrp_backends[$i]}
       	CMD+="restart $curr_backend &&" 
       done
       CMD+="restart frontend"
       shift
     ;;
    start)
       for ((i=0; i<num_backends;i++))
       do
       	curr_backend=${nrp_backends[$i]}
       	CMD+="restart $curr_backend &&" 
       done
       CMD+="restart frontend"
       shift
     ;;
    update)
      set +e && curl -X POST ${nrp_proxy_ip}/proxy/activity_log/update --max-time 10; set -e # logs each update event via the NRP proxy server
      
      CMD="pull_images"
      shift
    ;;
    install)
      set +e && curl -X POST ${nrp_proxy_ip}/proxy/activity_log/install --max-time 10; set -e # logs each install event via the NRP proxy server
      CMD="pull_images"
      shift
    ;;
    uninstall)
      CMD="uninstall"
      shift
    ;;
    stop)
      for ((i=0; i<num_backends;i++))
       do
       	curr_backend=${nrp_backends[$i]}
       	CMD+="stop $curr_backend &&" 
       done
       CMD+="stop frontend"
      shift
    ;;
    reset_backend)
      for ((i=0; i<((num_backends-1));i++))
       do
       	curr_backend=${nrp_backends[$i]}
       	CMD+="restore $curr_backend &&"
       done
       CMD+="restore ${nrp_backends[$(($num_backends-1))]}"
      shift
    ;;
    reset_frontend)
      CMD="restore frontend"
      shift
    ;;
    reset)
       for ((i=0; i<num_backends;i++))
       do
       	curr_backend=${nrp_backends[$i]}
       	CMD+="restore $curr_backend &&" 
       done
       CMD+="restore frontend"
       shift
     ;;
    connect_backend)
      CMD="connect nrp0"
      shift
    ;;
    connect_frontend)
      CMD="connect frontend"
      shift
    ;;
    install_drl)
      CMD="setup_experiments"
      shift
    ;;
    start_experiment)
      CMD="start_experiments false"
      shift
    ;;
    start_fast_test)
      echo -e "${BLUE}Fast test is enabled!${NC}"
      CMD="start_experiments true"
      shift
    ;;  	
    *)
     echo "Unknown option \"$key\""
     echo -e "$usage"
     exit
     ;;
esac
done

if [ -z "$CMD" ]
then
  echo -e "${RED}[ERROR] Please provide a command to execute${NC}"
  echo ""
  echo -e "$usage"
  exit
fi

eval $CMD
# Reset terminal colour back to normal
echo -e "${NC}"
