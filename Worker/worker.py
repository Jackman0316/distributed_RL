import argparse
import pickle
import time
import experiment_api
import agent
from agent import Agent

import random
import numpy as np
from collections import namedtuple
from itertools import count

import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F

import random

from argutils import str2bool

from socketclient import Message as sockMessage
import traceback
import socket
try:
    import selectors
except ImportError:
    import selectors2 as selectors  # run  python -m pip install selectors2
sel = selectors.DefaultSelector()
host = '172.19.0.1'
port = 65432


# if gpu is to be used
device = torch.device('cuda')

Transition = namedtuple(
    'Transition', ('state', 'action', 'reward', 'done', 'logits'))

fast_test = False


class ReplayMemory(object):

    def __init__(self, capacity):
        self.capacity = capacity
        self.memory = []
        self.position = 0

    def push(self, *args):
        """saves a transition"""
        if len(self.memory) < self.capacity:
            self.memory.append(None)
        self.memory[self.position] = Transition(*args)
        #self.memory[self.position] = transition_dict
        self.position = (self.position + 1) % self.capacity

    def sample(self, batch_size=16):
        if self.position == 0:
            print('error: empty memory when sampling')
            return []
        if self.position <= batch_size:
            return self.memory
        else:
            return self.memory[-batch_size:]

    def clear(self):
        self.memory = []
        self.position = 0

    def __len__(self):
        return len(self.memory)


