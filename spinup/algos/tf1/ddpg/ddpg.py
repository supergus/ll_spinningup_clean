import numpy as np
import tensorflow as tf
import gym
import time
from spinup.algos.tf1.ddpg import core
from spinup.algos.tf1.ddpg.core import get_vars
from spinup.utils.logx import EpochLogger
from spinup.utils.logx import colorize
import copy


class ReplayBuffer:
    """
    A simple FIFO experience replay buffer for DDPG agents.
    """

    def __init__(self, obs_dim, act_dim, size):
        self.raw_outs_buf = np.zeros([size, obs_dim], dtype=np.float32)
        self.obs1_buf = np.zeros([size, obs_dim], dtype=np.float32)
        self.obs2_buf = np.zeros([size, obs_dim], dtype=np.float32)
        self.acts_buf = np.zeros([size, act_dim], dtype=np.float32)
        self.rews_buf = np.zeros(size, dtype=np.float32)
        self.done_buf = np.zeros(size, dtype=np.float32)
        self.ptr, self.size, self.max_size = 0, 0, size

    def store(self, raw, obs, act, rew, next_obs, done):
        self.raw_outs_buf[self.ptr] = raw
        self.obs1_buf[self.ptr] = obs
        self.obs2_buf[self.ptr] = next_obs
        self.acts_buf[self.ptr] = act
        self.rews_buf[self.ptr] = rew
        self.done_buf[self.ptr] = done
        self.ptr = (self.ptr + 1) % self.max_size
        self.size = min(self.size + 1, self.max_size)

    def sample_batch(self, batch_size=32):
        idxs = np.random.randint(0, self.size, size=batch_size)
        return dict(raw=self.raw_outs_buf[idxs],
                    obs1=self.obs1_buf[idxs],
                    obs2=self.obs2_buf[idxs],
                    acts=self.acts_buf[idxs],
                    rews=self.rews_buf[idxs],
                    done=self.done_buf[idxs])


