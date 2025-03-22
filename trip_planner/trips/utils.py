import requests
import logging
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfgen import canvas
from io import BytesIO
from datetime import datetime

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class GeocodingError(Exception):
    pass

class RoutingError(Exception):
    pass

class PdfGenerationError(Exception):
    pass

def geocode_nominatim(location):
    url = f"https://nominatim.openstreetmap.org/search?q={location}&format=json&limit=1"
    headers = {"User-Agent": "TripPlanner/1.0"}
    try:
        logger.debug(f"Geocoding location: {location}")
        response = requests.get(url, headers=headers, timeout=5)
        response.raise_for_status()
        data = response.json()
        if not data:
            logger.warning(f"No geocoding results for location: {location}")
            return None
        coords = [float(data[0]["lon"]), float(data[0]["lat"])]
        logger.debug(f"Geocoded {location} to {coords}")
        return coords
    except (requests.RequestException, ValueError) as e:
        logger.error(f"Failed to geocode {location}: {str(e)}")
        return None

def get_osrm_route(coords):
    url = f"http://router.project-osrm.org/route/v1/driving/{coords['current'][0]},{coords['current'][1]};{coords['pickup'][0]},{coords['pickup'][1]};{coords['dropoff'][0]},{coords['dropoff'][1]}?overview=simplified&geometries=geojson"
    try:
        logger.debug(f"Fetching route for coords: {coords}")
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        if data["code"] != "Ok":
            raise RoutingError(f"OSRM returned error: {data.get('message', 'Unknown error')}")
        distance = data["routes"][0]["distance"] / 1609.34
        duration = data["routes"][0]["duration"] / 3600
        coordinates = data["routes"][0]["geometry"]["coordinates"]
        logger.debug(f"Route fetched with {len(coordinates)} coordinates")
        return {
            "distance_miles": distance,
            "duration_hours": duration,
            "coordinates": coordinates
        }
    except (requests.RequestException, KeyError, ValueError) as e:
        logger.error(f"Failed to calculate route: {str(e)}")
        raise RoutingError(f"Failed to calculate route: {str(e)}")
    
def generate_eld_logs(route_data, cycle_hours_used):
    """Generate ELD logs for the trip."""
    try:
        total_distance = route_data["distance_miles"]
        total_hours = route_data["duration_hours"] + 2  # 1 hour for pickup + 1 hour for dropoff
        
        logs = []
        remaining_hours = 70 - cycle_hours_used  # 70-hour cycle limit
        remaining_miles = total_distance
        current_day = 0
        max_iterations = 100  # Prevent infinite loops
        
        if remaining_hours <= 0:
            raise ValueError("No remaining hours in cycle to complete trip")
        
        logger.debug(f"Starting ELD log generation: total_distance={total_distance}, cycle_hours_used={cycle_hours_used}, remaining_hours={remaining_hours}")
        
        while remaining_miles > 0.01 and remaining_hours > 0:
            if current_day >= max_iterations:
                raise ValueError(f"Too many days required (>{max_iterations}), check cycle hours or route data")
            
            daily_log = {"day": current_day + 1, "activities": []}
            current_time = 8.0  # Start at 08:00 each day
            on_duty_hours = 0.0  # Track total on-duty hours for the day
            
            # Pickup (1 hour on Day 1)
            if current_day == 0:
                daily_log["activities"].append({
                    "type": "pickup",
                    "start": current_time,
                    "end": current_time + 1.0
                })
                current_time += 1.0
                on_duty_hours += 1.0
            
            # Calculate daily driving
            daily_driving_hours = min(11, remaining_hours - on_duty_hours, remaining_miles / 60)  # 60 mph average
            daily_driving_hours = max(round(daily_driving_hours, 1), 0.1) if remaining_miles > 0 else 0
            daily_miles = round(daily_driving_hours * 60, 1)
            
            # Adjust if remaining_miles is less than calculated daily_miles
            if daily_miles > remaining_miles:
                daily_miles = remaining_miles
                daily_driving_hours = daily_miles / 60
            
            # Driving period
            if daily_driving_hours > 0:
                daily_log["activities"].append({
                    "type": "driving",
                    "start": current_time,
                    "end": current_time + daily_driving_hours,
                    "miles": daily_miles
                })
                current_time += daily_driving_hours
                on_duty_hours += daily_driving_hours
            
            # Break (0.5 hours if driving > 8 hours)
            if daily_driving_hours > 8 and remaining_hours - on_duty_hours >= 0.5:
                daily_log["activities"].append({
                    "type": "break",
                    "start": current_time,
                    "end": current_time + 0.5
                })
                current_time += 0.5
                on_duty_hours += 0.5
            
            # Fuel stops (15 minutes per 1000 miles, only if driving occurred)
            if daily_miles > 0:
                fuel_stops = int(daily_miles / 1000)
                for _ in range(fuel_stops):
                    if remaining_hours - on_duty_hours >= 0.25:
                        daily_log["activities"].append({
                            "type": "fuel",
                            "start": current_time,
                            "end": current_time + 0.25
                        })
                        current_time += 0.25
                        on_duty_hours += 0.25
            
            # Dropoff (1 hour on the last day)
            if remaining_miles - daily_miles <= 0.01 and remaining_hours - on_duty_hours >= 1.0:
                daily_log["activities"].append({
                    "type": "dropoff",
                    "start": current_time,
                    "end": current_time + 1.0
                })
                current_time += 1.0
                on_duty_hours += 1.0
                remaining_miles = 0  # Mark trip as complete
            
            # Append log only if it has activities
            if daily_log["activities"]:
                logs.append(daily_log)
            
            # Update remaining values
            remaining_miles = max(remaining_miles - daily_miles, 0)  # Avoid negative values
            remaining_hours -= on_duty_hours
            current_day += 1
            
            logger.debug(f"Day {current_day}: daily_miles={daily_miles}, remaining_miles={remaining_miles}, on_duty_hours={on_duty_hours}, remaining_hours={remaining_hours}")
        
        if remaining_miles > 0.01:
            raise ValueError("Trip exceeds available cycle hours")
        
        # Renumber days
        for i, log in enumerate(logs):
            log["day"] = i + 1
        
        logger.debug(f"ELD log generation completed: {len(logs)} days")
        return logs
    
    except KeyError as e:
        logger.error(f"Invalid route data: missing {str(e)}")
        raise ValueError(f"Invalid route data: missing {str(e)}")
    except Exception as e:
        logger.error(f"Error generating ELD logs: {str(e)}")
        raise ValueError(f"Error generating ELD logs: {str(e)}")
    
