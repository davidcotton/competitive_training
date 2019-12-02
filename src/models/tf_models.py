from gym import spaces
import numpy as np
from ray.rllib.agents.dqn.distributional_q_model import DistributionalQModel
from ray.rllib.models.tf.fcnet_v2 import FullyConnectedNetwork
from ray.rllib.models.tf.misc import get_activation_fn, flatten, normc_initializer
from ray.rllib.models.tf.tf_modelv2 import TFModelV2
from ray.rllib.utils import try_import_tf

tf = try_import_tf()


class ParametricActionsMLP(DistributionalQModel, TFModelV2):
    """Tensorflow model that supports policy gradient and DQN policies."""

    def __init__(self, obs_space, action_space, num_outputs, model_config, name, **kwargs):
        super().__init__(obs_space, action_space, num_outputs, model_config, name, **kwargs)

        # DictFlatteningPreprocessor, combines all obs components together
        # obs.shape for MLP should be a flattened game board obs
        original_space = obs_space.original_space['board']
        flat_obs_space = spaces.Box(low=np.min(original_space.low), high=np.max(original_space.high),
                                    shape=(np.prod(original_space.shape),))
        self.mlp = FullyConnectedNetwork(flat_obs_space, action_space, num_outputs, model_config, name)
        self.register_variables(self.mlp.variables())

    def forward(self, input_dict, state, seq_lens):
        obs = flatten(input_dict['obs']['board'])
        action_mask = tf.maximum(tf.log(input_dict['obs']['action_mask']), tf.float32.min)
        model_out, _ = self.mlp({'obs': obs})
        return action_mask + model_out, state

    def value_function(self):
        return self.mlp.value_function()


class ParametricActionsCNN(DistributionalQModel, TFModelV2):
    """Tensorflow model that supports policy gradient and DQN policies.

    If `conv_filters` provided will generate CNN, otherwise MLP.
    """

    def __init__(self, obs_space, action_space, num_outputs, model_config, name, **kwargs):
        super().__init__(obs_space, action_space, num_outputs, model_config, name, **kwargs)

        conv_filters = model_config['conv_filters']
        self.is_conv = bool(conv_filters)
        orig_shape = obs_space.original_space['board']
        new_shape = orig_shape.shape + (1,) if self.is_conv else (np.prod(orig_shape.shape),)
        self.inputs = tf.keras.layers.Input(shape=new_shape, name='observations')
        last_layer = self.inputs

        if self.is_conv:
            conv_activation = get_activation_fn(model_config['conv_activation'])
            for i, (filters, kernel_size, stride) in enumerate(conv_filters, 1):
                last_layer = tf.keras.layers.Conv2D(
                    filters,
                    kernel_size,
                    stride,
                    name="conv{}".format(i),
                    activation=conv_activation,
                    padding='same')(last_layer)
            last_layer = tf.keras.layers.Flatten()(last_layer)

        fc_activation = get_activation_fn(model_config['fcnet_activation'])
        for i, size in enumerate(model_config['fcnet_hiddens'], 1):
            last_layer = tf.keras.layers.Dense(
                size,
                name='fc{}'.format(i),
                activation=fc_activation,
                kernel_initializer=normc_initializer(1.0))(last_layer)

        layer_out = tf.keras.layers.Dense(
            num_outputs,
            name="my_out",
            activation=None,
            kernel_initializer=normc_initializer(0.01))(last_layer)
        value_out = tf.keras.layers.Dense(
            1,
            name="value_out",
            activation=None,
            kernel_initializer=normc_initializer(0.01))(last_layer)

        self.base_model = tf.keras.Model(self.inputs, [layer_out, value_out])
        self.register_variables(self.base_model.variables)
        self._value_out = None

    def forward(self, input_dict, state, seq_lens):
        obs = input_dict['obs']['board']
        obs = tf.expand_dims(obs, -1) if self.is_conv else flatten(obs)
        action_mask = tf.maximum(tf.log(input_dict['obs']['action_mask']), tf.float32.min)
        model_out, self._value_out = self.base_model(obs)
        return action_mask + model_out, state

    def value_function(self):
        return tf.reshape(self._value_out, [-1])
