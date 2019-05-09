## Origins of the code is based on the ddpg_agent in the DDPG_Pendulum folder
## Tweaked the code to allow easier hyperparameter changes
## Added number of learning updates and number of time steps before update

import numpy as np
import random
import copy
from collections import namedtuple, deque

from model import Actor, Critic

import torch
import torch.nn.functional as F
import torch.optim as optim

BUFFER_SIZE = int(1e5)  # replay buffer size
BATCH_SIZE = 512        # minibatch size
GAMMA = 0.99            # discount factor
TAU = 1e-3              # for soft update of target parameters
LR_ACTOR = 1e-4         # learning rate of the actor 
LR_CRITIC = 1e-3        # learning rate of the critic
WEIGHT_DECAY = 0        # L2 weight decay

LEARNING_RATE = 10      # Number of learning updates
TIME_UPDATE = 10        # Number of time steps without update

EPS_MIN = 0.1
EPS_MAX = 1.0
EPS_DECAY = 0

device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

class Agent():
    """Interacts with and learns from the environment."""
    
    def __init__(self, num_agents,state_size, action_size, random_seed, gamma=GAMMA, tau= TAU, lr_actor=LR_ACTOR, lr_critic=LR_CRITIC, weight_decay=WEIGHT_DECAY, mu=0., theta=0.15, sigma=0.2, learn_rate=LEARNING_RATE, time_update = TIME_UPDATE, eps_max=EPS_MAX, eps_min=EPS_MIN, eps_decay=EPS_DECAY):
        """Initialize an Agent object.
        
        Params
        ======
            num_agents (int)    : Number of agents
            state_size (int)    : dimension of each state
            action_size (int)   : dimension of each action
            random_seed (int)   : random seed
            gamma (float)       : discount factor
            tau (float)         : soft update of target parameters
            lr_actor (int)      : learning rate of the actor 
            lr_critic (int)     : learning rate of the critic
            weight_decay (float): L2 weight decay
            learning_rate (int) : Number of learning updates
            time_update (int)   : Number of time steps without update
        """
        self.state_size=state_size
        self.action_size=action_size
        self.seed=random.seed(random_seed)
        self.gamma=gamma
        self.tau=tau
        self.lr_actor=lr_actor
        self.lr_critic=lr_critic
        self.weight_decay=weight_decay
        self.mu=mu
        self.theta=theta
        self.sigma=sigma
        self.learning_rate=learn_rate
        self.time_update=time_update
        self.eps_max=eps_max
        self.eps_min=eps_min
        self.eps_decay=eps_decay
        self.eps=self.eps_max
        self.num_agents=num_agents

        # Actor Network (w/ Target Network)
        self.actor_local = Actor(state_size, action_size, random_seed).to(device)
        self.actor_target = Actor(state_size, action_size, random_seed).to(device)
        self.actor_optimizer = optim.Adam(self.actor_local.parameters(), lr=self.lr_actor)

        # Critic Network (w/ Target Network)
        self.critic_local = Critic(state_size, action_size, random_seed).to(device)
        self.critic_target = Critic(state_size, action_size, random_seed).to(device)
        self.critic_optimizer = optim.Adam(self.critic_local.parameters(), lr=self.lr_critic, weight_decay=self.weight_decay)

        # Noise process
        self.noise = [OUNoise(action_size, random_seed, mu=self.mu, theta=self.theta, sigma=self.sigma) for i in range(self.num_agents)]

        # Replay memory
        self.memory = ReplayBuffer(action_size, BUFFER_SIZE, BATCH_SIZE, random_seed, num_agents)

        # Update the weights of the targets
        self.hard_update(self.actor_target, self.actor_local)
        self.hard_update(self.critic_target, self.critic_local)

    
    def step(self, time_step, states, actions, rewards, next_states, dones):
        """Save experience in replay memory, and use random sample from buffer to learn."""
        # Save experience / reward
        self.memory.add(states, actions, rewards, next_states, dones)
        
        # check if it's time to learn
        if time_step % self.time_update > 0:
            return

        # Learn, if enough samples are available in memory and learn as many times as the updates
        if len(self.memory) > BATCH_SIZE:
            for i in range(self.learning_rate):
                experiences = self.memory.sample()
                self.learn(experiences, self.gamma)


    def act(self, state, add_noise=True):
        """Returns actions for given state as per current policy."""
        state = torch.from_numpy(state).float().to(device)
        self.actor_local.eval()
        with torch.no_grad():
            action = self.actor_local(state).cpu().data.numpy()
        
        self.actor_local.train()
        
        if add_noise:
            for i in range(self.num_agents):
                action += self.noise[i].sample()
        
        return np.clip(action, -1, 1)

    
    def reset(self):
        for i in range(self.num_agents):
            self.noise[i].reset()


    def save(self):
        torch.save(self.actor_local.state_dict(), 'checkpoint_actor.pth')
        torch.save(self.critic_local.state_dict(), 'checkpoint_critic.pth')


    def learn(self, experiences, gamma):
        """Update policy and value parameters using given batch of experience tuples.
        Q_targets = r + γ * critic_target(next_state, actor_target(next_state))
        where:
            actor_target(state) -> action
            critic_target(state, action) -> Q-value

        Params
        ======
            experiences (Tuple[torch.Tensor]): tuple of (s, a, r, s', done) tuples 
            gamma (float): discount factor
        """
        states, actions, rewards, next_states, dones = experiences

        # ---------------------------- update critic ---------------------------- #
        # Get predicted next-state actions and Q values from target models
        actions_next = self.actor_target(next_states)
        Q_targets_next = self.critic_target(next_states, actions_next)

        # Compute Q targets for current states (y_i)
        Q_targets = rewards + (gamma * Q_targets_next * (1 - dones))
        
        # Compute critic loss
        Q_expected = self.critic_local(states, actions)
        critic_loss = F.mse_loss(Q_expected, Q_targets)
        
        # Minimize the loss
        self.critic_optimizer.zero_grad()
        critic_loss.backward()
        self.critic_optimizer.step()

        # ---------------------------- update actor ---------------------------- #
        # Compute actor loss
        actions_pred = self.actor_local(states)
        actor_loss = -self.critic_local(states, actions_pred).mean()
        
        # Minimize the loss
        self.actor_optimizer.zero_grad()
        actor_loss.backward()
        self.actor_optimizer.step()

        # ----------------------- update target networks ----------------------- #
        self.soft_update(self.critic_local, self.critic_target, TAU)
        self.soft_update(self.actor_local, self.actor_target, TAU)

        # ----------------------- update Epsilon value ------------------------- #
        self.eps = max(self.eps - self.eps_decay, self.eps_min)

    
    def soft_update(self, local_model, target_model, tau):
        """Soft update model parameters.
        θ_target = τ*θ_local + (1 - τ)*θ_target

        Params
        ======
            local_model: PyTorch model (weights will be copied from)
            target_model: PyTorch model (weights will be copied to)
            tau (float): interpolation parameter 
        """
        for target_param, local_param in zip(target_model.parameters(), local_model.parameters()):
            target_param.data.copy_(tau*local_param.data + (1.0-tau)*target_param.data)


    def hard_update(self, target_model, local_model):
        for target_param, local_param in zip(target_model.parameters(), local_model.parameters()):
            target_param.data.copy_(local_param.data)





