# **Trip Planner Backend**

This is the backend application for the **Trip Planner** project. It provides APIs for geocoding locations, calculating routes, generating ELD (Electronic Logging Device) logs, and creating downloadable PDF reports. The backend is built with **Django** and **Django REST Framework**.

---

## **Features**

### **1. Geocoding**
- Uses the Nominatim API to geocode locations (convert location names into latitude and longitude).
- Handles errors gracefully and logs warnings for invalid or missing geocoding results.

### **2. Route Calculation**
- Uses the OSRM (Open Source Routing Machine) API to calculate routes between locations.
- Returns route details including:
  - Distance in miles
  - Duration in hours
  - Route coordinates for mapping

### **3. ELD Logs Generation**
- Generates ELD logs based on the calculated route and available cycle hours.
- Logs include:
  - Pickup, driving, breaks, fuel stops, and dropoff activities
  - Daily logs with detailed activity timelines
- Ensures compliance with the 70-hour cycle limit.

### **4. PDF Report Generation**
- Creates a downloadable PDF report of the ELD logs.
- Features:
  - Header with trip details
  - Graphical timeline for each day's activities
  - Color-coded activity types (e.g., driving, breaks, fuel stops)
  - Footer with generation timestamp and page numbers

---

## **Getting Started**

### **Prerequisites**
- Python 3.9 or higher
- Django 5.1 or higher
- PostgreSQL (or any other database supported by Django)

### **Installation**
1. Clone the repository:
   ```bash
   git clone https://itmakai/trip-planner-backend.git
   cd trip-planner-backend