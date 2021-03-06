import argparse

import ray
from ray import tune
from ray.tune.registry import register_env

from src.bandits import Exp3Bandit
from src.callbacks import bandit_on_episode_start, bandit_policy_mapping_fn, bandit_on_episode_end
from src.policies import HumanPolicy, MCTSPolicy, RandomPolicy
from src.utils import get_worker_config, get_learner_policy_configs, get_model_config, get_policy_config


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--policy', type=str, default='PPO')
    parser.add_argument('--use-cnn', action='store_true')
    parser.add_argument('--num-learners', type=int, default=2)
    parser.add_argument('--debug', action='store_true')
    parser.add_argument('--human', action='store_true')
    args = parser.parse_args()

    ray.init(local_mode=args.debug)
    tune_config = get_worker_config(args)
    tune_config.update(get_policy_config(args.policy))

    Exp3Bandit = ray.remote(Exp3Bandit)
    bdt = Exp3Bandit.remote(args.num_learners, 0.07)

    model_config, env_cls = get_model_config(args.use_cnn)
    register_env('c4', lambda cfg: env_cls(cfg, bdt))
    env = env_cls(bandit=bdt)
    obs_space, action_space = env.observation_space, env.action_space
    trainable_policies = get_learner_policy_configs(args.num_learners, obs_space, action_space, model_config)

    tune.run(
        args.policy,
        name='main',
        stop={
            'timesteps_total': int(100e6),
        },
        config=dict({
            'env': 'c4',
            'env_config': {},
            'multiagent': {
                'policies_to_train': [*trainable_policies],
                'policy_mapping_fn': bandit_policy_mapping_fn,
                'policies': {
                    **trainable_policies,
                    'mcts': (MCTSPolicy, obs_space, action_space, {}),
                    'human': (HumanPolicy, obs_space, action_space, {}),
                    'random': (RandomPolicy, obs_space, action_space, {}),
                },
            },
            'callbacks': {
                'on_episode_start': bandit_on_episode_start,
                'on_episode_end': bandit_on_episode_end,
            },
        }, **tune_config),
        checkpoint_at_end=True,
        # resume=True,
    )
