import gym
from gym import spaces
import snakeoil3_gym as snakeoil3
import numpy as np
import copy
import collections as col
import os
import time


class TorcsEnv:
    terminal_judge_start = 500  # Speed limit is applied after this step
    termination_limit_progress = 5  # [km/h], episode terminates if car is running slower than this limit
    default_speed = 300

    initial_reset = True


    def __init__(self, vision=False, throttle=False, gear_change=False, brake=False):
       #print("Init")
        self.vision = vision
        self.throttle = throttle
        self.gear_change = gear_change
        self.brake = brake

        self.initial_run = True

        ##print("launch torcs")
        os.system('pkill torcs')
        time.sleep(0.5)
        if self.vision is True:
            os.system('torcs -nofuel -nodamage -nolaptime  -vision &')
        else:
            os.system('torcs  -nofuel -nodamage -nolaptime &')
        time.sleep(0.5)
        os.system('sh autostart.sh')
        time.sleep(0.5)

        """
        obs = client.S.d  # Get the current full-observation from torcs
        """
        if throttle is False:
            self.action_space = spaces.Box(low=-1.0, high=1.0, shape=(1,))
        else:
            self.action_space = spaces.Box(low=-1.0, high=1.0, shape=(2,))

        if vision is False:
            high = np.array([1., np.inf, np.inf, np.inf, 1., np.inf, 1., np.inf])
            low = np.array([0., -np.inf, -np.inf, -np.inf, 0., -np.inf, 0., -np.inf])
            self.observation_space = spaces.Box(low=low, high=high)
        else:
            high = np.array([1., np.inf, np.inf, np.inf, 1., np.inf, 1., np.inf, 255])
            low = np.array([0., -np.inf, -np.inf, -np.inf, 0., -np.inf, 0., -np.inf, 0])
            self.observation_space = spaces.Box(low=low, high=high)

    def step(self, u):
        #print("Step")
        # convert thisAction to the actual torcs actionstr
        client = self.client

        this_action = self.agent_to_torcs(u)

        # Apply Action
        action_torcs = client.R.d

        # Steering
        action_torcs['steer'] = this_action['steer']  # in [-1, 1]

        #  Simple Autnmatic Throttle Control by Snakeoil
        if self.throttle is False:
            target_speed = self.default_speed
            if client.S.d['speedX'] < target_speed - (client.R.d['steer']*50):
                client.R.d['accel'] += .01
            else:
                client.R.d['accel'] -= .01

            if client.R.d['accel'] > 0.2:
                client.R.d['accel'] = 0.2

            if client.S.d['speedX'] < 10:
                client.R.d['accel'] += 1/(client.S.d['speedX']+.1)

            # Traction Control System
            if ((client.S.d['wheelSpinVel'][2]+client.S.d['wheelSpinVel'][3]) -
               (client.S.d['wheelSpinVel'][0]+client.S.d['wheelSpinVel'][1]) > 5):
                action_torcs['accel'] -= .2
        else:
            action_torcs['accel'] = this_action['accel']

        #  Automatic Gear Change by Snakeoil
        if self.gear_change is True:
            action_torcs['gear'] = this_action['gear']
        else:
            #  Automatic Gear Change by Snakeoil is possible
            action_torcs['gear'] = 1

            if client.S.d['speedX'] > 50:
                action_torcs['gear'] = 2
            if client.S.d['speedX'] > 80:
                action_torcs['gear'] = 3
            if client.S.d['speedX'] > 110:
                action_torcs['gear'] = 4
            if client.S.d['speedX'] > 140:
                action_torcs['gear'] = 5
            if client.S.d['speedX'] > 170:
                action_torcs['gear'] = 6

        # braking
        if self.brake is True:
            action_torcs['brake'] = this_action['brake']

        #print(action_torcs)
        # Save the privious full-obs from torcs for the reward calculation
        obs_pre = copy.deepcopy(client.S.d)

        # One-Step Dynamics Update #################################
        # Apply the Agent's action into torcs
        client.respond_to_server()
        # Get the response of TORCS
        client.get_servers_input()

        # Get the current full-observation from torcs
        obs = client.S.d

        # Make an obsevation from a raw observation vector from TORCS
        self.observation = self.make_observaton(obs)

        # Reward setting Here #######################################
        # direction-dependent positive reward
        track = np.array(obs['track'])
        sp = np.array(obs['speedX'])
        progress = sp*np.cos(obs['angle'])
        reward = progress

        # collision detection
        if obs['damage'] - obs_pre['damage'] > 0:
            reward = -1

        # Termination judgement #########################
        episode_terminate = False
        if track.min() < 0:  # Episode is terminated if the car is out of track
            reward = - 1
            episode_terminate = True
            #client.R.d['meta'] = True

        if self.terminal_judge_start < self.time_step: # Episode terminates if the progress of agent is small
            if progress < self.termination_limit_progress:
                episode_terminate = True
                #client.R.d['meta'] = True

        if np.cos(obs['angle']) < 0: # Episode is terminated if the agent runs backward
            episode_terminate = True
            #client.R.d['meta'] = True


        if client.R.d['meta'] is True: # Send a reset signal
            self.initial_run = False
            client.respond_to_server()

        self.time_step += 1

        return self.get_obs(), reward, client.R.d['meta'], {}

    def reset(self, relaunch=False):
        #print("Reset")

        self.time_step = 0

        if self.initial_reset is not True:
            self.client.R.d['meta'] = True
            self.client.respond_to_server()

            ## TENTATIVE. Restarting TORCS every episode suffers the memory leak bug!
            if relaunch is True:
                self.reset_torcs()
                print("### TORCS is RELAUNCHED ###")

        # Modify here if you use multiple tracks in the environment
        self.client = snakeoil3.Client(p=3001, vision=self.vision)  # Open new UDP in vtorcs
        self.client.MAX_STEPS = np.inf

        client = self.client
        client.get_servers_input()  # Get the initial input from torcs

        obs = client.S.d  # Get the current full-observation from torcs
        self.observation = self.make_observaton(obs)

        self.last_u = None

        self.initial_reset = False
        return self.get_obs()

    def end(self):
        os.system('pkill torcs')

    def get_obs(self):
        return self.observation

    def reset_torcs(self):
       #print("relaunch torcs")
        os.system('pkill torcs')
        time.sleep(0.5)
        if self.vision is True:
            os.system('torcs -nofuel -nodamage -nolaptime -vision &')
        else:
            os.system('torcs -nofuel -nodamage -nolaptime &')
        time.sleep(0.5)
        os.system('sh autostart.sh')
        time.sleep(0.5)

    def agent_to_torcs(self, u):
        torcs_action = {'steer': u[0]}

        if self.throttle is True:  # throttle action is enabled
            torcs_action.update({'accel': u[1]})

        if self.gear_change is True: # gear change action is enabled
            torcs_action.update({'gear': u[2]})

        if self.brake is True: # gear change action is enabled
            torcs_action.update({'brake': u[3]})

        return torcs_action

    def make_observaton(self, raw_obs):
        names = ['focus',
                 'speedX', 'speedY', 'speedZ',
                 'opponents',
                 'rpm',
                 'track',
                 'wheelSpinVel',
                 'angle',
                 'trackPos']
        Observation = col.namedtuple('Observaion', names)
        return Observation(focus=np.array(raw_obs['focus'], dtype=np.float32) / 200.,
                           speedX=np.array(raw_obs['speedX'], dtype=np.float32) / self.default_speed,
                           speedY=np.array(raw_obs['speedY'], dtype=np.float32) / self.default_speed,
                           speedZ=np.array(raw_obs['speedZ'], dtype=np.float32) / self.default_speed,
                           opponents=np.array(raw_obs['opponents'], dtype=np.float32) / 200.,
                           rpm=np.array(raw_obs['rpm'], dtype=np.float32),
                           track=np.array(raw_obs['track'], dtype=np.float32) / 200.,
                           wheelSpinVel=np.array(raw_obs['wheelSpinVel'], dtype=np.float32),
                           angle=np.array(raw_obs['angle'], dtype=np.float32),
                           trackPos=np.array(raw_obs['trackPos'], dtype=np.float32))

