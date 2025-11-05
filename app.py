import os
import json
from flask import Flask, request, jsonify, render_template_string
# IMPORTANT: Added 'func' import for chart data calculation
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime
from openai import OpenAI 

# --- 1. CONFIGURATION ---
API_KEY = os.getenv("OPENAI_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")
PORT = os.getenv("PORT", 8080)
MODEL_NAME = "gemini-2.5-flash" 

if not API_KEY or not DATABASE_URL:
    print("FATAL: OPENAI_API_KEY or DATABASE_URL not set in environment variables.")
    
app = Flask(__name__)
client = OpenAI(api_key=API_KEY)

# --- 2. DATABASE SETUP ---
Base = declarative_base()

class DebugEvent(Base):
    """Stores the ingested debug/error events."""
    __tablename__ = 'debug_events'
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    level = Column(String(50))
    service = Column(String(100))
    message = Column(Text)
    ai_response = Column(Text, nullable=True) 

# Database connection setup
Session = None # Initialize Session globally
try:
    engine = create_engine(DATABASE_URL)
    Base.metadata.create_all(engine)
    # Define Session Class here, making it accessible to all functions
    Session = sessionmaker(bind=engine) 
except Exception as e:
    print(f"FATAL: Database connection failed. Error: {e}")
    # Handle DB failure gracefully

# --- 3. AI DEBUGGING LOGIC ---
SYSTEM_PROMPT = """
You are a highly experienced, professional Level 3 Site Reliability Engineer (SRE) and Debugging Analyst for Nexus Systems.
Your tone must be formal, objective, and solution-oriented. Your task is to perform a root cause analysis (RCA) on the provided error event.
Provide a concise analysis in two sections:
1.  **Root Cause & Impact**: State the core issue and its blast radius.
2.  **Proposed Fix**: Provide a specific, actionable code or configuration fix, preferably in the language of the error (e.g., Python, JavaScript).
Do not use humor, slang, or filler text.
"""

def get_ai_analysis(event_data):
    """Calls the AI model to analyze the error event."""
    # Check if API key is set before calling the client
    if not API_KEY:
        return "AI Analysis Skipped: OPENAI_API_KEY not configured."
        
    try:
        user_prompt = f"Analyze this debug event for RCA and fix:\n\n{json.dumps(event_data, indent=2)}"
        
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.3
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"AI API call failed: {e}")
        return f"AI Analysis Failed: {e}"

# --- 4. FLASK ENDPOINTS ---

@app.route('/health', methods=['GET'])
def health_check():
    """Simple health check endpoint."""
    return jsonify({"status": "ok"})

@app.route('/ingest_event', methods=['POST'])
def ingest_event():
    """Endpoint for external services to send debug events."""
    # Check if Session is defined (i.e., DB connection was successful)
    if Session is None:
        return jsonify({"error": "Database is not configured or connected."}), 503
        
    data = request.json
    if not data or 'level' not in data or 'message' not in data:
        return jsonify({"error": "Invalid payload"}), 400

    # 1. Get AI Analysis 
    ai_analysis = get_ai_analysis(data)

    # 2. Save to Database
    session = Session()
    try:
        new_event = DebugEvent(
            level=data.get('level'),
            service=data.get('service', 'unknown'),
            message=data.get('message'),
            ai_response=ai_analysis
        )
        session.add(new_event)
        session.commit()
    except Exception as e:
        session.rollback()
        print(f"Database save failed: {e}")
        return jsonify({"error": "Database error", "details": str(e)}), 500
    finally:
        session.close()

    return jsonify({
        "status": "success",
        "message": "Event ingested and analyzed.",
        "analysis": ai_analysis
    }), 201

# -------------------------------------------------------------
# ** NEW ENDPOINT FOR INVESTOR DEMO (VISUAL FRONTEND) **
# -------------------------------------------------------------

