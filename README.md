<img width="1512" height="982" alt="image" src="https://github.com/user-attachments/assets/c1a142c4-a454-4af5-b7aa-126e38495083" /># Triangulate App

A cross-platform PySide6 desktop application designed for triangulation rangefinding laboratory classes. Students learn image processing, sensor calibration, geometric calculations, and closed-loop PID control through simulated and physical hardware.

---

## Key Features

1. **Stage 0: Setup & Scripting (Sandbox)**
   - Custom Python scripting engine running image processing pipelines in a safe thread.
   - Built-in OpenCV, numpy, and logging hooks.
   - Stacked `16:18` aspect ratio screen displaying the original frame and processed binary mask separated by a 10px spacer.
   - Live Spot Location coordinates widget.
   - Exposure settings control.

2. **Stage 1: Empirical Calibration**
   - Collect empirical points mapping camera pixel coordinates ($X_{px}$) to physical distance ($Z$).
   - Fit calibration curves using linear or exponential algorithms.
   - Live distance prediction using fitted calibration equations.

3. **Stage 2: Analytical Modeling**
   - Dashboard displaying live parameters ($B$, $\alpha$, $X_{px}$).
   - Theoretical verification box where students input calculations to verify their results against the geometric triangulation model.
   - **Instructor Cheat Sheet Window** (accessible via standard Preferences shortcut `Cmd+,` on macOS or `Ctrl+,` on Windows/Linux) to view the live theoretical target distance and adjust modes.

4. **Stage 3: Active Tracking**
   - Target distance tracking using closed-loop PID controller steering the laser angle.
   - Auto-sweep mode scanning $0^\circ-180^\circ$ and locking onto the brightest spot reflection.
   - Real-time plotting of target and current positions.

5. **Physical Hardware & Simulation**
   - Automatically falls back to **Simulation Mode** if pigpio/hardware drivers are missing.
   - Real-time logging of physical servo set positioning: outputs `(SERVO_SET_POSITION) <angle>` directly to the main terminal shell.

---

## Installation & Setup

### Prerequisites
* Python 3.10 or higher.
* Raspberry Pi (optional, for physical hardware connection).

### Setup virtual environment
```bash
# Clone the repository and navigate into it
cd lab_triangulacja

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Running the App
Run the main entrypoint:
```bash
python main.py
```

---

## System Shortcuts
* **Settings Dialog & Cheat Sheet:** 
  - macOS: `Cmd + ,`
  - Windows / Linux / Raspberry Pi: `Ctrl + ,`

---

## Lab Geometry Formulas (Stage 2)

To calculate the target distance ($Z$) on paper:

1. **Calculate physical baseline spot displacement ($X_{hit\_mm}$):**
   $$X_{hit\_mm} = \frac{X_{px} - 320.0}{5.0}$$
   *(where $X_{px}$ is the spot position, $320.0$ is the optical center, and $5.0$ px/mm is the scaling factor).*

2. **Calculate target distance ($Z$):**
   $$Z = (B - X_{hit\_mm}) \cdot \tan(\alpha)$$
   *(where $B$ is the Base Distance between camera and laser, and $\alpha$ is the Laser Angle).*

---

## Project Structure

```
├── config.py             # Global UI & Hardware settings
├── main.py               # Main application entry point
├── requirements.txt      # Python dependencies
├── core/
│   ├── camera_worker.py  # Camera frame capture (Live / Simulation)
│   ├── hardware_manager.py # Physical GPIO / Mock servo control
│   ├── pid_controller.py # PID closed loop controller
│   └── script_runner.py  # Scripting execution thread
├── ui/
│   ├── highlighter.py    # Python syntax highlighting
│   ├── main_window.py    # Main window layouts and tabs
│   ├── schematic_widget.py # Interactive vector schematic drawing
│   ├── settings_dialog.py  # Non-modal instructor preferences window
│   ├── styles.qss        # Dark-mode styling sheet
│   └── widgets.py        # Reusable QT parameter widgets
└── utils/
    └── data_logger.py    # CSV exporter utility
```




<img width="1512" height="982" alt="image" src="https://github.com/user-attachments/assets/14a57de4-77ba-41af-811c-5b607a9805a7" />

