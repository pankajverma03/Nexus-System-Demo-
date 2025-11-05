import os
import time
from flask import Flask, render_template_string, redirect, url_for
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

# --- Configuration ---
# Use the DATABASE_URL environment variable provided by Render.
# This must be the Internal Database URL for the service to connect correctly.
database_url = os.environ.get("DATABASE_URL")
openai_api_key = os.environ.get("OPENAI_API_KEY")

app = Flask(__name__)
# The secret key is not strictly needed for this simple demo, but good practice
app.config['SECRET_KEY'] = os.urandom(24)

# Initialize engine (will be None if DATABASE_URL is missing)
engine = None
if database_url:
    try:
        # Note: psycopg2 is used via SQLAlchemy to connect to Postgres
        engine = create_engine(database_url)
        print("Database engine successfully configured.")
    except Exception as e:
        print(f"Error initializing database engine: {e}")
        engine = None
else:
    print("FATAL: DATABASE_URL environment variable is not set.")


# --- Database Schema Setup ---
def setup_database(engine):
    """Ensures the necessary table exists in the database."""
    if not engine:
        return False

    try:
        with engine.connect() as connection:
            # Create the 'events' table if it doesn't exist
            connection.execute(text("""
                CREATE TABLE IF NOT EXISTS events (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    event_type VARCHAR(50),
                    data TEXT
                );
            """))
            connection.commit()
        print("Database schema verified/initialized successfully.")
        return True
    except OperationalError as e:
        print(f"Database setup failed due to connection error: {e}")
        return False
    except Exception as e:
        print(f"Database setup failed: {e}")
        return False

# Setup the database immediately on service start
db_ready = setup_database(engine)

# --- Routes ---

