# Nexus System Core Application Logic for Professional Demo
from flask import Flask, render_template
import random
from datetime import datetime

# Initialize the Flask application
app = Flask(__name__)

# --- SYSTEM WIDE SIMULATED DATA (Replace with actual DB/API calls in production) ---
def get_system_metrics():
    """Generates a dictionary of simulated, real-time system performance metrics."""
    return {
        # Core Performance Metrics (Simulated real-time fluctuations)
        'cpu_load': round(random.uniform(15.0, 75.0), 2),
        'memory_utilization': round(random.uniform(55.0, 90.0), 2),
        'network_latency_ms': random.randint(10, 85),
        
        # Resource & Capacity Metrics
        'total_users': 8764,
        'active_sessions': random.randint(500, 1500),
        'disk_capacity_gb': 1024,
        'disk_used_gb': round(random.uniform(400, 950), 2),
        
        # Health and Status
        'status_icon': '🟢', # Green Circle for Operational
        'health_status': 'Operational',
        
        # Recent Alerts and Events
        'alerts': [
            {'id': 101, 'message': 'High CPU usage detected on Node 3.', 'level': 'Warning', 'time': '2m ago'},
            {'id': 102, 'message': 'New firmware deployment successful.', 'level': 'Info', 'time': '1h ago'},
            {'id': 103, 'message': 'Database connection intermittent.', 'level': 'Critical', 'time': '2h ago'}
        ]
    }

# --- Utility Functions ---
def calculate_disk_usage(used, total):
    """Calculates disk usage percentage."""
    if total == 0:
        return 0
    return round((used / total) * 100)

# --- Routes ---

# Main Dashboard Route (Displays HTML template with dynamic data)
@app.route('/')
def dashboard():
    # Fetch (or simulate) all necessary metrics
    metrics = get_system_metrics()
    
    # Calculate derived metrics needed for the dashboard
    disk_usage_percent = calculate_disk_usage(
        metrics['disk_used_gb'], 
        metrics['disk_capacity_gb']
    )
    
    context = {
        'title': 'Nexus System Dashboard',
        'metrics': metrics,
        'disk_usage_percent': disk_usage_percent,
        'current_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    # Render the dashboard template, passing the context data
    return render_template('dashboard.html', **context)

# Custom Error Handler for 404 Not Found errors
@app.errorhandler(404)
def page_not_found(error):
    # Render the error page template
    return render_template('error.html', title='Resource Not Found', error_code=404), 404

# --- Run Application ---

if __name__ == '__main__':
    # Run the application in debug mode for development
    app.run(debug=True)
