import copy
from typing import List

from gym import spaces
import numpy as np
from ray.rllib.env.multi_agent_env import MultiAgentEnv


# default game config, can be overridden in `env_config`
BOARD_HEIGHT = 6
BOARD_WIDTH = 7
WIN_LENGTH = 4
REWARD_WIN = 1.0
REWARD_LOSE = 0.0
REWARD_DRAW = 0.5
REWARD_STEP = 0.0


class Connect4Env(MultiAgentEnv):
    metadata = {'render.modes': ['human']}

    def __init__(self, env_config) -> None:
        super().__init__()
        self.game = Connect4(env_config)
        board_height = self.game.board_height
        board_width = self.game.board_width
        self.action_space = spaces.Discrete(board_width)
        self.observation_space = spaces.Dict({
            'board': spaces.Box(low=0, high=2, shape=(board_height, board_width), dtype=np.uint8),
            'action_mask': spaces.Box(low=0, high=1, shape=(board_width,), dtype=np.uint8),
        })
        # maintain a copy of each player's observations
        # each board is player invariant, has the player as `1` and the opponent as `2`
        self.boards: List[np.array] = []

    def reset(self):
        self.game = Connect4(self.game.env_config)
        self.boards = [np.zeros((self.game.board_height, self.game.board_width), dtype=np.uint8) for _ in range(2)]
        action_mask = self.game.get_action_mask()
        obs_dict = {i: {'board': self.get_state(i), 'action_mask': action_mask} for i in range(2)}
        return obs_dict

    def step(self, action_dict):
        """Make a game action.

        Throws a ValueError if trying to drop into a full column.

        :param action_dict: A dictionary of actions for each player.
        :return: A tuple containing the next obs, rewards, if the game ended and an empty info dict for both player.
        """

        player = self.game.player ^ 1  # game.player is incremented in game.move(), so use flipped value internally
        column = action_dict[player]
        if not self.game.is_valid_move(column):
            raise ValueError('Invalid action, column %s is full' % column)
        self.game.move(column)
        self.boards[0][self.game.lowest_row[column] - 1][column] = self.game.player + 1
        self.boards[1][self.game.lowest_row[column] - 1][column] = (self.game.player ^ 1) + 1

        action_mask = self.game.get_action_mask()
        obs = {i: {'board': self.get_state(i), 'action_mask': action_mask} for i in range(2)}
        rewards = {player: self.game.get_reward(), player ^ 1: 0.0}
        game_over = {'__all__': self.game.is_game_over()}

        return obs, rewards, game_over, {}

    def get_state(self, player=None) -> np.ndarray:
        if player == 0 or None:
            board = self.boards[0].copy()
        elif player == 1:
            board = self.boards[1].copy()
        else:
            raise ValueError('Invalid player ID %s' % player)
        state = np.flip(board, axis=0)
        return state


class FlattenedConnect4Env(Connect4Env):
    def __init__(self, env_config) -> None:
        super().__init__(env_config)
        board_height = self.game.board_height
        board_width = self.game.board_width
        self.observation_space = spaces.Dict({
            'board': spaces.Box(low=0, high=2, shape=(board_height * board_width,), dtype=np.uint8),
            'action_mask': spaces.Box(low=0, high=1, shape=(board_width,), dtype=np.uint8),
        })

    def get_state(self, player=None) -> np.ndarray:
        state = super().get_state(player)
        return np.ravel(state)


class SquareConnect4Env(Connect4Env):
    def __init__(self, env_config) -> None:
        super().__init__(env_config)
        board_height = self.game.board_height
        board_width = self.game.board_width
        self.observation_space = spaces.Dict({
            'board': spaces.Box(low=0, high=2, shape=(board_height + 1, board_width), dtype=np.uint8),
            'action_mask': spaces.Box(low=0, high=1, shape=(board_width,), dtype=np.uint8),
        })

    def get_state(self, player=None) -> np.ndarray:
        state = super().get_state(player)
        sq_obs = np.append(state, np.full((1, self.game.board_width), 3), axis=0)
        return sq_obs