def generate_eld_pdf(trip, eld_logs):
    try:
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=70, bottomMargin=50, leftMargin=50, rightMargin=50)
        elements = []
        
        styles = getSampleStyleSheet()
        
        # Colors for activities
        colors_dict = {
            'pickup': colors.Color(1, 0.39, 0.28),  # Tomato
            'driving': colors.Color(1, 0.84, 0),     # Gold
            'break': colors.Color(0.27, 0.51, 0.71), # SteelBlue
            'fuel': colors.Color(0.2, 0.8, 0.2),     # LimeGreen
            'dropoff': colors.Color(1, 0.27, 0)      # OrangeRed
        }

        # Header and footer
        def draw_header(canvas, doc):
            canvas.saveState()
            canvas.setFont('Helvetica-Bold', 16)
            canvas.drawCentredString(letter[0] / 2, letter[1] - 40, f"ELD Logs for Trip {trip.id}")
            canvas.setFont('Helvetica', 10)
            canvas.drawString(50, letter[1] - 60, f"From: {trip.current_location} | Pickup: {trip.pickup_location} | To: {trip.dropoff_location}")
            canvas.drawString(50, letter[1] - 75, f"Cycle Hours Used: {trip.cycle_hours_used}")
            canvas.line(50, letter[1] - 80, letter[0] - 50, letter[1] - 80)
            canvas.restoreState()

        def draw_footer(canvas, doc):
            canvas.saveState()
            canvas.setFont('Helvetica', 8)
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            canvas.drawString(50, 30, f"Generated on: {timestamp}")
            page_num = f"Page {doc.page}"
            canvas.drawRightString(letter[0] - 50, 30, page_num)
            canvas.line(50, 40, letter[0] - 50, 40)
            canvas.restoreState()

        # Draw each day's log as a graphical timeline
        for log in eld_logs:
            elements.append(Paragraph(f"Day {log['day']}", styles['Heading2']))
            elements.append(Spacer(1, 20))

            # Create a canvas for drawing the timeline
            width = 450
            height = 200  # Reduced height
            label_width = 70
            timeline_width = width - label_width
            pixels_per_hour = timeline_width / 24
            row_height = 30  # Reduced for compactness
            activity_types = ['pickup', 'driving', 'break', 'fuel', 'dropoff']

            from reportlab.graphics.shapes import Drawing, Line, String, PolyLine
            from reportlab.graphics import renderPDF

            d = Drawing(width, height)

            # Draw labels on the left (Pickup at the top)
            for i, type in enumerate(activity_types):
                y = 50 + (len(activity_types) - 1 - i) * row_height + row_height / 2  # Reverse the row order
                d.add(String(5, y, type.capitalize(), fontName='Helvetica', fontSize=10))

            # Draw timeline at the top
            for hour in range(25):
                x = label_width + hour * pixels_per_hour
                d.add(String(x, 35, str(hour), fontName='Helvetica', fontSize=8, textAnchor='middle'))
                for half in range(2):
                    x_half = x + half * (pixels_per_hour / 2)
                    d.add(Line(x_half, 40, x_half, 50, strokeColor=colors.black, strokeWidth=1))
                for third in range(3):
                    x_third = x + third * (pixels_per_hour / 3)
                    if third == 0 or third == 1.5: continue
                    d.add(Line(x_third, 45, x_third, 50, strokeColor=colors.black, strokeWidth=0.5))

            # Draw grid
            for hour in range(25):
                x = label_width + hour * pixels_per_hour
                d.add(Line(x, 50, x, 50 + len(activity_types) * row_height, strokeColor=colors.black, strokeWidth=0.5))
            for i in range(len(activity_types) + 1):
                y = 50 + i * row_height
                d.add(Line(label_width, y, width, y, strokeColor=colors.black, strokeWidth=0.5))

            # Draw small sticks in each row
            for row_index in range(len(activity_types)):
                y_base = 50 + row_index * row_height
                for hour in range(25):
                    x = label_width + hour * pixels_per_hour
                    for half in range(2):
                        x_half = x + half * (pixels_per_hour / 2)
                        d.add(Line(x_half, y_base + row_height - 10, x_half, y_base + row_height, strokeColor=colors.black, strokeWidth=1))
                    for third in range(3):
                        x_third = x + third * (pixels_per_hour / 3)
                        if third == 0 or third == 1.5: continue
                        d.add(Line(x_third, y_base + row_height - 5, x_third, y_base + row_height, strokeColor=colors.black, strokeWidth=0.5))

            # Draw activities and transition lines
            last_activity = None
            for activity in log['activities'] or []:
                row_index = activity_types.index(activity['type'])
                if row_index == -1: continue

                # Reverse the row index for correct positioning (Pickup at the top)
                adjusted_row_index = len(activity_types) - 1 - row_index
                start_x = label_width + activity['start'] * pixels_per_hour
                end_x = label_width + activity['end'] * pixels_per_hour
                y = 50 + adjusted_row_index * row_height + row_height / 2 - 5

                # Activity line
                d.add(Line(start_x, y, end_x, y, strokeColor=colors_dict.get(activity['type'], colors.gray), strokeWidth=8))

                # Transition line between different activities
                if last_activity and last_activity['type'] != activity['type']:
                    prev_end_x = label_width + last_activity['end'] * pixels_per_hour
                    prev_row_index = len(activity_types) - 1 - activity_types.index(last_activity['type'])
                    prev_y = 50 + prev_row_index * row_height + row_height / 2 - 5
                    points = [
                        prev_end_x, prev_y,
                        prev_end_x, prev_y + (y - prev_y) / 2,
                        start_x, prev_y + (y - prev_y) / 2,
                        start_x, y
                    ]
                    d.add(PolyLine(points, strokeColor=colors_dict.get(last_activity['type'], colors.gray), strokeWidth=2))
                # Transition line within the same activity type
                elif last_activity and last_activity['type'] == activity['type']:
                    prev_end_x = label_width + last_activity['end'] * pixels_per_hour
                    points = [
                        prev_end_x, y - row_height / 4,
                        prev_end_x, y + row_height / 4,
                        start_x, y + row_height / 4,
                        start_x, y - row_height / 4,
                        prev_end_x, y - row_height / 4
                    ]
                    d.add(PolyLine(points, strokeColor=colors_dict.get(activity['type'], colors.gray), strokeWidth=1))

                last_activity = activity

                # Start and end times
                start_time = f"{int(activity['start']):02d}:{int((activity['start'] % 1) * 60):02d}"
                end_time = f"{int(activity['end']):02d}:{int((activity['end'] % 1) * 60):02d}"
                d.add(String(start_x + 2, y - 5, start_time, fontName='Helvetica', fontSize=8))
                d.add(String(end_x - 30, y - 5, end_time, fontName='Helvetica', fontSize=8))

                # Miles for driving
                if activity['type'] == 'driving':
                    d.add(String((start_x + end_x) / 2, y - 5, f"{activity['miles']} miles", fontName='Helvetica', fontSize=8, textAnchor='middle'))

            elements.append(d)
            elements.append(Spacer(1, 30))

        # Build the PDF
        doc.build(elements, onFirstPage=lambda c, d: (draw_header(c, d), draw_footer(c, d)), 
                  onLaterPages=lambda c, d: (draw_header(c, d), draw_footer(c, d)))

        pdf_content = buffer.getvalue()
        buffer.close()
        return pdf_content
    except Exception as e:
        raise PdfGenerationError(f"Failed to generate PDF: {str(e)}")