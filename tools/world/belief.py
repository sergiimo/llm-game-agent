"""Tara's belief (spec 2026-10-30 §3; the robot_localization pattern with filterpy): our clicks predict her move and
grow the uncertainty; evidence (a log line with her position, a bubble of a known entity, a save reading) corrects
it. `needs_fix()` decides when the 2.5 s save reading is worth it."""
import math

import numpy as np
from filterpy.kalman import KalmanFilter

SIGMA_LOG = 0.05       # world units: a log line with her exact position
SIGMA_BUBBLE = 1.0     # the bubble of a known entity in reach
SIGMA_READING = 0.05   # a save reading
FIX_ABOVE = 3.0        # needs_fix() when the uncertainty (std) is above this
CLICK_BASE = 0.2       # click error std = BASE + PER_UNIT x hop length; set from the M0 baseline eval
CLICK_PER_UNIT = 0.4   # (dead reckoning within 1 unit only 6-27 % of the time); recalibrated from world_belief
UNKNOWN = 99.0


class Belief:
    def __init__(self, area=None, x=0.0, z=0.0, u=UNKNOWN):
        self.area = area
        self.kf = KalmanFilter(dim_x=2, dim_z=2)
        self.kf.F = np.eye(2)
        self.kf.H = np.eye(2)
        self._set(x, z, u)
        self.moving = False
        self.in_reach = None

    def _set(self, x, z, u):
        self.kf.x = np.array([[float(x)], [float(z)]])
        self.kf.P = np.eye(2) * u * u

    def click(self, dx, dz):
        """Our click is predicted to move her by (dx, dz); the error grows with the hop."""
        self.kf.x = self.kf.x + np.array([[dx], [dz]])
        q = CLICK_BASE + CLICK_PER_UNIT * math.hypot(dx, dz)
        self.kf.P = self.kf.P + np.eye(2) * q * q

    def fix(self, x, z, sigma):
        self.kf.R = np.eye(2) * sigma * sigma
        self.kf.update(np.array([[x], [z]]))

    def scene(self, area, x=None, z=None):
        """A new area: position from its anchor/spawn if known, else unknown."""
        self.area = area
        if x is None:
            self._set(0.0, 0.0, UNKNOWN)
        else:
            self._set(x, z, SIGMA_LOG)

    def u(self):
        return float(math.sqrt(max(self.kf.P[0, 0], self.kf.P[1, 1])))

    def needs_fix(self):
        return self.u() > FIX_ABOVE

    def predicted(self):
        return self.area, float(self.kf.x[0, 0]), float(self.kf.x[1, 0]), self.u()
