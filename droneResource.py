import simpy


TAKE_OFF_DRAIN = 4
LAND_DRAIN = 1
PER_KM_DRAIN = 6
CHARGE_RATE = 4 # per Minute



def charge_time(curr_batt):
    return (100-curr_batt) / CHARGE_RATE



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

    