@app.route('/', methods=['GET'])
def dashboard_demo():
    """
    Renders a simple, visual dashboard for the investor demo.
    Fetches the latest 10 events and displays them with a clean UI.
    """
    # Check if Session is defined (i.e., DB connection was successful)
    if Session is None:
        return "<h1>Dashboard Error</h1><p>Database is not configured or connected. Please check DATABASE_URL variable.</p>"

    session = Session()
    try:
        # Fetch latest 10 events
        events = session.query(DebugEvent).order_by(DebugEvent.timestamp.desc()).limit(10).all()
        
        # Calculate event counts for the chart data
        level_counts = session.query(DebugEvent.level, func.count(DebugEvent.level)).group_by(DebugEvent.level).all()
        chart_data = json.dumps([{"level": level, "count": count} for level, count in level_counts])
        
        # Determine status colors for UI
        def get_status_color(level):
            return {
                'CRITICAL': 'bg-red-500',
                'ERROR': 'bg-yellow-500',
                'WARNING': 'bg-blue-500',
                'INFO': 'bg-gray-500',
            }.get(level.upper(), 'bg-gray-500')

        # Simple HTML Template using Tailwind CSS classes for a modern look
        HTML_TEMPLATE = """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Nexus Systems: Live POC Dashboard</title>
            <script src="https://cdn.tailwindcss.com"></script>
            <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
            <style>
                @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
                body { font-family: 'Inter', sans-serif; background-color: #f7f9fc; }
                .card { background: white; border-radius: 12px; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05); }
                .log-entry { transition: background-color 0.3s; }
                .log-entry:hover { background-color: #f0f4f8; }
            </style>
        </head>
        <body class="p-4 sm:p-8">
            <header class="mb-8 p-4 bg-white rounded-xl shadow-lg border-t-4 border-indigo-600">
                <h1 class="text-3xl font-bold text-gray-900">Nexus Systems: Live Proof-of-Concept</h1>
                <p class="text-sm text-gray-500 mt-1">Unified Observability & AI Root Cause Analysis Demo (Render Live)</p>
                <p class="text-xs mt-2 text-indigo-600 font-semibold">Status: Backend API is Live | Database is Connected | AI Analysis is Active</p>
            </header>

            <!-- KPI & Charts Section -->
            <div class="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
                <div class="card p-6 col-span-1 lg:col-span-2">
                    <h2 class="text-xl font-semibold mb-4 text-gray-700">Event Volume by Severity</h2>
                    <canvas id="eventChart" class="w-full h-80"></canvas>
                </div>
                <div class="card p-6 flex flex-col justify-center items-center space-y-4">
                    <h2 class="text-xl font-semibold text-gray-700">Total Events Logged</h2>
                    <p class="text-6xl font-extrabold text-indigo-600">{{ total_events }}</p>
                    <p class="text-sm text-gray-500">since deployment</p>
                </div>
            </div>

            <!-- Live Event Log & AI Analysis -->
            <div class="card p-6">
                <h2 class="text-xl font-semibold mb-4 text-gray-700">Latest Live Events & AI Root Cause Analysis (RCA)</h2>
                <div class="space-y-4">
                    {% if events %}
                        {% for event in events %}
                            <div class="log-entry p-4 border border-gray-100 rounded-lg">
                                <div class="flex justify-between items-start mb-2">
                                    <span class="px-3 py-1 text-xs font-bold text-white rounded-full {{ event.status_color }}">{{ event.level }}</span>
                                    <span class="text-xs text-gray-500">{{ event.timestamp }}</span>
                                </div>
                                
                                <p class="text-sm font-medium text-gray-800 mb-2">Service: {{ event.service }}</p>
                                <p class="text-sm text-gray-600 italic mb-3">Log Message: "{{ event.message|truncate(150) }}"</p>
                                
                                <!-- AI Analysis Section -->
                                <div class="mt-3 p-3 bg-indigo-50 border-l-4 border-indigo-500 rounded-r-lg">
                                    <p class="text-xs font-semibold text-indigo-700 mb-1">AI RCA (SRE Analyst):</p>
                                    <div class="text-xs text-gray-700 whitespace-pre-wrap">{{ event.ai_response }}</div>
                                </div>
                            </div>
                        {% endfor %}
                    {% else %}
                        <p class="text-center text-gray-500 p-10">No events logged yet. Send a POST request to /ingest_event to see live data.</p>
                    {% endif %}
                </div>
            </div>

            <!-- Chart JavaScript -->
            <script>
                const chartData = JSON.parse('{{ chart_data | safe }}');
                const labels = chartData.map(d => d.level);
                const data = chartData.map(d => d.count);
                const colors = chartData.map(d => {
                    switch (d.level.toUpperCase()) {
                        case 'CRITICAL': return 'rgb(239, 68, 68)';
                        case 'ERROR': return 'rgb(245, 158, 11)';
                        case 'WARNING': return 'rgb(59, 130, 246)';
                        case 'INFO': return 'rgb(107, 114, 128)';
                        default: return 'rgb(75, 192, 192)';
                    }
                });

                new Chart(document.getElementById('eventChart'), {
                    type: 'bar',
                    data: {
                        labels: labels,
                        datasets: [{
                            label: 'Event Count',
                            data: data,
                            backgroundColor: colors,
                            borderRadius: 6,
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: { display: false },
                            title: { display: false }
                        },
                        scales: {
                            y: { beginAtZero: true, ticks: { precision: 0 } }
                        }
                    }
                });
            </script>
        </body>
        </html>
        """
        
        # Prepare data for rendering
        total_events = session.query(DebugEvent).count()
        events_data = [{
            'level': e.level.upper(), 
            'service': e.service, 
            'message': e.message, 
            'ai_response': e.ai_response, 
            'timestamp': e.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC'),
            'status_color': get_status_color(e.level)
        } for e in events]

        # Use render_template_string to inject Python variables into the HTML string
        return render_template_string(
            HTML_TEMPLATE,
            events=events_data,
            chart_data=chart_data,
            total_events=total_events
        )

    except Exception as e:
        # Handle case where DB is empty or connection fails
        return f"<h1>Dashboard Error</h1><p>Could not connect to Database or render dashboard: {e}</p>"
    finally:
        session.close()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT)
