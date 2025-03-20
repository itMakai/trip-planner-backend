from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from django.http import HttpResponse
from .models import Trip
from .serializers import TripSerializer
from .utils import geocode_nominatim, get_osrm_route, generate_eld_logs, generate_eld_pdf
from .utils import GeocodingError, RoutingError, PdfGenerationError

class TripViewSet(viewsets.ModelViewSet):
    queryset = Trip.objects.all()
    serializer_class = TripSerializer

    @action(detail=True, methods=['get'])
    def calculate_route(self, request, pk=None):
        try:
            trip = self.get_object()
            
            # Check if data is already calculated
            if trip.route_data and trip.eld_logs:
                return Response({
                    "route": trip.get_route_data(),
                    "eld_logs": trip.get_eld_logs()
                })
            
            coords = {
                "current": geocode_nominatim(trip.current_location),
                "pickup": geocode_nominatim(trip.pickup_location),
                "dropoff": geocode_nominatim(trip.dropoff_location)
            }
            
            if None in coords.values():
                return Response({"error": "Geocoding returned None for one or more locations"}, status=400)
            
            route_data = get_osrm_route(coords)
            eld_logs = generate_eld_logs(route_data, trip.cycle_hours_used)
            
            # Store the data
            trip.set_route_data(route_data)
            trip.set_eld_logs(eld_logs)
            trip.save()
            
            return Response({
                "route": route_data,
                "eld_logs": eld_logs
            })
        except GeocodingError as e:
            return Response({"error": str(e)}, status=400)
        except RoutingError as e:
            return Response({"error": str(e)}, status=400)
        except ValueError as e:
            return Response({"error": str(e)}, status=400)
        except Exception as e:
            return Response({"error": f"Unexpected error: {str(e)}"}, status=500)

    @action(detail=True, methods=['get'])
    def download_eld_logs(self, request, pk=None):
        try:
            trip = self.get_object()
            
            # Check if data exists
            if not trip.route_data or not trip.eld_logs:
                return Response({"error": "Route and ELD logs not calculated yet. Please calculate the route first."}, status=400)
            
            route_data = trip.get_route_data()
            eld_logs = trip.get_eld_logs()
            pdf_content = generate_eld_pdf(trip, eld_logs)
            
            response = HttpResponse(pdf_content, content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="eld_logs_trip_{trip.id}.pdf"'
            response['Content-Length'] = len(pdf_content)
            return response
        except PdfGenerationError as e:
            return Response({"error": str(e)}, status=400)
        except Exception as e:
            return Response({"error": f"Unexpected error: {str(e)}"}, status=500)