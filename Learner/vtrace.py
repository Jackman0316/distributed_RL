from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import torch
import torch.nn.functional as F


def log_probs_from_logits_and_actions(policy_logits, actions):
    """
    Computes action log-probs from policy logits and actions.
    """

    num_actions = 12
    assert len(policy_logits.shape) == 3
    assert len(actions.shape) == 2

    # this permute is because: in pytorch cross_entropy loss must have classes in dim 1,
    # while in tensorflow tf.nn.sparse_softmax_cross_entropy_with_logits could have classes in last dim
    # permute it to (seq_len, #num_action, batch)
    policy_logits = policy_logits.permute(0, 2, 1)

    return -F.cross_entropy(policy_logits, actions, reduction='none')


def from_logits(behaviour_policy_logits, target_policy_logits, actions,
                discounts, rewards, values, bootstrap_value,
                clip_rho_threshold=1.0, clip_pg_rho_threshold=1.0):
    """
    Calculates V-trace actor critic targets for softmax polices as described in

    "IMPALA: Scalable Distributed Deep-RL with
    Importance Weighted Actor-Learner Architectures"
    by Espeholt, Soyer, Munos et al.

    Target policy refers to the policy we are interested in improving and
    behaviour policy refers to the policy that generated the given
    rewards and actions.
    """
    # Make sure tensor ranks are as expected.
    # The rest will be checked by from_action_log_probs.
    assert len(behaviour_policy_logits.shape) == 3
    assert len(target_policy_logits.shape) == 3
    assert len(actions.shape) == 2

    target_action_log_probs = log_probs_from_logits_and_actions(target_policy_logits, actions)
    behaviour_action_log_probs = log_probs_from_logits_and_actions(behaviour_policy_logits, actions)

    log_rhos = target_action_log_probs - behaviour_action_log_probs  # log importance sampling weight

    vs, pg_advantages = from_importance_weights(
        log_rhos=log_rhos,
        discounts=discounts,
        rewards=rewards,
        values=values,
        bootstrap_value=bootstrap_value,
        clip_rho_threshold=clip_rho_threshold,
        clip_pg_rho_threshold=clip_pg_rho_threshold)
    return vs, pg_advantages


def from_importance_weights(
        log_rhos, discounts, rewards, values, bootstrap_value,
        clip_rho_threshold=1.0, clip_pg_rho_threshold=1.0):
    """
        Calculates V-trace actor critic targets
    """
    if clip_rho_threshold is not None:
        clip_rho_threshold = torch.tensor(clip_rho_threshold, dtype=torch.float32, device=log_rhos.device)
    if clip_pg_rho_threshold is not None:
        clip_pg_rho_threshold = torch.tensor(clip_pg_rho_threshold, dtype=torch.float32, device=log_rhos.device)

    # Make sure tensor ranks are consistent.
    rho_rank = len(log_rhos.shape)  # Usually 2.
    assert len(values.shape) == rho_rank
    assert len(bootstrap_value.shape) == rho_rank - 1
    assert len(discounts.shape) == rho_rank
    assert len(rewards.shape) == rho_rank

    if clip_rho_threshold is not None:
        assert len(clip_rho_threshold.shape) == 0
    if clip_pg_rho_threshold is not None:
        assert len(clip_pg_rho_threshold.shape) == 0

    with torch.no_grad():  # Make sure no gradients backpropagated through vtrace.

        rhos = torch.exp(log_rhos)  # importance sampling weight

        if clip_rho_threshold is not None:
            clipped_rhos = torch.min(clip_rho_threshold, rhos)
        else:
            clipped_rhos = rhos

        cs = torch.min(torch.ones(rhos.shape), rhos)  # truncated importance sampling weights

        # Append bootstrapped value to get [v1, ..., v_t+1]
        values_t_plus_1 = torch.cat((values[1:], bootstrap_value.unsqueeze(0)), dim=0)

        deltas = clipped_rhos * (rewards + discounts * values_t_plus_1 - values)  # weighted temporal difference
        initial_values = torch.zeros_like(bootstrap_value)

        acc = initial_values
        eq_out = []
        seq_len = discounts.shape[0]
        for i in range(seq_len - 1, -1, -1):  # Vtrace's Sigma, computing starts from the back.
            # print(i)
            discount_t, c_t, delta_t = discounts[i], cs[i], deltas[i]
            acc = delta_t + discount_t * c_t * acc
            eq_out.insert(0, acc)
        eq_out = torch.stack(eq_out, 0)
        vs_minus_v_xs = eq_out

        vs = torch.add(vs_minus_v_xs, values)

        # Advantage for policy gradient.
        vs_t_plus_1 = torch.cat((vs[1:], bootstrap_value.unsqueeze(0)), dim=0)

        if clip_pg_rho_threshold is not None:
            clipped_pg_rhos = torch.min(clip_pg_rho_threshold, rhos)
        else:
            clipped_pg_rhos = rhos

        # pg_advantages: for policy evaluation in policy gradient loss.
        # To make sure estimation is unbiased, not using vs, proved in IMPALA paper
        pg_advantages = clipped_pg_rhos * (rewards + discounts * vs_t_plus_1 - values)

        # Make sure no gradients backpropagated through the returned values.
        return vs.detach(), pg_advantages.detach()