class Worker():

    def __init__(self, fast_test=False, mem_size=10000, num_actions=12, discount_factor=0.8, num_episodes=20, num_steps=20):
        self.replay_memory = ReplayMemory(mem_size)
        # now num_action is 12, because each joint has two direction!
        self.agent = Agent(isactor=True)
        self.discount_factor = discount_factor
        self.robot = experiment_api.Robot()
        self.num_actions = num_actions
        self.fast_test = fast_test
        self.num_episodes = num_episodes
        self.num_steps = num_steps
        time.sleep(5)

    def create_request(self, action, value):
        if action == "pull":
            return dict(
                type="binary/pull",
                encoding="binary",
                content=None,
            )
        else:
            return dict(
                type="binary/push",
                encoding="binary",
                content=bytes(value),
            )

    def start_connection(self, host, port, request):
        addr = (host, port)
        print("starting connection to", addr)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setblocking(False)
        sock.connect_ex(addr)
        events = selectors.EVENT_READ | selectors.EVENT_WRITE
        message = sockMessage(sel, sock, addr, request)
        sel.register(sock, events, data=message)

    def wait_response(self):
        try:
            while True:
                events = sel.select(timeout=1)
                for key, mask in events:
                    message = key.data
                    try:
                        parameters = message.process_events(mask)
                        if parameters != None:
                            self.received_parameters(parameters)
                    except Exception:
                        print(
                            "main: error: exception for %s \n %s"
                            % (message.addr, traceback.format_exc())
                        )
                        message.close()
                # Check for a socket being monitored to continue.
                if not sel.get_map():
                    break
        finally:
            pass
        #     sel.close()

    def pull_parameters(self):
        # print('pull params request')
        request = self.create_request("pull", None)
        self.start_connection(host, port, request)
        # socket get learner side .state_dict()
        self.wait_response()

    def received_parameters(self, data):

        new_state_dict = pickle.loads(data)
        # print(new_state_dict)
        self.agent.load_state_dict(new_state_dict)

    def send_exp(self):  # socket send experience to learner
        # self.update_reward()
        experiences = self.replay_memory.memory
        send_exp = map(lambda x: x._asdict(), experiences)
        serialized_exp = pickle.dumps(send_exp)
        request = self.create_request("push", serialized_exp)
        self.start_connection(host, port, request)
        self.wait_response()
        self.replay_memory.clear()
        return

    def check_stable_state(self, init_state=None):  # check done, roll&drop.
        """checks if the object state and the robot state changed in the last 0.1 seconds
        :return: True, if state did not change, False otherwise
        :rtype: bool
        """
        eps = 0.001
        _, object_old_state, robot_old_state = self.robot.get_current_state()
        time.sleep(0.5)
        _, object_new_state, robot_new_state = self.robot.get_current_state()
        new_state = self.robot.get_current_state()

        distance_object = self.get_distance(object_old_state, object_new_state)
        distance_endeffector = self.get_distance(
            robot_old_state, robot_new_state)

        # if distance < threashold: stable state
        if distance_object < eps and distance_endeffector < eps:
            return True
        if (init_state is not None) and self.check_done(new_state, init_state):
            return True
        return False

    def get_position(self, state):
        """gets position of a state pose in a np.array

        :param state: pose of a state
        :type state: geometry_msgs.msg._Pose.Pose
        :return: x,y,z state position in np.array
        :rtype: np.array(Float, Float, Float)
        """
        x = state.position.x
        y = state.position.y
        z = state.position.z
        return np.array((x, y, z))

    def get_distance(self, state_1, state_2):
        postion_1 = self.get_position(state_1)
        postion_2 = self.get_position(state_2)
        return np.linalg.norm(
            postion_1 - postion_2)

    def compute_reward(self, old_state, new_state, init_state):
        """computes the reward for an actio nold_state -> new_state

        :param old_state: robot state before action
        :type old_state: ( _ ,geometry_msgs.msg._Pose.Pose)
        :param new_state: robot state after action
        :type new_state: ( _ ,geometry_msgs.msg._Pose.Pose)
        :param init_state: initial robot state
        :type init_state: ( _ ,geometry_msgs.msg._Pose.Pose)
        :return: reward for this action
        :rtype: int
        """
        _, init_object, _ = init_state
        _, object_new, endeffector_new = new_state
        _, object_old, endeffector_old = old_state

        distance_real = self.get_distance(object_new, endeffector_new)
        distance_change_object = self.get_distance(object_old, object_new)

        z_init = init_object.position.z
        z_new = object_new.position.z
        # check if blue object fell from the table
        eps = 0.01
        if z_new + eps < z_init:
            return 1

        # check if blue object was moved
        if(distance_change_object > eps):
            return 0.8

        print("Distance", distance_real)
        if distance_real >= 1.15:
            return -distance_real/15
        else:
            return 0.4 / (1 + distance_real)

    def select_strategy(self, strategy_threshold):
        """ select strategy (explore or exploit) for a given threshold

        :param strategy_threshold: probability threshold
        :type strategy_threshold: int
        :return: strategy (explore or exploit) for the next round
        :rtype: String
        """
        prob = random.uniform(0, 1)
        strategy = 'exploit'
        if prob < strategy_threshold:
            strategy = 'explore'
        return strategy

    def check_done(self, new_state, init_state, actions_counter=None):
        """check, if robot is done (blue object fell from the table)

        :param new_state: robot state after action
        :type new_state:  ( _ ,geometry_msgs.msg._Pose.Pose)
        :param init_state: initial robot state
        :type init_state: ( _ ,geometry_msgs.msg._Pose.Pose)
        :return: true, if object has fallen, else false
        :rtype: bool
        """

        if((new_state[1].position.z + 0.1) < init_state[1].position.z):
            return True
        elif (actions_counter is not None) and actions_counter >= self.num_steps-2:
            print('20 steps done, game over')
            return True
        else:
            return False

    def update_reward(self):
        """updates reward with discounted rewards
        of the following actions in the end of every episode
        """
        reward = 0
        factor = 0
        reward_final = self.replay_memory.memory[-1].reward
        if reward_final >= 19:
            factor = 1
        for idx, transition in enumerate(self.replay_memory.memory[::-1]):
            reward_final = self.discount_factor * reward_final
            reward = transition.reward + factor * reward_final
            print(reward)
            self.replay_memory.memory[-(idx+1)] = Transition(
                transition.state, transition.action, reward)

    def transfer_action(self, current_joint_state, action):
        """ transfer action from {0-11} to {-6,...,-1, 1,...,6},
            where +6: joint6 +1, -6: joint6 -1,
                    +5: joint5 +1, -5: joint5 -1,
                    +4: joint4 +1, -4: joint4 -1,
                    +3: joint3 +1, -3: joint3 -1,
                    +2: joint2 +1, -2: joint2 -1,
                    +1: joint1 +1, -1: joint1 -1,
        :param current_joint_state: robot current joint values
                type: list, e.g.: [1,-2,0,0,0,0]
        :param action: selected action of this step
                type: int,  e.g.: 9 or 4
        :return: new_joint_state, the new robot joint values, after transferred to j1,j2,j3..., can be used in robot.act()
        :rtype: list
        """
        action -= 5
        if action <= 0:
            action -= 1
        print('transferred action:', action)
        act_joint_num = np.abs(action) - 1
        current_joint_state[int(act_joint_num)] += np.sign(action)
        new_joint_state = current_joint_state
        return new_joint_state

    def choose_action_with_fast_test(self, test_number):
        """chooses the action and generates the new joint position and the new test_number

        :param test_number: current test iteration
        :type test_number: Int
        :return: new joint state, action, new test number
        :rtype: [Int], Int, Int
        """
        if(test_number == 1):
            return [0, -1, 0, 0, 0, 0], 2, 4
        elif (test_number == 2):
            return [0, -2, 0, 0, 0, 0], 3, 4
        elif (test_number == 3):
            self.fast_test = False
            return [-1, -2, 0, 0, 0, 0], 0, 5

    def get_strategy_threshhold(self, episode):
        """gets the strategy threshhold for a given episode

        :param episode: current episode
        :type episode: Int
        :return: strategy_threshhold
        :rtype: Double
        """
        if self.fast_test:
            return 0.0
        else:
            return 1 - (float(episode) / self.num_episodes)

    def get_list_state(self, bare_state):
        """returns the bare_state in a list state

        :param bare_state tuple of (current position robot hand, current position object, current joint states)
        :type tuple
        :return: bare_state as a list
        :rtype: list
        """
        return list(bare_state[0]) + [bare_state[1].position.x, bare_state[1].position.y, bare_state[1].position.z] +\
            [bare_state[2].position.x, bare_state[2].position.y,
                bare_state[2].position.z]

    def set_init_worker(self, bare_state, tensor_state):
        """sets the inital worker configuration

        :return: tuple of init states, action and reward
        :rtype: tuple
        """
        init_action = torch.zeros((1, 1), dtype=torch.float32)
        init_reward = torch.tensor(0, dtype=torch.float32).view(1, 1)
        init_logits = torch.zeros((1, self.num_actions), dtype=torch.float32)
        init_core_state = None
        init_done = torch.tensor(True, dtype=torch.bool).view(1, 1)
        init_worker = (bare_state, tensor_state, init_action,
                       init_reward, init_done, init_logits, init_core_state)
        print(type(init_worker))
        return init_worker

    def run(self):
        """executes num_episodes rounds of attempt of the task
        """

        self.robot.reset()
        time.sleep(2)

        # TODO: here we could randomize initial state (in episodes)
        bare_state = self.robot.get_current_state()
        list_state = self.get_list_state(bare_state)
        tensor_state = torch.Tensor(list_state)

        init_worker = self.set_init_worker(bare_state, tensor_state)

        if self.fast_test is True:
            test_number = 1

        for i in range(self.num_episodes):
            self.robot.reset()
            time.sleep(2)

            # TODO: here we could randomize initial state
            bare_state, tensor_state, action, reward, done, logits, core_state = init_worker
            init_state = bare_state
            while (not self.check_stable_state(init_state)):
                time.sleep(1)
            self.robot.reset_object()
            bare_state = init_state

            self.pull_parameters()
            print('episode: ', i)

            # push init states, to make learner&worker start from the same init settings
            self.replay_memory.push(
                tensor_state, action, reward, done, logits.detach())

            if self.replay_memory.position >= self.num_steps:
                self.send_exp()  # after #num_steps steps, send the trajectory

            for actions_counter in count():  # number of actions

                # object state has to be transferred at here,
                # otherwise in Learner, we cannot parse state by state.position

                new_joint_state = []
                strategy_threshold = self.get_strategy_threshhold(i)
                strategy = self.select_strategy(strategy_threshold)

                if self.fast_test:
                    new_joint_state, test_number, action = self.choose_action_with_fast_test(
                        test_number)
                    print("Strategy", "fast-test-round")

                else:
                    action, logits, core_state = self.agent(
                        x=tensor_state, action=action, reward=reward, dones=None, core_state=core_state, isactor=True)
                    action = action.item()
                    print("Strategy", strategy)

                    if strategy == 'explore':
                        action = random.randint(0, 11)

                    current_joint_state = list(bare_state[0])
                    new_joint_state = self.transfer_action(
                        current_joint_state, action)

                self.robot.act(*new_joint_state)

                # sleep wait for this action finished
                time.sleep(1)
                while not self.check_stable_state(init_state):
                    time.sleep(0.5)

                new_state = self.robot.get_current_state()
                reward = self.compute_reward(bare_state, new_state, init_state)
                print('reward:', reward)

                action = torch.Tensor([action]).view(1, 1)
                reward = torch.Tensor([reward]).view(1, 1)

                bare_state = new_state

                list_state = self.get_list_state(bare_state)
                tensor_state = torch.Tensor(list_state)

                done = self.check_done(new_state, init_state, actions_counter)

                # here we push False as done, because we pushed a True done at init_state
                self.replay_memory.push(tensor_state, action, reward, torch.tensor(
                    False, dtype=torch.bool).view(1, 1), logits.detach())

                if self.replay_memory.position >= self.num_steps:
                    self.send_exp()  # after #num_steps steps, send the trajectory

                if done:
                    # self.send_exp()
                    break

            # self.send_exp()  # one game over, send the experience
            print('number of actions in this round game:', actions_counter + 2)
        print(self.num_episodes, ' training over')
        sel.close()  # cleanup the selector as every experiences are sent


parser = argparse.ArgumentParser(description='Process some integers.')
parser.add_argument('--fast_test', default=False, type=str2bool, dest='fast_test',
                    help='whether to use fast_test or not')
args = parser.parse_args()

worker = Worker(fast_test=args.fast_test)
worker.run()
