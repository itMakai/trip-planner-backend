import requests
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib.styles import getSampleStyleSheet
from io import BytesIO

class GeocodingError(Exception):
    """Raised when geocoding fails."""
    pass

class RoutingError(Exception):
    """Raised when route calculation fails."""
    pass

class PdfGenerationError(Exception):
    """Raised when PDF generation fails."""
    pass

def geocode_nominatim(location):
    url = f"https://nominatim.openstreetmap.org/search?q={location}&format=json&limit=1"
    headers = {"User-Agent": "TripPlanner/1.0"}
    try:
        response = requests.get(url, headers=headers, timeout=5)
        response.raise_for_status()  # Raise an HTTPError for bad responses
        data = response.json()
        if not data:
            raise GeocodingError(f"No geocoding results for location: {location}")
        return [float(data[0]["lon"]), float(data[0]["lat"])]
    except (requests.RequestException, ValueError) as e:
        raise GeocodingError(f"Failed to geocode {location}: {str(e)}")

def get_osrm_route(coords):
    url = f"http://router.project-osrm.org/route/v1/driving/{coords['current'][0]},{coords['current'][1]};{coords['pickup'][0]},{coords['pickup'][1]};{coords['dropoff'][0]},{coords['dropoff'][1]}?overview=full&geometries=geojson"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        if data["code"] != "Ok":
            raise RoutingError(f"OSRM returned error: {data.get('message', 'Unknown error')}")
        distance = data["routes"][0]["distance"] / 1609.34
        duration = data["routes"][0]["duration"] / 3600
        coordinates = data["routes"][0]["geometry"]["coordinates"]
        return {
            "distance_miles": distance,
            "duration_hours": duration,
            "coordinates": coordinates
        }
    except (requests.RequestException, KeyError, ValueError) as e:
        raise RoutingError(f"Failed to calculate route: {str(e)}")

def generate_eld_logs(route_data, cycle_hours_used):
    try:
        total_distance = route_data["distance_miles"]
        total_hours = route_data["duration_hours"] + 2
        
        logs = []
        remaining_hours = 70 - cycle_hours_used
        remaining_miles = total_distance
        current_day = 0
        
        if remaining_hours <= 0:
            raise ValueError("No remaining hours in cycle to complete trip")
        
        while remaining_miles > 0 and remaining_hours > 0:
            daily_log = {"day": current_day + 1, "entries": []}
            
            daily_driving_hours = min(11, remaining_hours, remaining_miles / 60)
            daily_miles = daily_driving_hours * 60
            
            on_duty_hours = daily_driving_hours
            if current_day == 0:
                on_duty_hours += 1
            if remaining_miles - daily_miles <= 0:
                on_duty_hours += 1
            
            fuel_stops = int(daily_miles / 1000)
            if fuel_stops > 0:
                daily_log["entries"].append({"type": "fuel", "count": fuel_stops})
            
            if daily_driving_hours > 8:
                daily_log["entries"].append({"type": "break", "duration": 0.5})
                on_duty_hours += 0.5
            
            daily_log["entries"].append({
                "type": "driving",
                "hours": daily_driving_hours,
                "miles": daily_miles
            })
            
            logs.append(daily_log)
            remaining_miles -= daily_miles
            remaining_hours -= on_duty_hours
            current_day += 1
        
        if remaining_miles > 0:
            raise ValueError("Trip exceeds available cycle hours")
        
        return logs
    except KeyError as e:
        raise ValueError(f"Invalid route data: missing {str(e)}")
    except Exception as e:
        raise ValueError(f"Error generating ELD logs: {str(e)}")

def generate_eld_pdf(trip, eld_logs):
    try:
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter)
        elements = []
        
        styles = getSampleStyleSheet()
        header = Paragraph(f"ELD Logs for Trip {trip.id}", styles['Title'])
        elements.append(header)
        elements.append(Paragraph(f"From: {trip.current_location} to {trip.dropoff_location}", styles['Normal']))
        elements.append(Paragraph(f"Cycle Hours Used: {trip.cycle_hours_used}", styles['Normal']))
        elements.append(Paragraph("<br/><br/>", styles['Normal']))
        
        for log in eld_logs:
            elements.append(Paragraph(f"Day {log['day']}", styles['Heading2']))
            data = [["Activity", "Details"]]
            for entry in log["entries"]:
                if entry["type"] == "driving":
                    data.append(["Driving", f"{entry['hours']} hrs, {entry['miles']} miles"])
                elif entry["type"] == "break":
                    data.append(["Break", f"{entry['duration']} hrs"])
                elif entry["type"] == "fuel":
                    data.append(["Fuel Stops", f"{entry['count']}"])
            if log["day"] == 1:
                data.append(["Pickup", "1 hr"])
            if log["day"] == len(eld_logs):
                data.append(["Dropoff", "1 hr"])
            
            table = Table(data, colWidths=[150, 300])
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 12),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 1), (-1, -1), 10),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('ALIGN', (1, 1), (1, -1), 'LEFT'),
            ]))
            elements.append(table)
            elements.append(Paragraph("<br/>", styles['Normal']))
        
        doc.build(elements)
        pdf_content = buffer.getvalue()
        buffer.close()
        return pdf_content
    except Exception as e:
        raise PdfGenerationError(f"Failed to generate PDF: {str(e)}")