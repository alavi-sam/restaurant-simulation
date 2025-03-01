import simpy
import datetime as dt
import random
import numpy as np
import math


MEAN_PREP = 9
STD_PREP = 2
LOAD_TIME = 2
RUN_TIME = 8
MEAN_ORDER_VAL = 145
STD_ORDER_VAL = 41
DRONE_SPEED = 60 # per Hour
TAKE_OFF_TIME = 0.5
LAND_TIME = 0.5
CUSTOMER_PICKUP_TIME = 2
TAKE_OFF_DRAIN = 0.04
LAND_DRAIN = 0.01
PER_KM_DRAIN = 0.06
CHARGE_RATE = 0.04 # per Minute


def coord_gen():
    return (np.random.uniform(-6, 6), np.random.uniform(-6, 6))


def distance(x, y):
    return math.sqrt(x**2 + y**2)


def charge_time(curr_batt):
    return (1-curr_batt) / CHARGE_RATE


def prep_gen():
    return np.random.normal(MEAN_PREP, STD_PREP, 1)


def value_gen():
    return np.random.normal(MEAN_ORDER_VAL, STD_ORDER_VAL)

