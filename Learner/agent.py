import torch
import torch.nn as nn
import torch.nn.functional as F


class Agent(nn.Module):

    def __init__(self, num_actions=12, input_size=12, fc_size=512, lstm_hidden=256, isactor=False):
        super(Agent, self).__init__()
        self.num_actions = num_actions
        self.input_size = input_size
        self.fc_size = fc_size
        self.lstm_hidden = lstm_hidden
        self.l1 = nn.Linear(input_size, 128)
        self.l2 = nn.Linear(128, 256)
        # FC layers output size: 499, for future concatenated with one-hot encoding actions and reward, 499+12+1=512
        self.l3 = nn.Linear(256, fc_size - self.num_actions - 1)

        self.lstm = nn.LSTMCell(fc_size, lstm_hidden)

        self.head = Head(num_actions)
        self.isactor = isactor

    def forward(self, x, action, reward, dones=None, core_state=None, batch_size=1, isactor=False):

        # computing hidden representation for state information
        x = F.leaky_relu(self.l1(x))
        x = F.leaky_relu(self.l2(x))
        x = F.leaky_relu(self.l3(x))

        if isactor:
            seq_len = 1
            batch_size = 1
        else:
            seq_len = x.shape[0]
            batch_size = x.shape[1]

        x = x.view(seq_len, batch_size, -1)  # just in case, actually not resized
        action = F.one_hot(action.long(), num_classes=self.num_actions)
        action = action.view(seq_len, batch_size, -1).to(torch.float32)
        reward = reward.view(seq_len, batch_size, -1)

        x = torch.cat((x, action, reward), dim=2)  # concatenate state, action and reward, feed into LSTM

        hx = None
        cx = None

        if core_state is None:
            hx = torch.zeros((batch_size, self.lstm_hidden))
            cx = torch.zeros((batch_size, self.lstm_hidden))
        else:
            hx = core_state[0]
            cx = core_state[1]

        lstm_out = []

        for i in range(seq_len):
            if dones is not None:
                # if dones_t is True, cut the connection with previous hidden state
                hx = torch.where(dones[i].view(-1, 1), torch.zeros((batch_size, self.lstm_hidden)), hx)
                cx = torch.where(dones[i].view(-1, 1), torch.zeros((batch_size, self.lstm_hidden)), cx)
            hx, cx = self.lstm(x[i], (hx, cx))
            lstm_out.append(hx)
            core_state = torch.stack([hx, cx], 0)  # core_state which will be passing in a trajectory

        x = torch.cat(lstm_out, 0)  # concatenate lstm output and feed into Head (output layers of model)

        new_action, policy_logits, baseline = self.head(x)

        if isactor:
            # output of an actor: new_action, behavior_logits, and lstm core_state
            # core_state which will be passing in a trajectory
            return new_action, policy_logits.view(1, -1), core_state
        else:
            # output of the learner: target_logits, and baseline
            return policy_logits.view(batch_size, seq_len, -1), baseline.view(batch_size, seq_len)


class Head(nn.Module):
    def __init__(self, num_actions):
        super(Head, self).__init__()
        self.actor_linear = nn.Linear(256, num_actions)  # for policy output
        self.critic_linear = nn.Linear(256, 1)  # for baseline output

    def forward(self, x):
        policy_logits = self.actor_linear(x)
        baseline = self.critic_linear(x)
        prob_weights = F.softmax(policy_logits, dim=1).clamp(1e-10, 1)  # clamped, in case error in torch.multinomial

        new_action = torch.multinomial(prob_weights, 1, replacement=True)  # new action sampled from prob_weights
        return new_action, policy_logits, baseline


class MyLoss(nn.Module):
    def __init__(self):
        super(MyLoss, self).__init__()
        self.num_actions = 12

    def compute_baseline_loss(self, vs, baseline):
        # Loss for the baseline, summed over the time dimension.
        # Multiply by 0.5 to match the standard update rule:
        advaranges = vs - baseline
        return 0.5 * torch.sum(advaranges**2)

    def compute_entropy_loss(self, logits):
        # entropy regularization
        policy = F.softmax(logits, dim=2)
        log_policy = F.log_softmax(logits, dim=2)
        entropy_per_timestep = torch.sum(-policy * log_policy, dim=-1)
        return -torch.sum(entropy_per_timestep)

    def compute_policy_gradient_loss(self, logits, actions, advantages):

        # this permute is because: in pytorch cross_entropy loss must have classes in dim 1,
        # while in tensorflow tf.nn.sparse_softmax_cross_entropy_with_logits could have classes in last dim
        logits = logits.permute(0, 2, 1)

        cross_entropy = F.cross_entropy(logits, actions, reduction='none')

        advantages = advantages.requires_grad_(False)
        policy_gradient_loss_per_timestep = cross_entropy * advantages
        return torch.sum(policy_gradient_loss_per_timestep)