def ddpg(env_fn, actor_critic=core.mlp_actor_critic, ac_kwargs=dict(), seed=0,
         steps_per_epoch=4000, epochs=100, replay_size=int(1e6), gamma=0.99,
         polyak=0.995, pi_lr=1e-3, q_lr=1e-3, batch_size=100, start_steps=10000,
         update_after=1000, update_every=50, act_noise=0.1, num_test_episodes=10,
         max_ep_len=1000, logger_kwargs=dict(), save_freq=1, env_params=None,
         controller_params=None,):
    """
    Deep Deterministic Policy Gradient (DDPG)


    Args:
        env_fn : A function which creates a copy of the environment.
            The environment must satisfy the OpenAI Gym API.

        actor_critic: A function which takes in placeholder symbols 
            for state, ``x_ph``, and action, ``a_ph``, and returns the main 
            outputs from the agent's Tensorflow computation graph:

            ===========  ================  ======================================
            Symbol       Shape             Description
            ===========  ================  ======================================
            ``pi``       (batch, act_dim)  | Deterministically computes actions
                                           | from policy given states.
            ``q``        (batch,)          | Gives the current estimate of Q* for 
                                           | states in ``x_ph`` and actions in
                                           | ``a_ph``.
            ``q_pi``     (batch,)          | Gives the composition of ``q`` and 
                                           | ``pi`` for states in ``x_ph``: 
                                           | q(x, pi(x)).
            ===========  ================  ======================================

        ac_kwargs (dict): Any kwargs appropriate for the actor_critic 
            function you provided to DDPG.

        seed (int): Seed for random number generators.

        steps_per_epoch (int): Number of steps of interaction (state-action pairs) 
            for the agent and the environment in each epoch.

        epochs (int): Number of epochs to run and train agent.

        replay_size (int): Maximum length of replay buffer.

        gamma (float): Discount factor. (Always between 0 and 1.)

        polyak (float): Interpolation factor in polyak averaging for target 
            networks. Target networks are updated towards main networks 
            according to:

            .. math:: \\theta_{\\text{targ}} \\leftarrow 
                \\rho \\theta_{\\text{targ}} + (1-\\rho) \\theta

            where :math:`\\rho` is polyak. (Always between 0 and 1, usually 
            close to 1.)

        pi_lr (float): Learning rate for policy.

        q_lr (float): Learning rate for Q-networks.

        batch_size (int): Minibatch size for SGD.

        start_steps (int): Number of steps for uniform-random action selection,
            before running real policy. Helps exploration.

        update_after (int): Number of env interactions to collect before
            starting to do gradient descent updates. Ensures replay buffer
            is full enough for useful updates.

        update_every (int): Number of env interactions that should elapse
            between gradient descent updates. Note: Regardless of how long 
            you wait between updates, the ratio of env steps to gradient steps 
            is locked to 1.

        act_noise (float): Stddev for Gaussian exploration noise added to 
            policy at training time. (At test time, no noise is added.)

        num_test_episodes (int): Number of episodes to test the deterministic
            policy at the end of each epoch.

        max_ep_len (int): Maximum length of trajectory / episode / rollout.

        logger_kwargs (dict): Keyword args for EpochLogger.

        save_freq (int): How often (in terms of gap between epochs) to save
            the current policy and value function.

        env_params (dict): Environment settings.

        controller_params (dict): Controller settings.
    """

    logger = EpochLogger(**logger_kwargs)
    logger.save_config(locals())

    tf.set_random_seed(seed)
    np.random.seed(seed)

    env, test_env = env_fn(), env_fn()

    # DEBUG: cc
    print(colorize('\n\nUpdating environment parameters:\n\n', color='yellow', bold=False))

    print(colorize('\t> Training environment...', color='yellow', bold=False))
    env.update(**env_params)
    for c in env.controllers:
        c.update_parameters(**controller_params)

    print(colorize('\n\n\t> Test environment...', color='yellow', bold=False))
    # Force reset_index_mode to 'random'; If zero, we might always reset to a location that gives
    # a first observation that throws the 'done' flag.
    env_params['reset_index_mode'] = 'random'
    test_env.update(**env_params)
    for c in test_env.controllers:
        c.update_parameters(**controller_params)

    print('\n\nInfo for env:')
    env.info()
    print('\n\nInfo for test_env:')
    test_env.info()

    obs_dim = env.observation_space.shape[0]
    act_dim = env.action_space.shape[0]

    # Action limit for clamping: critically, assumes all dimensions share the same bound!
    act_limit = env.action_space.high[0]

    # Share information about action space with policy architecture
    ac_kwargs['action_space'] = env.action_space

    # Inputs to computation graph
    x_ph, a_ph, x2_ph, r_ph, d_ph = core.placeholders(obs_dim, act_dim, obs_dim, None, None)

    # Main outputs from computation graph
    with tf.variable_scope('main'):
        pi, q, q_pi = actor_critic(x_ph, a_ph, **ac_kwargs)

    # Target networks
    with tf.variable_scope('target'):
        # Note that the action placeholder going to actor_critic here is 
        # irrelevant, because we only need q_targ(s, pi_targ(s)).
        pi_targ, _, q_pi_targ = actor_critic(x2_ph, a_ph, **ac_kwargs)

    # Experience buffer
    replay_buffer = ReplayBuffer(obs_dim=obs_dim, act_dim=act_dim, size=replay_size)

    # Count variables
    var_counts = tuple(core.count_vars(scope) for scope in ['main/pi', 'main/q', 'main'])
    print('\nNumber of parameters: \t pi: %d, \t q: %d, \t total: %d\n' % var_counts)

    # Bellman backup for Q function
    backup = tf.stop_gradient(r_ph + gamma * (1 - d_ph) * q_pi_targ)

    # DDPG losses
    pi_loss = -tf.reduce_mean(q_pi)
    q_loss = tf.reduce_mean((q - backup) ** 2)

    # Separate train ops for pi, q
    pi_optimizer = tf.train.AdamOptimizer(learning_rate=pi_lr)
    q_optimizer = tf.train.AdamOptimizer(learning_rate=q_lr)
    train_pi_op = pi_optimizer.minimize(pi_loss, var_list=get_vars('main/pi'))
    train_q_op = q_optimizer.minimize(q_loss, var_list=get_vars('main/q'))

    # Polyak averaging for target variables
    target_update = tf.group([tf.assign(v_targ, polyak * v_targ + (1 - polyak) * v_main)
                              for v_main, v_targ in zip(get_vars('main'), get_vars('target'))])

    # Initializing targets to match main variables
    target_init = tf.group([tf.assign(v_targ, v_main)
                            for v_main, v_targ in zip(get_vars('main'), get_vars('target'))])

    sess = tf.Session()
    sess.run(tf.global_variables_initializer())
    sess.run(target_init)

    # Setup model saving
    logger.setup_tf_saver(sess, inputs={'x': x_ph, 'a': a_ph}, outputs={'pi': pi, 'q': q})

    def rolling_setpoints(my_env, batch_window=500):
        v = copy.copy(my_env.verbosity)
        my_env.verbosity = 0
        if my_env.playhead - batch_window >= my_env.trim_batches_start:
            first_batch = (my_env.playhead - batch_window)
        else:
            first_batch = my_env.trim_batches_start
        new_setpoints = my_env.dataset_outputs[first_batch:my_env.playhead, 0, :].mean(axis=0)
        my_env.set_output_targets(list(new_setpoints))
        print(colorize(f'\tNew setpoints: {list_of_nums_to_string(new_setpoints)}', color='magenta', bold=False))
        my_env.verbosity = v
        return

    def list_of_nums_to_string(my_list):
        list_of_strings = [f'{format(elem, ".3f"):>6}' for elem in my_list]
        a_str = '[' + ', '.join(list_of_strings) + ']'
        return a_str

    def get_action(o, noise_scale):
        a = sess.run(pi, feed_dict={x_ph: o.reshape(1, -1)})[0]
        a += noise_scale * np.random.randn(act_dim)
        return np.clip(a, -act_limit, act_limit)

    def test_agent():

        # # Set first playhead location randomly (verify settings above; we forced reset_index_mode = 'random')
        # test_env.reset()
        # # Capture playhead location; we will maintain this as a state variable below so we can
        # # force the test simulation to move sequentially through the data across epochs.
        # playhead = copy.copy(test_env.playhead)

        for j in range(num_test_episodes):

            # DEBUG cc
            print('\n\n')
            print(colorize('=' * 120, color='blue', bold=True))
            print(colorize('Start of new test episode\n', color='blue', bold=True))

            print(colorize(f'\nj: {j} / {num_test_episodes} test episodes, env.playhead: {env.playhead}',
                           color='gray', bold=True))

            # DEBUG
            print(f'\tResetting test_env...')

            # Reset test_env with playhead at "current" batch; see how far we can get
            o, d, ep_ret, ep_len = test_env.reset(), False, 0, 0

            # DEBUG
            print(f'\tObs at reset j({j}): {list_of_nums_to_string(o)}\n')
            print(f'\tobs: {list_of_nums_to_string(o)}')

            while not (d or (ep_len == max_ep_len)):

                # DEBUG cc
                print(colorize(f'Test rollout step: {ep_len} (of max {max_ep_len}), '
                               f'epoch: {j} (of {num_test_episodes})',
                               color='gray', bold=True))
                # rolling_setpoints(test_env)   # TODO: Needed?
                print(f'\tSetpoints: {list_of_nums_to_string(list(test_env.lpp.data.output_setpoints.values()))}')

                # Take deterministic actions at test time (noise_scale=0)
                test_action = get_action(o, 0)

                # DEBUG cc
                print(colorize(f'\tTaking test action: {list_of_nums_to_string(test_action)}',
                               color='red', bold=False))

                o, r, d, _ = test_env.step(test_action)

                # DEBUG cc
                print(f'\ttest_env playhead after step: {test_env.playhead}')
                print(colorize(f'\tObs from LPP: {list_of_nums_to_string(o)}\n', color='white', bold=False))

                ep_ret += r
                ep_len += 1

            # DEBUG cc
            my_str = f'\n\nEnd of test trajectory: d={d}, ep_len={ep_len}, max_ep_len={max_ep_len}\n\n'
            print(colorize(my_str, color='yellow', bold=True))

            logger.store(TestEpRet=ep_ret, TestEpLen=ep_len)

            # # Set playhead and done flag for next reset above
            # playhead = copy.copy(test_env.playhead)
            # if d:
            #     test_env.returns['done'] = False

    # Prepare for interaction with environment
    total_steps = steps_per_epoch * epochs
    start_time = time.time()

    # DEBUG cc
    print('Resetting env...')

    o, ep_ret, ep_len = env.reset(), 0, 0

    # Main loop: collect experience in env and update/log each epoch
    for t in range(total_steps):

        # DEBUG cc
        epoch = (t + 1) // steps_per_epoch
        print(colorize(f'\nt: {t}, epoch: {epoch}, env.playhead: {env.playhead}', color='gray', bold=True))

        # Until start_steps have elapsed, randomly sample actions
        # from a uniform distribution for better exploration. Afterwards, 
        # use the learned policy (with some noise, via act_noise). 
        if t > start_steps:
            a = get_action(o, act_noise)
            print(colorize(f'\tAction from policy: {list_of_nums_to_string(a)}', color='white', bold=False))
        else:
            a = env.action_space.sample()
            print(colorize(f'\tRandomly sampled action (t <= {start_steps}): {list_of_nums_to_string(a)}',
                           color='white', bold=False))

        # TODO: An ugly hack to test using convolution of experimental outputs as setpoints. Needed?
        # rolling_setpoints(env)

        # Step the env
        o2, r, d, _ = env.step(a)
        ep_ret += r
        ep_len += 1

        # DEBUG cc
        print(colorize(f'\tObs from LPP: {list_of_nums_to_string(o2)}', color='white', bold=False))

        # Ignore the "done" signal if it comes from hitting the time
        # horizon (that is, when it's an artificial terminal signal
        # that isn't based on the agent's state)
        d = False if ep_len == max_ep_len else d

        # Get raw output from underlying experimental data (not modified with controls)
        # and store in replay buffer for easy comparison to controlled outputs
        raw = env.dataset_outputs[env.playhead]

        # Store experience to replay buffer
        replay_buffer.store(raw[0], o, a, r, o2, d)

        # Super critical, easy to overlook step: make sure to update most recent observation!
        o = o2

        # End of trajectory handling
        if d or (ep_len == max_ep_len):

            # DEBUG cc
            my_str = f'\n\nEnd of training trajectory: d={d}, ep_len={ep_len}, max_ep_len={max_ep_len}\n\n'
            print(colorize(my_str, color='yellow', bold=True))
            print('Resetting env...')

            logger.store(EpRet=ep_ret, EpLen=ep_len)
            o, ep_ret, ep_len = env.reset(), 0, 0

        # Update handling
        if t >= update_after and t % update_every == 0:

            # DEBUG cc
            print(colorize('\n\nUpdating Q-learning and Policy...\n', color='magenta', bold=True))

            for _ in range(update_every):
                batch = replay_buffer.sample_batch(batch_size)
                feed_dict = {x_ph: batch['obs1'],
                             x2_ph: batch['obs2'],
                             a_ph: batch['acts'],
                             r_ph: batch['rews'],
                             d_ph: batch['done']
                             }

                # Q-learning update
                outs = sess.run([q_loss, q, train_q_op], feed_dict)
                logger.store(LossQ=outs[0], QVals=outs[1])

                # Policy update
                outs = sess.run([pi_loss, train_pi_op, target_update], feed_dict)
                logger.store(LossPi=outs[0])

        # End of epoch wrap-up
        if (t + 1) % steps_per_epoch == 0:

            # DEBUG cc
            print('\n\n')
            print(colorize('=' * 120, color='blue', bold=True))
            print(colorize('End of epoch wrap-up\n\n', color='blue', bold=True))

            epoch = (t + 1) // steps_per_epoch

            # Save model
            if (epoch % save_freq == 0) or (epoch == epochs):
                logger.save_state({'env': env}, None)

            # Test the performance of the deterministic version of the agent.
            print(colorize('\n\nTesting agent...\n\n', color='red', bold=True))
            test_agent()

            # Log info about epoch
            logger.log_tabular('Epoch', epoch)
            logger.log_tabular('EpRet', with_min_and_max=True)
            logger.log_tabular('TestEpRet', with_min_and_max=True)
            logger.log_tabular('EpLen', average_only=True)
            logger.log_tabular('TestEpLen', average_only=True)
            logger.log_tabular('TotalEnvInteracts', t)
            logger.log_tabular('QVals', with_min_and_max=True)
            logger.log_tabular('LossPi', average_only=True)
            logger.log_tabular('LossQ', average_only=True)
            logger.log_tabular('Time', time.time() - start_time)

            # DEBUG cc
            print('')

            logger.dump_tabular()

            # DEBUG cc
            print('')

    sess.close()

    return env, logger, replay_buffer


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--env', type=str, default='HalfCheetah-v2')
    parser.add_argument('--hid', type=int, default=256)
    parser.add_argument('--l', type=int, default=2)
    parser.add_argument('--gamma', type=float, default=0.99)
    parser.add_argument('--seed', '-s', type=int, default=0)
    parser.add_argument('--epochs', type=int, default=50)
    parser.add_argument('--exp_name', type=str, default='ddpg')
    args = parser.parse_args()

    from spinup.utils.run_utils import setup_logger_kwargs

    logger_kwargs = setup_logger_kwargs(args.exp_name, args.seed)

    ddpg(lambda: gym.make(args.env), actor_critic=core.mlp_actor_critic,
         ac_kwargs=dict(hidden_sizes=[args.hid] * args.l),
         gamma=args.gamma, seed=args.seed, epochs=args.epochs,
         logger_kwargs=logger_kwargs)
