import agent
from agent import Agent

import vtrace

# # for comparing the paper with our implementation
# import vtrace_tf
# import tensorflow as tf

import pickle
import random
from collections import namedtuple
import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
import os
from socketserver import Message as sockMessage
import socket
import traceback
import threading
import time
try:
    import selectors
except ImportError:
    import selectors2 as selectors  # run  python -m pip install selectors2

host = '172.19.0.1'
port = 65432
sel = selectors.DefaultSelector()


device = torch.device('cuda')

# trajectory data structure
Transition = namedtuple('Transition', ('state', 'action', 'reward', 'done', 'logits'))


class ReplayMemory(object):

    def __init__(self, capacity):
        self.capacity = capacity
        self.memory = []
        self.position = 0

    def push(self, *args):
        """push a trajectory into memory"""
        if len(self.memory) < self.capacity:
            self.memory.append(None)
        self.memory[self.position] = Transition(*args)
        self.position = (self.position + 1) % self.capacity

    def sample(self, batch_size=16):
        """
        :param batch_size:
        :return: batch of trajectory, default batch_size = 16
        """
        if self.position == 0:
            print('error: empty memory when sampling')
            return []
        if self.position <= batch_size:
            return self.memory
        else:
            return self.memory[-batch_size:]

    def __len__(self):
        return len(self.memory)


