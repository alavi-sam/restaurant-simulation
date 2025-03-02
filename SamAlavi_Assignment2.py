import simpy
import random
import numpy as np
import math
import matplotlib.pyplot as plt



MEAN_PREP = 9
STD_PREP = 2
LOAD_TIME = 2
RUN_TIME = 8 # Hours
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
    prep_time = random.normalvariate(MEAN_PREP, STD_PREP)
    while prep_time < 0:
        prep_time = random.normalvariate(MEAN_PREP, STD_PREP)
    return prep_time

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



class Drone:
    def __init__(self, env: simpy.Environment, drone_id):
        self.env = env
        self.drone_id = drone_id
        self.battery_level = 100
        self.is_charged = self.env.event()
        self.is_charged.succeed()

    
    def drain_by_travel(self, distance):
        self.battery_level -= distance * PER_KM_DRAIN


    def drain_by_landing(self):
        self.battery_level -= LAND_DRAIN


    def drain_by_takeoff(self):
        self.battery_level -= TAKE_OFF_DRAIN


    def charge(self):
        yield self.env.timeout(charge_time(self.battery_level))
        self.battery_level = 100


class DroneMonitoredResource(simpy.Resource):
    def __init__(self, env, capacity):
        super().__init__(env, capacity)
        self.env = env
        self.drones = [Drone(self.env, i) for i in range(capacity)]
        self.drone_wait_time_list = list()
        self.delivery_times = list()
        self.last_update = 0
        self.busy_time = 0
        self.queue_time = 0


    def record_drone_wait_time(self, wait_time):
        self.drone_wait_time_list.append(wait_time)

    
    def record_delivery_wait_time(self, wait_time):
        self.delivery_times.append(wait_time)


    def request(self):
        fully_charged = [drone for drone in self.drones if drone.battery_level == 100]
        if not fully_charged:
            picked_drone = max(self.drones, key=lambda d: d.battery_level)
            yield self.env.process(picked_drone.charge())

        else:
            picked_drone = fully_charged[0]

        self.update_status()
        if picked_drone.battery_level < 100:
            print(picked_drone.battery_level)
        req = super().request()
        yield req
        return picked_drone, req


    def release(self, request, drone: Drone):
        self.env.process(drone.charge())
        self.update_status()
        return super().release(request)
    

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
    
    drone, req = yield from drone_resource.request()

    drone_release_time = env.now
    drone_resource.record_drone_wait_time(drone_release_time - drone_request_time)

    yield(env.timeout(LOAD_TIME))

    drone.drain_by_takeoff()
    yield env.timeout(TAKE_OFF_TIME)

    travel_distance = distance(*order_location)
    drone.drain_by_travel(travel_distance)
    travel_time = travel_distance / DRONE_SPEED
    yield env.timeout(travel_time * 60)

    yield env.timeout(LAND_TIME)
    drone.drain_by_landing()

    drone_delivered_time = env.now
    drone_resource.record_delivery_wait_time(drone_delivered_time - chef_request_time)

    yield env.timeout(CUSTOMER_PICKUP_TIME)

    drone.drain_by_takeoff()
    yield env.timeout(TAKE_OFF_TIME)

    yield env.timeout(travel_time * 60)
    drone.drain_by_travel(travel_distance)

    yield env.timeout(LAND_TIME)
    drone.drain_by_landing()
    
    drone_resource.release(req, drone)



def optimize_chef_drone(drone_number, chef_number):
    sum_mean_delivery_time = 0
    for _ in range(100):
        env = simpy.Environment()
        drone_resource = DroneMonitoredResource(env, drone_number)
        chef_resource = ChefMonitoredResource(env, chef_number)
        env.process(order_source(env, chef_resource, drone_resource))
        env.run()
        sum_mean_delivery_time += sum(drone_resource.delivery_times)/len(drone_resource.delivery_times)
    return sum_mean_delivery_time / 100


if __name__ == '__main__':
    MEAN_INTERVAL = 7
    DRONE_COUNT = 2
    CHEF_COUNT = 2
    revenue = 0

    wait_time = list()

    env = simpy.Environment()
    elapsed_time = env.now
    drone_resource = DroneMonitoredResource(env=env, capacity=DRONE_COUNT)
    chef_resource = ChefMonitoredResource(env=env, capacity=CHEF_COUNT)
    env.process(order_source(env, chef_resource, drone_resource))
    env.run()
    print("mean delivery times:", sum(drone_resource.delivery_times)/len(drone_resource.delivery_times))
    print("mean drone wait time:", sum(drone_resource.drone_wait_time_list)/len(drone_resource.drone_wait_time_list))
    print("mean chef wait time:", sum(chef_resource.chef_wait_time)/len(chef_resource.chef_wait_time))
    print("mean order value:", sum(chef_resource.order_values)/len(chef_resource.order_values))
    
    plt.hist(drone_resource.delivery_times)
    plt.xlabel('Histogram of delivery times')
    plt.savefig('delivery_histogram.jpg')
    # plt.show()
    plt.close()

    plt.hist(drone_resource.drone_wait_time_list)
    plt.xlabel('Histogram of drone wait time')
    plt.savefig('drone_wait_time_histogram.jpg')
    # plt.show()
    plt.close()

    plt.hist(chef_resource.chef_wait_time)
    plt.xlabel('Histogram of chef wait time')
    plt.savefig('chef_wait_time_histogram.jpg')
    # plt.show()
    plt.close()

    plt.hist(chef_resource.order_values)
    plt.xlabel('Histogram of order value')
    plt.savefig('order_value_histogram.jpg')
    # plt.show()
    plt.close()

    for d in range(1, 5):
        for c in range(1, 5):
            delivery_time = optimize_chef_drone(d, c)

            print(delivery_time, d, c)