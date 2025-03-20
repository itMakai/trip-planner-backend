from django.db import models
import json

class Trip(models.Model):
    current_location = models.CharField(max_length=255)
    pickup_location = models.CharField(max_length=255)
    dropoff_location = models.CharField(max_length=255)
    cycle_hours_used = models.FloatField()
    route_data = models.TextField(null=True, blank=True)  # Store JSON as text
    eld_logs = models.TextField(null=True, blank=True)   # Store JSON as text

    def set_route_data(self, data):
        self.route_data = json.dumps(data)

    def get_route_data(self):
        return json.loads(self.route_data) if self.route_data else None

    def set_eld_logs(self, logs):
        self.eld_logs = json.dumps(logs)

    def get_eld_logs(self):
        return json.loads(self.eld_logs) if self.eld_logs else None