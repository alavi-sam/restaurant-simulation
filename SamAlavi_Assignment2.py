import simpy
import random
import numpy as np
import math
import matplotlib.pyplot as plt
import simpy.events



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
stats = {}



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
        self.order_id = 0
        self.last_update = 0
        self.busy_time = 0
        self.queue_time = 0
        self.order_values = []
        self.chef_wait_time = []
        self.orders_queue = list()


    def record_order_value(self, value):
        self.order_values.append(value)


    def record_chef_wait_times(self, wait_time):
        self.chef_wait_time.append(wait_time)


    def request(self, order_id):
        self.update_status()
        req = super().request()
        yield req
        self.orders_queue.append(order_id)
        return req, order_id
    
    
    def release(self, request, order_id):
        self.orders_queue.remove(order_id)
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
        self.on_site = self.env.event() 
        self.on_site.succeed()

    
    def drain_by_travel(self, distance):
        self.battery_level -= distance * PER_KM_DRAIN


    def drain_by_landing(self):
        self.battery_level -= LAND_DRAIN


    def drain_by_takeoff(self):
        self.battery_level -= TAKE_OFF_DRAIN


    def charge(self):
        yield self.env.timeout(charge_time(self.battery_level))
        self.battery_level = 100
        if not self.is_charged.triggered:
            self.is_charged.succeed()


class DroneMonitoredResource(simpy.Resource):
    def __init__(self, env, capacity):
        super().__init__(env, capacity)
        self.env = env
        self.drones = [Drone(self.env, i) for i in range(capacity)]
        self.drone_wait_time_list = list()
        self.delivery_times = list()
        self.last_update = 0
        self.distance_list = list()
        self.busy_time = 0
        self.queue_time = 0


    def record_drone_wait_time(self, wait_time):
        self.drone_wait_time_list.append(wait_time)

    
    def record_delivery_wait_time(self, wait_time):
        self.delivery_times.append(wait_time)

    def record_delivery_distance(self, distance):
        self.distance_list.append(distance)


    
    def request(self):
        # Find drones that are free (on_site is triggered)
        free_drones = [drone for drone in self.drones if drone.on_site.triggered]
        if free_drones:
            # Prefer free drones that are fully charged.
            fully_charged = [d for d in free_drones if d.battery_level == 100]
            if fully_charged:
                picked_drone = fully_charged[0]
            else:
                # If none fully charged, pick the free drone with the highest battery and wait for it.
                picked_drone = max(free_drones, key=lambda d: d.battery_level)
                yield self.env.process(picked_drone.charge())
        else:
            # If no drone is free, select the drone with the highest battery.
            best_drone = max(self.drones, key=lambda d: d.battery_level)
            yield best_drone.on_site  # Wait until it becomes available.
            if best_drone.battery_level < 100:
                yield self.env.process(best_drone.charge())
            picked_drone = best_drone

        self.update_status()
        # Mark this drone as busy by resetting its on_site event.
        picked_drone.on_site = self.env.event()
        req = super().request()
        yield req
        return picked_drone, req


    def release(self, request, drone: Drone):
        if not drone.on_site.triggered:
            drone.on_site.succeed()
        drone.is_charged = self.env.event()
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
    order_id = 0
    while env.now < RUN_TIME * 60:
        order_id += 1
        order_value = value_gen()
        order_location = coord_gen()
        print(f"recieved order {order_id} at {env.now}")
        stats[order_id] = {'order_time': env.now}
        env.process(order_prep(env, chef_resource, drone_resource, order_value, order_location, order_id))
        # print()
        yield env.timeout(random.expovariate(1/MEAN_INTERVAL))


def order_prep(
        env: simpy.Environment,
        chef_resource: ChefMonitoredResource,
        drone_resource: DroneMonitoredResource,
        order_value,
        order_location,
        order_id
):
    chef_request_time = env.now
    
    chef_req, order_id = yield from chef_resource.request(order_id)
    stats[order_id].update({'prep_start_time': env.now})
    print(f"chef is preparing {order_id} at {env.now}")
    chef_wait_time = env.now - chef_request_time
    chef_resource.record_chef_wait_times(chef_wait_time)
    chef_resource.record_order_value(order_value)
    prep_time = prep_gen()
    print(f"order {order_id} will take {prep_time}")
    stats[order_id].update({'prep_time': prep_time})
    yield env.timeout(prep_time)
    print(f"chef has done {order_id} at {env.now}")
    stats[order_id].update({'prep_done': env.now})
    chef_resource.release(chef_req, order_id)

    drone_request_time = env.now
    
    print(f"drone requested at {env.now}")

    stats[order_id].update({'drone_request_time': env.now})

    drone, req = yield from drone_resource.request()
    print(f"drone {drone.drone_id}  picked up the order at {env.now}")
    stats[order_id].update({'drone_ready_time': env.now})

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
    print(f"drone {drone.drone_id} delivered the order at {env.now}")
    drone_resource.record_delivery_wait_time(drone_delivered_time - chef_request_time)
    drone_resource.record_delivery_distance(travel_distance)
    stats[order_id].update({'delivered_time': env.now})

    yield env.timeout(CUSTOMER_PICKUP_TIME)

    drone.drain_by_takeoff()
    yield env.timeout(TAKE_OFF_TIME)

    yield env.timeout(travel_time * 60)
    drone.drain_by_travel(travel_distance)

    yield env.timeout(LAND_TIME)
    drone.drain_by_landing()
    
    stats[order_id].update({
        "end_battery_level": drone.battery_level,
        "time_to_charge": charge_time(drone.battery_level),
        "drone_end_time": env.now
    })
    print(f"drone {drone.drone_id} released at {env.now}")
    yield drone_resource.release(req, drone)



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
    # print("mean delivery times:", sum(drone_resource.delivery_times)/len(drone_resource.delivery_times))
    # print("mean drone wait time:", sum(drone_resource.drone_wait_time_list)/len(drone_resource.drone_wait_time_list))
    # print("mean chef wait time:", sum(chef_resource.chef_wait_time)/len(chef_resource.chef_wait_time))
    # print("mean order value:", sum(chef_resource.order_values)/len(chef_resource.order_values))

    # print(
    #     "90% percent of the orders are arrived in less than",
    #     sorted(drone_resource.delivery_times)[len(drone_resource.delivery_times)*9//10],
    #     'minutes.'
    #     )
    print(stats)
    
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

    # for d in range(1, 5):
    #     for c in range(1, 5):
    #         delivery_time = optimize_chef_drone(d, c)

    #         print(delivery_time, d, c)


    # print(drone_resource.distance_list)
    # print("=" *10)
    # print(drone_resource.delivery_times)
    # print("=" *10)
    # print(len(drone_resource.delivery_times))


"""
mean delivery times: 54.504713794746266
mean drone wait time: 36.17471247755659
mean chef wait time: 1.9547662565952457
mean order value: 156.82325140715173
90% percent of the orders are arrived in less than 81.38849574137677 minutes.
QSocketNotifier: Can only be used with threads started with QThread
303.2815668677018 1 1
305.2277996135673 1 2
302.10144327489445 1 3
307.78342883635634 1 4
101.85720430421321 2 1
61.19344495516057 2 2
59.85998647970304 2 3
60.68827948305403 2 4
96.51316713839074 3 1
25.64804922204772 3 2
22.94712132877359 3 3
23.380711606983617 3 4
101.05084122335546 4 1
21.465415563713545 4 2
19.182363750841645 4 3
19.00685087382815 4 4
"""