class Connect4:
    def __init__(self, env_config=None) -> None:
        super().__init__()
        self.env_config = env_config or {}
        self.env_config['board_height'] = self.env_config.get('board_height', BOARD_HEIGHT)
        self.env_config['board_width'] = self.env_config.get('board_width', BOARD_WIDTH)
        self.env_config['win_length'] = self.env_config.get('win_length', WIN_LENGTH)
        self.env_config['reward_win'] = self.env_config.get('reward_win', REWARD_WIN)
        self.env_config['reward_draw'] = self.env_config.get('reward_draw', REWARD_DRAW)
        self.env_config['reward_lose'] = self.env_config.get('reward_lose', REWARD_LOSE)
        self.env_config['reward_step'] = self.env_config.get('reward_step', REWARD_STEP)
        self.bit_board = [0, 0]  # bit-board for each player
        # this is used for bitwise operations
        self.dirs = [1, (self.board_height + 1), (self.board_height + 1) - 1, (self.board_height + 1) + 1]
        self.heights = [(self.board_height + 1) * i for i in range(self.board_width)]  # top empty row for each column
        self.lowest_row = [0] * self.board_width  # number of stones in each row
        # top row of the board (this will never change)
        self.top_row = [(x * (self.board_height + 1)) - 1 for x in range(1, self.board_width + 1)]
        self.player = 1

    def clone(self):
        clone = Connect4()
        clone.env_config = self.env_config
        clone.bit_board = copy.deepcopy(self.bit_board)
        clone.heights = copy.deepcopy(self.heights)
        clone.lowest_row = copy.deepcopy(self.lowest_row)
        clone.top_row = copy.deepcopy(self.top_row)
        clone.player = self.player
        return clone

    def move(self, column: int) -> None:
        m2 = 1 << self.heights[column]  # position entry on bit-board
        self.heights[column] += 1  # update top empty row for column
        self.player ^= 1
        self.bit_board[self.player] ^= m2  # XOR operation to insert stone in player's bit-board
        self.lowest_row[column] += 1  # update number of stones in column

    def get_reward(self, player=None) -> float:
        if player is None:
            player = self.player

        if self.is_winner(player):
            return self.reward_win
        elif self.is_winner(player ^ 1):
            return self.reward_lose
        elif self.is_draw():
            return self.reward_draw
        else:
            return self.reward_step

    def is_winner(self, player=None) -> bool:
        """Evaluate board, find out if a player has won.

        :param player: The player to check.
        :return: True if the player has won, otherwise False.
        """
        if player is None:
            player = self.player

        for d in self.dirs:
            bb = self.bit_board[player]
            for i in range(1, self.win_length):
                bb &= self.bit_board[player] >> (i * d)
            if bb != 0:
                return True
        return False

    def is_draw(self) -> bool:
        """Is the game a draw?

        :return: True if the game is drawn, else False.
        """
        return not self.get_moves() and not self.is_winner(self.player) and not self.is_winner(self.player ^ 1)

    def is_game_over(self) -> bool:
        """Is the game over?

        :return: True if the game is over, else False.
        """
        return self.is_winner(self.player) or self.is_winner(self.player ^ 1) or not self.get_moves()

    def get_moves(self) -> List[int]:
        """Get a list of available moves.

        :return: A list of action indexes.
        """
        if self.is_winner(self.player) or self.is_winner(self.player ^ 1):
            return []  # if terminal state, return empty list

        list_moves = []
        for i in range(self.board_width):
            if self.lowest_row[i] < self.board_height:
                list_moves.append(i)
        return list_moves

    def get_action_mask(self) -> np.array:
        """Fetch a mask of valid actions

        :return: A numpy array where 1 if valid move else 0.
        """
        return np.array([1 if self.lowest_row[i] < self.board_height else 0 for i in range(self.board_width)],
                        dtype=np.uint8)

    def is_valid_move(self, column: int) -> bool:
        """Check if column is full.

        :param column: The column to check
        :return: True if it is a valid move, else False.
        """
        return self.heights[column] != self.top_row[column]

    @property
    def board_height(self) -> int:
        return self.env_config['board_height']

    @property
    def board_width(self) -> int:
        return self.env_config['board_width']

    @property
    def win_length(self) -> int:
        return self.env_config['win_length']

    @property
    def reward_win(self) -> float:
        return self.env_config['reward_win']

    @property
    def reward_draw(self) -> float:
        return self.env_config['reward_draw']

    @property
    def reward_lose(self) -> float:
        return self.env_config['reward_lose']

    @property
    def reward_step(self) -> float:
        return self.env_config['reward_step']