class OUNoise:
    """Ornstein-Uhlenbeck process."""

    def __init__(self, size, seed, mu=0., theta=0.15, sigma=0.2):
        """Initialize parameters and noise process."""
        self.mu = mu * np.ones(size)
        self.theta = theta
        self.sigma = sigma
        self.seed = random.seed(seed)
        self.reset()


    def reset(self):
        """Reset the internal state (= noise) to mean (mu)."""
        self.state = copy.copy(self.mu)


    def sample(self):
        """Update internal state and return it as a noise sample."""
        x = self.state
        dx = self.theta * (self.mu - x) + self.sigma * np.array([random.random() for i in range(len(x))])
        self.state = x + dx
        return self.state





class ReplayBuffer:
    """Fixed-size buffer to store experience tuples."""

    def __init__(self, action_size, buffer_size, batch_size, seed, num_agents):
        """Initialize a ReplayBuffer object.
        Params
        ======
            buffer_size (int): maximum size of buffer
            batch_size (int): size of each training batch
        """
        self.action_size = action_size
        self.memory = deque(maxlen=buffer_size)  # internal memory (deque)
        self.batch_size = batch_size
        self.experience = namedtuple("Experience", field_names=["state", "action", "reward", "next_state", "done"])
        self.seed = random.seed(seed)
        self.num_agents = num_agents
    

    def add(self, states, actions, rewards, next_states, dones):
        """Add a new experience to memory."""
        for i in range(self.num_agents):
            e_i = self.experience(states[i], actions[i], rewards[i], next_states[i], dones[i])
            self.memory.append(e_i)

    
    def sample(self):
        """Randomly sample a batch of experiences from memory."""
        experiences = random.sample(self.memory, k=self.batch_size)

        states = torch.from_numpy(np.vstack([e.state for e in experiences if e is not None])).float().to(device)
        actions = torch.from_numpy(np.vstack([e.action for e in experiences if e is not None])).float().to(device)
        rewards = torch.from_numpy(np.vstack([e.reward for e in experiences if e is not None])).float().to(device)
        next_states = torch.from_numpy(np.vstack([e.next_state for e in experiences if e is not None])).float().to(device)
        dones = torch.from_numpy(np.vstack([e.done for e in experiences if e is not None]).astype(np.uint8)).float().to(device)

        return (states, actions, rewards, next_states, dones)


    def __len__(self):
        """Return the current size of internal memory."""
        return len(self.memory)