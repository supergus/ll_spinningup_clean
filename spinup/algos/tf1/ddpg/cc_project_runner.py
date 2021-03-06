import gym
import liveline_gym
import numpy as np
from spinup.algos.tf1.ddpg.ddpg import ddpg
from spinup.algos.tf1.ddpg import core
from spinup.utils.run_utils import setup_logger_kwargs
from pathlib import Path

# Disable GPU
import os
os.environ['CUDA_VISIBLE_DEVICES'] = '-1'

# Make TF shut up
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'
from seq2seq.utils import tf_helpers
tf_helpers.tf_verbosity_handler()


env_params = {
    'action_max': 0.1,  # Agent policy will be clipped by training script
    'action_min': -0.1,  # Agent policy will be clipped by training script
    'obs_max': 2.0,  # If exceeded, will trigger end of episode when training agent
    'obs_min': -2.0,  # If exceeded, will trigger end of episode when training agent
    'seed_value': 42,
    'base_reward': 0.0,  # 1.0
    'rmse_factor': 2.0,  # 2.0
    'areg_factor': 0.0,  # 0.5
    'nreg_factor': 4.0,  # 0.5
    'controller_mode': 'incremental',  # {'incremental', 'absolute'}
    'data_mode': 'all',  # {'all', 'train', 'test', 'val'}
    'step_index_mode': 'sequential',  # {'sequential', 'random'}
    'reset_index_mode': 'random',  # {'zero', 'random'}
    'verbosity': 2,  # [0, 1, 2];   0: Silent; 1: Warnings only; 2: Full verbosity
    'trim_batches_start': 200,
    'trim_batches_end': 100,
}

controller_params = {
    'output_lim_max': np.inf,  # 5.0
    'output_lim_min': np.NINF,  # -5.0
    'output_delta_max': np.inf,  # 20.0
    'output_delta_min': np.NINF,  # -20.0
    'nudge_lim_max': np.inf,  # 5.0
    'nudge_lim_min': np.NINF,  # -5.0
    'nudge_delta_max': np.inf,  # 20.0
    'nudge_delta_min': np.NINF,  # -20.0
    'controller_mode': 'incremental',
    'verbosity': 2,  # [0, 1, 2]; 1: Warnings only; 2: Full verbosity
}

logger_kwargs = setup_logger_kwargs('NEW')

env, logger, replay_buffer = ddpg(lambda: gym.make('liveline-v0'), actor_critic=core.mlp_actor_critic,
                                  ac_kwargs=dict(hidden_sizes=[256] * 2),
                                  gamma=0.99, seed=42,

                                  # # FOR QUICK TESTS
                                  # steps_per_epoch=40, epochs=3, start_steps=20, update_after=10, update_every=5,
                                  # max_ep_len=10, num_test_episodes=2,

                                  # TRAINING
                                  steps_per_epoch=4000, epochs=50, start_steps=10000, update_after=1000,
                                  update_every=50,
                                  max_ep_len=1000, num_test_episodes=10,  # more test eps? 20? More start_steps?

                                  # # DEFAULTS
                                  # steps_per_epoch=4000, epochs=100, start_steps=10000, update_after=1000,
                                  # update_every=50,
                                  # max_ep_len=1000, num_test_episodes=10,

                                  env_params=env_params,
                                  controller_params=controller_params,

                                  logger_kwargs=logger_kwargs)


p = Path(r'D:\chris\Documents\Programming\liveline_repos\ll_spinningup_clean\spinup\algos\tf1\ddpg')
f = 'cc_run_policy_vs_uncontrolled.py'
t = p / f
exec(open(t).read())