class Learner():

    def __init__(self, lr=0.0001, mem_capacity=10000, num_actions=12):
        self.lr = lr
        self.agent = Agent(num_actions=num_actions)
        self.replay_memory = ReplayMemory(mem_capacity)
        self.optimizer = optim.RMSprop(self.agent.parameters(), self.lr)
        self.loss_dict = []
        self.state_dict = self.agent.state_dict()

        self.gamma = 0.99  # Discounting factor for vtrace computation
        self.baseline_cost = 0.5  # baseline loss discount factor
        self.entropy_cost = 0.00025  # entropy loss discount factor

    def accept_wrapper(self, sock):
        conn, addr = sock.accept()  # Should be ready to read
        print("accepted connection from", addr)
        conn.setblocking(True)
        message = sockMessage(sel, conn, addr, self.send_parameters())
        sel.register(conn, selectors.EVENT_READ, data=message)

    def socket_init(self):
        lsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Avoid bind() exception: OSError: [Errno 48] Address already in use
        lsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        lsock.bind((host, port))
        lsock.listen(5)
        print("listening on", (host, port))
        lsock.setblocking(False)
        sel.register(lsock, selectors.EVENT_READ, data=None)
        try:
            while True:
                events = sel.select(timeout=None)
                for key, mask in events:
                    if key.data is None:
                        self.accept_wrapper(key.fileobj)
                    else:
                        message = key.data
                        try:
                            exp = message.process_events(mask)
                            if exp != None:
                                self.receive_exp(exp)
                        except Exception:
                            print(
                                "main: error: exception for %s\n %s"
                                % (message.addr, traceback.format_exc))
                            traceback.print_exc()
                            message.close()
        except KeyboardInterrupt:
            print("caught keyboard interrupt, exiting")
        finally:
            sel.close()

    def send_parameters(self):
        # socket send parameters back to worker
        # when receive newest parameter request, call this
        # return pickle.dumps(self.agent.state_dict())
        return pickle.dumps(self.state_dict)

    def receive_exp(self, data):
        encoded_data = pickle.loads(data)

        # each step stored as Transition = namedtuple('Transition', ('state', 'action', 'reward', 'done', 'logits'))
        # extract each element and stack them to create a trajectory
        state_list = []
        action_list = []
        reward_list = []
        done_list = []
        logits_list = []
        for exp in encoded_data:
            state_list.append(exp['state'])
            action_list.append(exp['action'])
            reward_list.append(exp['reward'])
            done_list.append(exp['done'])
            logits_list.append(exp['logits'])

        state_trajectory = torch.stack(state_list, 0)
        action_trajectory = torch.stack(action_list, 0)
        reward_trajectory = torch.stack(reward_list, 0)
        done_trajectory = torch.stack(done_list, 0)
        logits_trajectory = torch.stack(logits_list, 0)

        # push trajectory into memory
        self.replay_memory.push(state_trajectory, action_trajectory, reward_trajectory, done_trajectory, logits_trajectory)

        print ("Got new stuff with len: ", len(data))

        '''
            Start to train. Here we don't make learner keep training all the time, because the workers are way too slow, 
        and running multiple workers needs much computer resources. We don't want old trajectories overwhelming the 
        gradient update.
        '''
        for i in range(3):
            self.training_process()
        self.state_dict = self.agent.state_dict()
        torch.save(self.agent.state_dict(), 'params.pkl')

        # loss in RL is not like loss in traditional ML,
        # the value of loss in RL only means the amplitude of update and direction (award or punishment).
        print(self.loss_dict)

    def training_process(self):

        # sample a batch of trajectories from memory and stack them, default batch_size=16
        # dim of trajectories: (batch, seq_len, -1)
        transitions = self.replay_memory.sample()
        batch = Transition(*zip(*transitions))
        state_batch = torch.stack(batch.state, dim=0)
        action_batch = torch.stack(batch.action, dim=0)
        reward_batch = torch.stack(batch.reward, dim=0)
        done_batch = torch.stack(batch.done, dim=0)
        behavior_logits_batch = torch.stack(batch.logits, dim=0)

        # make time major, dim of trajectories: (seq_len, batch, -1), for further computation
        state_batch = torch.transpose(state_batch, 0, 1)
        action_batch = torch.transpose(action_batch, 0, 1)
        reward_batch = torch.transpose(reward_batch, 0, 1)
        done_batch = torch.transpose(done_batch, 0, 1)
        if len(behavior_logits_batch.shape) == 4:
            # in case logits in (batch, seq_len, 1, #num_action), squeeze then permute it to (seq, batch, #num_action)
            behavior_logits_batch = behavior_logits_batch.squeeze(2)
        behavior_logits_batch = behavior_logits_batch.permute(1, 0, 2)

        # feed in to neural network, get learner output
        target_logits, baseline = self.agent(x=state_batch, action=action_batch, reward=reward_batch, dones=done_batch, core_state=None, isactor=False)

        # make time major of learner output
        target_logits = target_logits.permute(1, 0, 2)
        baseline = torch.transpose(baseline, 0, 1)

        # Use last baseline value (from the baseline function) to bootstrap.
        bootstrap_value = baseline[-1]

        # At this point, the environment outputs at time step `t` are the inputs that
        # lead to the learner_outputs at time step `t`. After the following shifting,
        # the actions in agent_outputs and learner_outputs at time step `t` is what
        # leads to the environment outputs at time step `t`.
        actions, behaviour_logits, rewards, dones = action_batch.view(action_batch.shape[0], -1).type(torch.long)[1:], behavior_logits_batch[1:], \
                                                    reward_batch.view(reward_batch.shape[0], -1)[1:], done_batch.view(done_batch.shape[0], -1)[1:]

        target_logits, baseline = target_logits[:-1], baseline[:-1]

        discounts = (~dones).float() * self.gamma

        vs, pg_advantages = vtrace.from_logits(
            behaviour_policy_logits=behaviour_logits,
            target_policy_logits=target_logits,
            actions=actions,
            discounts=discounts,
            rewards=rewards,
            values=baseline,
            bootstrap_value=bootstrap_value)

        self.optimizer.zero_grad()

        criterion = agent.MyLoss()
        loss = criterion.compute_policy_gradient_loss(target_logits, actions, pg_advantages)  # policy_gradient_loss
        loss += self.baseline_cost * criterion.compute_baseline_loss(vs=vs, baseline=baseline)  # baseline_loss
        loss += self.entropy_cost * criterion.compute_entropy_loss(target_logits)  # entropy regularization

        # loss in RL is not like loss in traditional ML,
        # the value of loss in RL only means the amplitude of update and direction (award or punishment).

        '''
        For comparing vtrace and loss in the IMPALA paper with our implementation
        '''
        # vtrace_tf.from_logits(
        #     behaviour_policy_logits=tf.convert_to_tensor(behaviour_logits.detach().numpy()),
        #     target_policy_logits=tf.convert_to_tensor(target_logits.detach().numpy()),
        #     actions=tf.convert_to_tensor(actions.int().detach().numpy()),
        #     discounts=tf.convert_to_tensor(discounts.detach().numpy()),
        #     rewards=tf.convert_to_tensor(rewards.detach().numpy()),
        #     values1=tf.convert_to_tensor(baseline.detach().numpy()),
        #     bootstrap_value=tf.convert_to_tensor(bootstrap_value.detach().numpy()))
        # # tf vs, tf pg_advantages will be printed in vtrace_tf.py
        # print('torch vs', vs)
        # print('torch pg_advantages', pg_advantages)

        # tf_loss = vtrace_tf.compute_policy_gradient_loss(tf.convert_to_tensor(target_logits.detach().numpy()),
        #                                                      tf.convert_to_tensor(actions.detach().numpy()),
        #                                                     tf.convert_to_tensor(pg_advantages.detach().numpy())) \
        #     + self.baseline_cost * vtrace_tf.compute_baseline_loss(tf.convert_to_tensor(vs.detach().numpy()),
        #                                                            tf.convert_to_tensor(baseline.detach().numpy())) \
        #     + self.entropy_cost * vtrace_tf.compute_entropy_loss(tf.convert_to_tensor(target_logits.detach().numpy()))
        # print('torch loss', loss)
        # print('tf loss', tf_loss)

        loss.backward()
        self.optimizer.step()
        self.loss_dict.append(loss.item())

        return


# Does the main work here?
def learner_func():
    while True:
        time.sleep(1)


x = threading.Thread(target=learner_func, args=())


learner = Learner()
if os.path.exists('params.pkl'):
    learner.agent.load_state_dict(torch.load('params.pkl'))

if __name__ == "__main__":

    learner.socket_init()