@app.route("/")
def dashboard_demo():
    global db_ready # Use the global status flag

    # 1. Check if the database engine is configured and ready
    if not engine or not db_ready:
        # If DB is not ready, show a professional error message page
        error_html = """
        <script src="https://cdn.tailwindcss.com"></script>
        <div class="min-h-screen flex items-center justify-center bg-gray-900 text-white p-4">
            <div class="text-center p-8 bg-gray-800 rounded-xl shadow-2xl max-w-lg w-full">
                <h1 class="text-4xl font-bold text-red-500 mb-4">Critical Configuration Error</h1>
                <p class="text-lg mb-6">Database is not configured or connected. Please check <code class="bg-gray-700 p-1 rounded">DATABASE_URL</code> variable.</p>
                <p class="text-sm text-gray-400">
                    <span class="font-semibold">Current Status:</span> Engine is unavailable or connection failed during startup.
                    <br>
                    <span class="text-yellow-400">Action Required:</span> Ensure the <strong class="text-yellow-300">Internal Database URL</strong> is correctly set in Render's Environment Variables for the 'Nexus-System-Demo' service.
                </p>
            </div>
        </div>
        """
        return render_template_string(error_html), 500

    # 2. If DB is ready, proceed to fetch data for the dashboard
    try:
        with engine.connect() as connection:
            # Get total event count
            total_events = connection.execute(text("SELECT COUNT(id) FROM events")).scalar_one()

            # Get latest 5 events
            latest_events_result = connection.execute(text("SELECT * FROM events ORDER BY timestamp DESC LIMIT 5")).fetchall()
            
            # Format results
            latest_events = []
            for row in latest_events_result:
                latest_events.append({
                    'timestamp': row[1].strftime("%Y-%m-%d %H:%M:%S"),
                    'type': row[2],
                    'data': row[3]
                })

    except Exception as e:
        # Fallback in case a runtime DB error occurs (e.g., connection drop)
        return render_template_string(f"<h1>Dashboard Runtime Error</h1><p>Failed to query database: {e}</p>"), 500

    # 3. Render the actual dashboard
    event_rows = ""
    if not latest_events:
        event_rows = '<tr><td colspan="3" class="p-4 text-center text-gray-500">No events logged yet.</td></tr>'
    else:
        for event in latest_events:
            event_rows += f"""
            <tr class="hover:bg-gray-700">
                <td class="p-4">{event['timestamp']}</td>
                <td class="p-4 font-mono text-sm text-green-400">{event['type']}</td>
                <td class="p-4 text-gray-300 truncate max-w-xs">{event['data']}</td>
            </tr>
            """

    dashboard_html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Nexus Systems Dashboard</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
        <style>
            body {{ font-family: 'Inter', sans-serif; }}
            .card {{ background-color: #1f2937; }}
            .header-bg {{ background-color: #111827; }}
        </style>
    </head>
    <body class="bg-gray-900">
        <div class="min-h-screen p-4 sm:p-8">
            <header class="header-bg p-4 rounded-xl shadow-lg mb-8">
                <h1 class="text-2xl sm:text-3xl font-bold text-white">
                    Nexus Systems: <span class="text-green-400">Live</span> Proof-of-Concept
                </h1>
                <p class="text-gray-400 text-sm">Real-time status monitor and AI endpoint demo.</p>
            </header>

            <div class="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
                <!-- Total Events Card -->
                <div class="card p-6 rounded-xl shadow-xl border-t-4 border-green-500">
                    <p class="text-sm font-semibold text-gray-400 uppercase tracking-wider">Total Events Logged</p>
                    <p class="text-5xl font-extrabold text-white mt-2">{total_events}</p>
                </div>
                <!-- Status Card (Placeholder) -->
                <div class="card p-6 rounded-xl shadow-xl border-t-4 border-blue-500">
                    <p class="text-sm font-semibold text-gray-400 uppercase tracking-wider">AI Integration Status</p>
                    <p class="text-2xl font-bold text-blue-400 mt-2">Active</p>
                    <p class="text-sm text-gray-500">Model: Gemini 2.5 Flash</p>
                </div>
                <!-- Info Card (Placeholder) -->
                <div class="card p-6 rounded-xl shadow-xl border-t-4 border-yellow-500">
                    <p class="text-sm font-semibold text-gray-400 uppercase tracking-wider">Service Uptime</p>
                    <p class="text-2xl font-bold text-yellow-400 mt-2">Running</p>
                    <p class="text-sm text-gray-500">Render Free Tier</p>
                </div>
            </div>

            <!-- Latest Events Table -->
            <div class="card p-4 sm:p-6 rounded-xl shadow-xl">
                <h2 class="text-xl font-bold text-white mb-4 border-b border-gray-700 pb-2">Latest Live Events</h2>
                <div class="overflow-x-auto">
                    <table class="min-w-full text-left text-sm text-gray-300">
                        <thead>
                            <tr class="uppercase text-xs font-semibold text-gray-400 border-b border-gray-700">
                                <th class="p-4">Timestamp</th>
                                <th class="p-4">Event Type</th>
                                <th class="p-4">Data/Message</th>
                            </tr>
                        </thead>
                        <tbody>
                            {event_rows}
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- Footer for the API Key Status -->
            <footer class="mt-8 text-center text-xs text-gray-500">
                <p>
                    API Key Status: 
                    <span class="font-mono p-1 rounded {('bg-green-600 text-white' if openai_api_key else 'bg-red-600 text-white')}" title="OpenAI API Key must be set in Environment Variables">
                        {'Key Set' if openai_api_key else 'Key Missing'}
                    </span>
                    <br>
                    <span class="mt-1 block">To run AI features, ensure the OPENAI_API_KEY is correctly set.</span>
                </p>
            </footer>
        </div>
    </body>
    </html>
    """
    return render_template_string(dashboard_html)

# --- Run the App ---
# Render provides the PORT variable
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # Note: In Render, the startup command handles running the app using gunicorn or similar.
    # We keep this for local testing, but the Render service runs 'gunicorn app:app'
    app.run(host='0.0.0.0', port=port)
