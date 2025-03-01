import simpy
import datetime as dt
import random
import numpy as np
import math

import simpy.resources


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
TAKE_OFF_DRAIN = 4
LAND_DRAIN = 1
PER_KM_DRAIN = 6
CHARGE_RATE = 4 # per Minute


def coord_gen():
    return (np.random.uniform(-6, 6), np.random.uniform(-6, 6))


def distance(x, y):
    return math.sqrt(x**2 + y**2)


def charge_time(curr_batt):
    return (100-curr_batt) / CHARGE_RATE


def prep_gen():
    return np.random.normal(MEAN_PREP, STD_PREP)


def value_gen():
    return np.random.normal(MEAN_ORDER_VAL, STD_ORDER_VAL)



class ChefMonitoredResource(simpy.Resource):
    def __init__(self, env, capacity):
        super().__init__(env, capacity)
        self.last_update = 0
        self.busy_time = 0
        self.queue_time = 0
        self.order_values = []
        self.chef_wait_time = []


    def record_order_value(self, value):
        self.order_values.append(value)


    def record_chef_wait_times(self, wait_time):
        self.chef_wait_time.append(wait_time)


    def request(self):
        self.update_status()
        return super().request()
    
    
    def release(self, request):
        self.update_status()
        return super().release(request)


    def update_status(self):
        if self.count > 0:
            interval_time = self._env.now - self.last_update
            self.busy_time +=  len(self.users) * interval_time
            self.queue_time += len(self.users) * interval_time
        self.last_update = self._env.now



class DroneMonitoredResource(simpy.Resource):
    def __init__(self, env, capacity):
        super().__init__(env, capacity)
        self.last_update = 0
        self.busy_time = 0
        self.queue_time = 0
        self.battery_level = 100
        self.is_charged = self._env.event()
        self.is_charged.succeed()
        self.drone_wait_time = []
        self.battery_level_list = []
        self.delivery_times = []


    def record_drone_wait_time(self, req, wait_time):
        req.drone_wait_time.append(wait_time)


    def record_delivery_time(self, req, delivery_time):
        req.delivery_times.append(delivery_time)


    def take_off_drain_battery(self, req):
        req.battery_level -= TAKE_OFF_DRAIN


    def landing_drain_battery(self, req):
        req.battery_level -= LAND_DRAIN


    def distance_drain_battery(self, req, distance_travelled):
        req.battery_level -= distance_travelled * PER_KM_DRAIN


    def charge(self, req):
        t = charge_time(req.battery_level)
        yield self._env.timeout(t)
        req.is_charged.succeed()
        req.battery_level = 100
    

    def request(self):
        if not self.is_charged.triggered:
            yield self.is_charged
        req = super().request()
        self.update_status()
        return req
        
    
    def release(self, request):
        super().release(request)
        request.battery_level_list.append(request.battery_level)
        request.is_charged = request._env.event()
        self._env.process(request.charge())
        self.update_status()


    def update_status(self):
        if self.count > 0:
            interval_time = self._env.now - self.last_update
            self.busy_time +=  len(self.users) * interval_time
            self.queue_time += len(self.users) * interval_time
        self.last_update = self._env.now



def order_source(env: simpy.Environment, chef_resource: ChefMonitoredResource, drone_resource:DroneMonitoredResource):
    while env.now < RUN_TIME * 60:
        order_value = value_gen()
        order_location = coord_gen()
        env.process(order_prep(env, chef_resource, drone_resource, order_value, order_location))
        yield env.timeout(random.expovariate(1/MEAN_INTERVAL))


def order_prep(
        env: simpy.Environment,
        chef_resource: ChefMonitoredResource,
        drone_resource: DroneMonitoredResource,
        order_value,
        order_location
):
    chef_request_time = env.now
    with chef_resource.request() as chef_request:
        yield chef_request
        chef_wait_time = env.now - chef_request_time
        chef_resource.record_chef_wait_times(chef_wait_time)
        chef_resource.record_order_value(order_value)

        prep_time = prep_gen()
        yield env.timeout(prep_time)

    drone_request_time = env.now
    with drone_resource.request() as drone_request:
        yield drone_request
        drone_release_time = env.now
        drone_resource.record_drone_wait_time(drone_request, drone_release_time - drone_request_time)

        drone_resource.take_off_drain_battery(drone_request)
        yield env.timeout(TAKE_OFF_TIME)

        travel_distance = distance(*order_location)
        drone_resource.distance_drain_battery(drone_request, travel_distance)
        travel_time = travel_distance / DRONE_SPEED
        yield env.timeout(travel_time * 60)

        yield env.timeout(LAND_TIME)
        drone_resource.landing_drain_battery(drone_request)

        yield env.timeout(CUSTOMER_PICKUP_TIME)

        drone_resource.take_off_drain_battery(drone_request)
        yield env.timeout(TAKE_OFF_TIME)

        yield env.timeout(travel_time * 60)
        drone_resource.distance_drain_battery(drone_request, travel_distance)

        yield env.timeout(LAND_TIME)
        drone_resource.landing_drain_battery(drone_request)

        drone_delivered_time = env.now
        drone_resource.record_delivery_time(drone_request, drone_delivered_time - chef_request_time)


if __name__ == '__main__':
    MEAN_INTERVAL = 7
    DRONE_COUNT = 2
    CHEF_COUNT = 2
    revenue = 0

    env = simpy.Environment()
    drone_resource = DroneMonitoredResource(env=env, capacity=DRONE_COUNT)
    chef_resource = ChefMonitoredResource(env=env, capacity=CHEF_COUNT)
    env.process(order_source(env, chef_resource, drone_resource))
    print("delivery times:", drone_resource.delivery_times)
    print("drone wait time:", drone_resource.drone_wait_time)
    print("chef wait time:", chef_resource.chef_wait_time)
    print("order values", chef_resource.order_values)
    env.run()
