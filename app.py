from flask import Flask, render_template
from datetime import datetime
import random

# Initialize the Flask application.
app = Flask(__name__)

# --- Simulated System Metrics (To look professional and functional) ---

def get_simulated_metrics():
    """Generates dynamic and realistic system metrics data."""
    
    # Simulate current usage metrics
    cpu_load = random.randint(30, 95)
    memory_usage = random.randint(45, 90)
    disk_utilization = random.randint(55, 99)
    
    # Determine system status based on disk usage (high disk usage implies risk)
    if disk_utilization > 90:
        health_status = 'Critical'
        status_color = 'bg-red-500'
    elif cpu_load > 85 or memory_usage > 80:
        health_status = 'Warning'
        status_color = 'bg-yellow-500'
    else:
        health_status = 'Operational'
        status_color = 'bg-green-500'

    # Simulated recent alerts
    alerts = [
        {"time": "09:30 AM", "message": "High Disk Utilization (98%) on Storage Node Alpha."},
        {"time": "10:15 AM", "message": f"CPU spike detected: {cpu_load}%"},
        {"time": "11:05 AM", "message": "Network latency increased by 15ms."}
    ]

    return {
        'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'cpu_load': cpu_load,
        'memory_usage': memory_usage,
        'disk_utilization': disk_utilization,
        'health_status': health_status,
        'status_color': status_color,
        'uptime_days': 157,
        'total_servers': 42,
        'alerts': alerts
    }

# --- Routes ---

# Route for the main dashboard page (Home page).
@app.route('/')
def dashboard():
    """Renders the dashboard with simulated data."""
    # Fetch the dynamic metrics
    metrics = get_simulated_metrics()
    
    # Render the 'dashboard.html' template and pass the data
    return render_template(
        'dashboard.html', 
        title='Nexus System Dashboard',
        data=metrics
    )

# A simple metrics route to show functionality (not strictly necessary for the demo, but good practice)
@app.route('/metrics')
def metrics_page():
    """Shows raw simulated metrics data as JSON."""
    return get_simulated_metrics()

# --- Error Handler ---

# Custom handler for 404 Not Found errors.
@app.errorhandler(404)
def page_not_found(error):
    # Render the 'error.html' template.
    return render_template('error.html', title='Page Not Found', error_code=404), 404
